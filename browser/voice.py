"""Real WebRTC voice sessions: signaling, provider, transcript and evidence.

Brisa owns the voice provider/session layer; Prisma owns the Desktop client
(RTCPeerConnection, mic controls, shell-voice.jsx); Codex/Nexo compose the
actions on the shell bridge. The Control Plane remains the only tool and
effect authority: voice tool calls from audio are recorded as transcript
segments with provider receipts, never executed here.

Design rules (from contracts.md C07 + task order):
- Microphone opt-in MUST be explicit True before any call; the server never
  implies consent from page state.
- Missing provider is an explicit unavailable state, never a silent fallback.
- SDP/ICE/config/credentials never leak: TURN credentials and provider
  bearers stay server-side; only non-secret ICE server hosts are published.
- call_id binds account/session/principal/project/Space/conversation and the
  originating Run/WorkItem when the server supplies them; the browser never
  chooses owner.
- stop/cancel/revoke are idempotent; tab loss leaves `uncertain` (never
  auto-restart); rebind within a bounded window keeps the same call_id with
  a new generation fence.
- Transcript segments are keyed (call_id, message_id, revision) with monotonic
  revisions and provider receipts, mirroring the streaming contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sentra_mcp.services.chat_access import _ID, _PRINCIPAL, _validate
from sentra_core.conversations import _encode, _decode
from .protected_assets import checkpoint

CALL_TTL_S = 3600
REBIND_WINDOW_S = 300
HEARTBEAT_STALE_S = 120
MAX_SDP_CHARS = 32_768
MAX_TRANSCRIPT_SEGMENTS = 2_000
MAX_SEGMENT_CHARS = 8_000
CALL_ID_PREFIX = "call-"

VOICE_STATUSES = frozenset({
    "starting", "active", "uncertain", "stopped", "revoked", "expired",
})

# Machine-readable action schemas for Codex/Nexo composition and Prisma.
# Shell allowlist names are owned by the bridge (Codex); these schemas fix
# the payload/return contract Brisa implements behind runtime.voice_dispatch.
VOICE_ACTION_SCHEMAS: dict[str, dict[str, Any]] = {
    "voice_start": {
        "payload": {"project_id": "str", "space_id": "str",
                    "conversation_id": "ID",
                    "offer_sdp": "SDP string 1..32768",
                    "microphone_opt_in": "literal True",
                    "requested_model": "optional str 1..120",
                    "requested_effort": "optional str 1..120",
                    "request_key": "idempotency 1..200 (shell envelope)"},
        "returns": {"call_id": "call-<hex>", "answer_sdp": "SDP string",
                    "status": "active|uncertain", "transcript": "[]",
                    "provider": "configured name",
                    "provider_call_ref": "opaque provider ref or null",
                    "start_request_key": "echo of request_key"},
    },
    "voice_signal": {
        "payload": {"call_id": "str",
                    "kind": "ice-candidate|heartbeat|transcript|rebind",
                    "candidate": "optional ICE candidate (ice-candidate)",
                    "offer_sdp": "optional replacement SDP (rebind)",
                    "segments": "optional transcript segments (transcript)"},
        "returns": {"call_id": "str", "status": "voice status",
                    "generation": "current fence int",
                    "answer_sdp": "fresh SDP answer (rebind success only)",
                    "segments_recorded": "int (transcript only)"},
    },
    "voice_status": {
        "payload": {"call_id": "optional when start_request_key given",
                    "start_request_key": "optional origin request_key"},
        "returns": {"call_id": "str", "status": "voice status",
                    "transcript": "[{message_id, role, content, revision, receipt, verified}]",
                    "provider": "name", "generation": "int"},
    },
    "voice_stop": {
        "payload": {"call_id": "str", "start_request_key": "origin key",
                    "request_key": "idempotency key"},
        "returns": {"call_id": "str", "status": "stopped",
                    "idempotent_replay": "bool"},
    },
    "voice_revoke": {
        "payload": {"call_id": "str", "start_request_key": "origin key",
                    "request_key": "idempotency key"},
        "returns": {"call_id": "str", "status": "revoked",
                    "transcript_sealed": True, "idempotent_replay": "bool"},
    },
}


class VoiceUnavailable(RuntimeError):
    """Explicit missing-provider state; never a silent fallback."""


def _provider_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Explicit provider configuration. Only documented transports are valid.

    Supported kind: "openai-realtime" — the public OpenAI Realtime API over
    REST+SDP (ephemeral session mint, SDP offer/answer exchange, call
    status poll, call close). No assumed/generic signaling server: an
    unrecognized kind fails closed at config time.
    """
    if not isinstance(config, dict):
        return None
    provider = config.get("voice_provider")
    if not isinstance(provider, dict):
        return None
    kind = provider.get("kind", "openai-realtime")
    if kind != "openai-realtime":
        raise ValueError("unsupported voice provider kind: %r" % (kind,))
    base_url = provider.get("base_url", "https://api.openai.com/v1")
    if not isinstance(base_url, str) or not base_url:
        raise ValueError("voice provider base_url must be a non-empty string")
    parsed = urlsplit(base_url)
    if parsed.scheme == "https" and parsed.hostname:
        pass
    elif (parsed.scheme == "http"
          and parsed.hostname in {"127.0.0.1", "localhost"}):
        pass
    else:
        raise ValueError("voice provider base_url must be https or loopback http")
    model = provider.get("model", "gpt-realtime")
    if not isinstance(model, str) or not 1 <= len(model) <= 120:
        raise ValueError("voice provider model must be 1..120 characters")
    voice = provider.get("voice")
    if voice is not None and (not isinstance(voice, str) or not 1 <= len(voice) <= 80):
        raise ValueError("voice provider voice must be 1..80 characters")
    name = provider.get("name", kind)
    if not isinstance(name, str) or not 1 <= len(name) <= 80:
        raise ValueError("voice provider name must be 1..80 characters")
    return {"kind": kind, "name": name, "base_url": base_url.rstrip("/"),
            "model": model, "voice": voice,
            "ice_servers": provider.get("ice_servers") or []}


def _provider_api_key(config: dict[str, Any] | None) -> str:
    """Server-side provider credential. Never published to any renderer."""
    if isinstance(config, dict):
        provider = config.get("voice_provider") or {}
        direct = provider.get("api_key")
        if isinstance(direct, str) and len(direct) >= 16:
            return direct
        path = provider.get("bearer_file") or provider.get("api_key_file")
        if isinstance(path, str) and path:
            try:
                value = Path(path).expanduser().read_text(encoding="utf-8").strip()
            except OSError:
                value = ""
            if len(value) >= 16:
                return value
        legacy = config.get("voice_provider_bearer")
        if isinstance(legacy, str) and len(legacy) >= 16:
            return legacy
    for variable in ("SENTRA_VOICE_PROVIDER_API_KEY",
                     "SENTRA_VOICE_PROVIDER_BEARER"):
        value = os.environ.get(variable, "").strip()
        if len(value) >= 16:
            return value
    return ""


def _provider_bearer(config: dict[str, Any] | None) -> str:
    return _provider_api_key(config)


def _ice_server_entries(raw: Any) -> list[dict[str, Any]]:
    """Normalize configured ICE servers to RTCIceServer {urls} (no secrets).

    The Desktop RTCPeerConnection requires RTCIceServer dicts, not bare
    hosts. Accepts config strings ("stun:host:port", "host:port", "host" with
    stun:/3478 defaults) or dicts {"urls": [...]}. TURN username/credential
    fields are stripped: short-lived TURN credentials must be issued
    out-of-band by the operator, never published to the renderer.
    """
    if not isinstance(raw, list):
        return []
    servers: list[dict[str, Any]] = []
    for entry in raw[:8]:
        urls: list[str] = []
        if isinstance(entry, str) and 1 <= len(entry) <= 256:
            text = entry.strip()
            if text.startswith(("stun:", "stuns:", "turn:", "turns:")):
                urls = [text]
            elif text and all(c not in text for c in " \t\"'"):
                host, _, port = text.partition(":")
                urls = ["stun:%s:%s" % (host, port or "3478")]
        elif isinstance(entry, dict):
            values = entry.get("urls")
            candidates = values if isinstance(values, list) else [values]
            for candidate in candidates[:4]:
                if isinstance(candidate, str) and 1 <= len(candidate) <= 256:
                    urls.append(candidate.strip())
        urls = [u for u in urls if u]
        if urls:
            servers.append({"urls": urls})
    return servers


class OpenAIRealtimeTransport:
    """GA Realtime WebRTC transport: multipart POST /realtime/calls.

    The server keeps its API key; Location authenticates the rtc_ call ID.
    Read-only sideband receives transcripts over /realtime?call_id=.
    POST /realtime/calls/{id}/hangup releases media. No guessed GET poll,
    DELETE call, legacy session mint, or renderer receipt verification.
    Each HTTP/sideband connection checks the current central physical context.
    Sources: official OpenAI Create call, Hang up call, server-side controls
    with voice-api=realtime, consulted 2026-10-11; no provider was executed.
    """

    def __init__(self, provider: dict[str, Any], api_key: str) -> None:
        self.provider = provider
        self.api_key = api_key
        self._ephemeral: str = ""
        self._ephemeral_expires: float = 0.0
        self.response_headers: dict[str, str] = {}
        from .realtime_sideband import RealtimeSideband
        self.sideband = RealtimeSideband(provider["base_url"], api_key)

    def _request(self, method: str, path: str, *, bearer: str,
                 body: bytes | None = None,
                 content_type: str = "application/json",
                 timeout: float = 15.0) -> tuple[int, bytes]:
        request = urllib.request.Request(
            self.provider["base_url"] + path, data=body, method=method,
            headers={"Authorization": "Bearer " + bearer})
        if body is not None:
            request.add_header("Content-Type", content_type)
            request.add_header("Content-Length", str(len(body)))
        try:
            checkpoint(required=True)
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    raise VoiceUnavailable("voice provider redirect refused")
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                self.response_headers = dict(response.headers.items())
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise VoiceUnavailable("voice provider response outside bounds")
                return response.status, raw
        except urllib.error.HTTPError as exc:
            raise VoiceUnavailable(
                "voice provider HTTP %s" % exc.code) from exc
        except Exception as exc:
            raise VoiceUnavailable(
                "voice provider request failed (%s)" % type(exc).__name__) from exc

    def exchange_offer(self, offer_sdp: str, *, model: str | None = None) -> dict[str, str]:
        from urllib.parse import quote as _quote

        session: dict[str, Any] = {"type": "realtime", "model": model or self.provider["model"],
                   "tools": [], "audio": {"input": {"transcription": {
                       "model": "gpt-4o-mini-transcribe"}}}}
        if self.provider.get("voice"):
            session["audio"]["output"] = {"voice": self.provider["voice"]}
        boundary = "sentra-" + uuid.uuid4().hex
        body = ("--" + boundary + '\r\nContent-Disposition: form-data; name="sdp"\r\n'
                "Content-Type: application/sdp\r\n\r\n" + offer_sdp + "\r\n--" + boundary +
                '\r\nContent-Disposition: form-data; name="session"\r\n'
                "Content-Type: application/json\r\n\r\n" + json.dumps(session) +
                "\r\n--" + boundary + "--\r\n").encode()
        status, raw = self._request(
            "POST", "/realtime/calls", bearer=self.api_key,
            body=body, content_type="multipart/form-data; boundary=" + boundary)
        if status not in {200, 201}:
            raise VoiceUnavailable("voice SDP exchange failed: HTTP %s" % status)
        answer = raw.decode("utf-8", "replace")
        if not answer or "v=" not in answer:
            raise VoiceUnavailable("voice provider returned no SDP answer")
        location = next((v for k, v in self.response_headers.items() if k.lower() == "location"), "")
        match = re.fullmatch(r"(?:https://[^/]+)?/v1/realtime/calls/(rtc_[A-Za-z0-9_-]{1,196})", location)
        if match is None:
            raise VoiceUnavailable("SDP received without authenticated call Location; reconcile, never resend")
        call_ref = match.group(1)
        return {"answer_sdp": answer, "call_ref": call_ref}

    def poll_call(self, call_ref: str) -> dict[str, Any]:
        if not call_ref:
            return {"live": False, "reason": "no provider call ref"}
        from urllib.parse import quote as _quote

        try:
            events = self.sideband.drain(call_ref)
        except VoiceUnavailable as exc:
            return {"live": False, "reason": str(exc)[:200]}
        return {"live": True, "provider_status": "sideband_connected", "events": events}

    def close_call(self, call_ref: str) -> None:
        if not call_ref:
            return
        from urllib.parse import quote as _quote

        try:
            self._request("POST", "/realtime/calls/" + _quote(call_ref, safe="") + "/hangup",
                          bearer=self.api_key, timeout=8.0)
        finally:
            self.sideband.detach(call_ref)

    def verify_segment(self, *, call_ref: str, receipt: str) -> tuple[bool, str]:
        """Server-side receipt check. Item-level REST verification is
        unsupported by the provider protocol, so segments stay provisional.
        Returns (verified, reason)."""
        if not isinstance(receipt, str) or not receipt:
            return False, "transcript segment lacks a provider receipt"
        # Renderer receipts are never an attestation. Only the authenticated
        # sideband ingress below can create verified transcript segments.
        return False, ("provider protocol has no server-side transcript-item "
                       "endpoint; client-supplied segments are provisional and "
                       "tool-role segments are denied")


class VoiceSessionLedger:
    """Durable voice calls + transcripts in the shared chat_access database."""

    def __init__(self, store) -> None:
        self.store = store
        db = self.store.connect("chat_access")
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS voice_calls(
                    call_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    project_id TEXT NOT NULL, space_id TEXT,
                    conversation_id TEXT NOT NULL, run_id TEXT,
                    work_item_id TEXT, provider TEXT NOT NULL,
                    generation INTEGER NOT NULL, status TEXT NOT NULL,
                    start_request_key TEXT NOT NULL,
                    answer_sdp TEXT, provider_call_ref TEXT,
                    created REAL NOT NULL, updated REAL NOT NULL,
                    expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS voice_requests(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL,
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    call_id TEXT NOT NULL, result TEXT,
                    PRIMARY KEY(owner,project_id,request_key));
                CREATE TABLE IF NOT EXISTS voice_transcripts(
                    call_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    role TEXT NOT NULL, revision INTEGER NOT NULL,
                    content_sha256 TEXT NOT NULL, content_chars INTEGER NOT NULL,
                    truncated INTEGER NOT NULL, receipt TEXT,
                    observed REAL NOT NULL,
                    PRIMARY KEY(call_id,message_id,revision));
                CREATE INDEX IF NOT EXISTS voice_transcripts_lookup
                    ON voice_transcripts(call_id,message_id,revision);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(voice_transcripts)")}
            if "content" not in columns:
                db.execute("ALTER TABLE voice_transcripts ADD COLUMN content TEXT")
            if "verified" not in columns:
                db.execute("ALTER TABLE voice_transcripts ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE TABLE IF NOT EXISTS voice_provider_events("
                       "owner TEXT NOT NULL,call_id TEXT NOT NULL,generation INTEGER NOT NULL,"
                       "event_id TEXT NOT NULL,protected_event TEXT NOT NULL,"
                       "PRIMARY KEY(owner,call_id,generation,event_id))")
            db.execute("CREATE TABLE IF NOT EXISTS voice_effect_requests("
                       "owner TEXT NOT NULL,project_id TEXT NOT NULL,request_key TEXT NOT NULL,"
                       "call_id TEXT NOT NULL,fingerprint TEXT NOT NULL,protected_result TEXT,"
                       "PRIMARY KEY(owner,project_id,request_key))")
            db.commit()
        finally:
            db.close()


class VoiceRuntime:
    """Shell-composed voice provider. Constructed server-side, never in renderers.

    Codex wires an instance as shell runtime (voice_availability /
    voice_dispatch). All identity (owner/project/conversation/Run/WorkItem)
    comes from the authenticated server envelope, never the browser.
    """

    def __init__(self, state_root, config: dict[str, Any] | None = None,
                 *, store=None, clock=time.time) -> None:
        self.state_root = Path(state_root)
        self.config = config or {}
        if store is None:
            from sentra_mcp.services.control_store import create_control_plane_store
            store = create_control_plane_store(self.state_root)
        self.ledger = VoiceSessionLedger(store)
        self.store = store
        self.clock = clock
        self._cached_transport: OpenAIRealtimeTransport | None = None

    # -- availability ----------------------------------------------------
    def voice_availability(self, project_id: str, owner: str) -> dict[str, Any]:
        try:
            provider = _provider_config(self.config)
        except ValueError as exc:
            return {"available": False, "reason": str(exc)[:300],
                    "provider": None, "ice_servers": []}
        if provider is None:
            return {"available": False,
                    "reason": "voice provider is not configured",
                    "provider": None, "ice_servers": []}
        if not _provider_api_key(self.config):
            return {"available": False,
                    "reason": "voice provider credentials are not configured",
                    "provider": provider["name"], "ice_servers": []}
        return {"available": True, "reason": "ready",
                "provider": provider["name"],
                "ice_servers": _ice_server_entries(provider["ice_servers"]),
                # Honest availability: configured credentials exist, but the
                # transport is proven only by a real voice_start SDP exchange.
                # Signaling is server-side; media stays peer-to-peer; nothing
                # here proves model delivery or transcript authenticity.
                "probed": False, "transport": "WebRTC and server sideband",
                "proves_delivery": False}

    # -- dispatch --------------------------------------------------------
    def voice_dispatch(self, project_id: str, owner: str, action: str,
                       payload: dict[str, Any], request_key: str | None) -> dict[str, Any]:
        if action == "voice_status":
            return self._status(owner, project_id, payload)
        if action == "voice_start":
            return self._start(project_id, owner, payload, request_key)
        if action == "voice_signal":
            return self._signal(project_id, owner, payload, request_key)
        if action in {"voice_stop", "voice_revoke"}:
            return self._finish(project_id, owner, action, payload, request_key)
        raise ValueError("unsupported voice action")

    # -- internals -------------------------------------------------------
    def _transport(self) -> OpenAIRealtimeTransport:
        provider = _provider_config(self.config)
        if provider is None:
            raise VoiceUnavailable("voice provider is not configured")
        api_key = _provider_api_key(self.config)
        if not api_key:
            raise VoiceUnavailable("voice provider credentials are not configured")
        if (self._cached_transport is None or self._cached_transport.provider != provider
                or self._cached_transport.api_key != api_key):
            self._cached_transport = OpenAIRealtimeTransport(provider, api_key)
        return self._cached_transport

    def _start(self, project_id: str, owner: str, payload: dict[str, Any],
               request_key: str | None) -> dict[str, Any]:
        _validate("principal", owner, _PRINCIPAL)
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
            raise ValueError("voice_start requires request_key 1..200")
        space_id = payload.get("space_id")
        conversation = payload.get("conversation") or {}
        conversation_id = payload.get("conversation_id") or conversation.get("conversation_id")
        _validate("conversation identity", conversation_id, _ID)
        if payload.get("microphone_opt_in") is not True:
            raise PermissionError("microphone opt-in is required before the call")
        offer = payload.get("offer_sdp")
        if (not isinstance(offer, str) or not 1 <= len(offer) <= MAX_SDP_CHARS
                or "v=" not in offer):
            raise ValueError("voice_start requires a complete SDP offer")
        requested_model = payload.get("requested_model")
        if requested_model is not None and (
                not isinstance(requested_model, str) or not 1 <= len(requested_model) <= 120):
            raise ValueError("requested_model must be 1..120 characters")
        requested_effort = payload.get("requested_effort")
        if requested_effort is not None and (
                not isinstance(requested_effort, str) or not 1 <= len(requested_effort) <= 120):
            raise ValueError("requested_effort must be 1..120 characters")
        fingerprint = hashlib.sha256(json.dumps(
            {"offer": offer, "conversation_id": conversation_id, "space_id": space_id,
             "run_id": conversation.get("run_id"), "work_item_id": conversation.get("work_item_id"),
             "model": requested_model, "effort": requested_effort},
            sort_keys=True).encode()).hexdigest()
        now = self.clock()
        db = self.store.connect("chat_access")
        try:
            # Phase 1: reserve idempotency and COMMIT before any network I/O.
            # No DB transaction is ever held across the provider exchange, and
            # a crash after this point leaves a reservation the same
            # request_key reconciles instead of duplicating provider effect.
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM voice_requests WHERE owner=? AND project_id=? AND request_key=?",
                                  (owner, project_id, request_key)).fetchone()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    db.rollback()
                    raise ValueError("request_key already used for another voice intent")
                if existing["result"]:
                    result = {**_decode(existing["result"]),
                              "idempotent_replay": True}
                    db.rollback()
                    return result
                reserved_call_id = existing["call_id"]
                db.rollback()
                return self._reconcile_start(owner, project_id, request_key,
                                             reserved_call_id, conversation_id or "")
            call_id = CALL_ID_PREFIX + uuid.uuid4().hex
            db.execute("INSERT INTO voice_requests VALUES(?,?,?,?,?,?)",
                       (owner, project_id, request_key, fingerprint, call_id, None))
            db.commit()
            transport = self._transport()
            provider_name = transport.provider["name"]
            # Phase 2: network exchange with NO open transaction.
            try:
                answer = transport.exchange_offer(
                    offer, model=requested_model)
                exchange_failed = None
            except VoiceUnavailable as exc:
                answer = None
                exchange_failed = exc
            # Phase 3: persist the outcome in one short transaction.
            db.execute("BEGIN IMMEDIATE")
            if answer is None:
                db.execute("INSERT INTO voice_calls VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (call_id, owner, project_id,
                            space_id if isinstance(space_id, str) else None,
                            conversation_id,
                            conversation.get("run_id") if isinstance(conversation.get("run_id"), str) else None,
                            conversation.get("work_item_id") if isinstance(conversation.get("work_item_id"), str) else None,
                            provider_name, 1, "uncertain", request_key,
                            None, None, now, now, now + CALL_TTL_S))
                db.commit()
                return {"call_id": call_id, "answer_sdp": None,
                        "status": "uncertain", "transcript": [],
                        "provider": provider_name,
                        "start_request_key": request_key,
                        "reason": "provider did not answer (%s); reconcile with the same request_key"
                                  % str(exchange_failed)[:160]}
            result = {"call_id": call_id, "answer_sdp": answer["answer_sdp"],
                      "status": "active", "transcript": [],
                      "provider": provider_name,
                      "start_request_key": request_key,
                      "provider_call_ref": answer.get("call_ref") or None}
            db.execute("UPDATE voice_requests SET result=? WHERE owner=? AND project_id=? AND request_key=?",
                       (_encode(result), owner, project_id, request_key))
            db.execute("INSERT INTO voice_calls VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (call_id, owner, project_id,
                        space_id if isinstance(space_id, str) else None,
                        conversation_id,
                        conversation.get("run_id") if isinstance(conversation.get("run_id"), str) else None,
                        conversation.get("work_item_id") if isinstance(conversation.get("work_item_id"), str) else None,
                        provider_name, 1, "active", request_key, _encode(answer["answer_sdp"]),
                        answer.get("call_ref") if isinstance(answer.get("call_ref"), str) else None,
                        now, now, now + CALL_TTL_S))
            db.commit()
            # Open the authenticated observer before media starts at the peer.
            # Absence of the optional observer does not invent verification.
            try:
                transport.sideband.attach(answer["call_ref"])
                result["transcript_ingress"] = {"available": True, "verified_segments_only": True}
            except (ImportError, RuntimeError, OSError) as exc:
                result["transcript_ingress"] = {"available": False, "reason": type(exc).__name__}
            return result
        except BaseException:
            try:
                db.rollback()
            except Exception:
                pass
            raise
        finally:
            db.close()

    def _reconcile_start(self, owner: str, project_id: str, request_key: str,
                         call_id: str, conversation_id: str) -> dict[str, Any]:
        """Resolve a reserved-but-unfinished start without provider effect."""
        db = self.store.connect("chat_access")
        try:
            row = db.execute("SELECT * FROM voice_calls WHERE call_id=? AND owner=?",
                             (call_id, owner)).fetchone()
        finally:
            db.close()
        if row is None:
            # Reserved before the exchange, crashed before persisting: the
            # provider effect may or may not have happened, so the call stays
            # uncertain and the SAME request_key must be reused to finish it.
            try:
                configured = _provider_config(self.config)
                provider_name = configured["name"] if configured else "unknown"
            except ValueError:
                provider_name = "unknown"
            return {"call_id": call_id, "answer_sdp": None,
                    "status": "uncertain", "transcript": [],
                    "provider": provider_name,
                    "start_request_key": request_key,
                    "reason": "start was interrupted before the provider outcome persisted; "
                              "retry voice_start with the same request_key"}
        self._check_scope(row, project_id, {"conversation_id": conversation_id})
        return self._status(owner, project_id, {"call_id": row["call_id"]})

    @staticmethod
    def _check_scope(row, project_id: str, payload: dict[str, Any]) -> None:
        """Server-owned scope fence: project always, space/conversation when
        the authenticated envelope supplies them (root passes the canonical
        conversation). Owner was already fenced by the lookup."""
        if row["project_id"] != project_id:
            raise PermissionError("voice call belongs to another project")
        for key in ("space_id", "conversation_id"):
            wanted = payload.get(key)
            if isinstance(wanted, str) and wanted and row[key] != wanted:
                raise PermissionError("voice call belongs to another %s" % key)

    def _lookup(self, db, owner: str, payload: dict[str, Any], project_id: str):
        call_id = payload.get("call_id")
        if isinstance(call_id, str) and call_id:
            row = db.execute("SELECT * FROM voice_calls WHERE call_id=? AND owner=?",
                             (call_id, owner)).fetchone()
            if row is None:
                raise PermissionError("voice call belongs to another owner or is unknown")
            return row
        key = payload.get("start_request_key")
        if isinstance(key, str) and key:
            row = db.execute("SELECT c.* FROM voice_calls c JOIN voice_requests r "
                             "ON r.call_id=c.call_id WHERE r.owner=? AND r.project_id=? AND r.request_key=?",
                             (owner, project_id, key)).fetchone()
            if row is None:
                raise PermissionError("voice call origin is unknown")
            return row
        raise ValueError("voice_status requires call_id or start_request_key")

    def _transcript_view(self, db, call_id: str) -> list[dict[str, Any]]:
        rows = db.execute("SELECT message_id,role,revision,content,content_sha256,content_chars,"
                          "truncated,receipt,verified,observed "
                          "FROM voice_transcripts WHERE call_id=? "
                          "ORDER BY observed ASC LIMIT ?",
                          (call_id, MAX_TRANSCRIPT_SEGMENTS)).fetchall()
        result = []
        for row in rows:
            content = _decode(row["content"]) if row["content"] else ""
            if (not isinstance(content, str) or len(content) != row["content_chars"]
                    or hashlib.sha256(content.encode()).hexdigest() != row["content_sha256"]):
                raise PermissionError("voice transcript protected content differs from receipt")
            result.append({"message_id": row["message_id"], "role": row["role"],
                "revision": row["revision"], "content": content, "content_chars": row["content_chars"],
                "truncated": bool(row["truncated"]), "receipt": row["receipt"],
                "verified": bool(row["verified"]),
                "source": "provider_sideband" if row["verified"] else "renderer_provisional",
                "overflow": {"call_id": call_id, "provider_event_id": row["receipt"]}
                    if row["truncated"] and row["verified"] else None})
        return result

    def _status(self, owner: str, project_id: str,
                payload: dict[str, Any]) -> dict[str, Any]:
        _validate("principal", owner, _PRINCIPAL)
        db = self.store.connect("chat_access")
        try:
            try:
                row = self._lookup(db, owner, payload, project_id)
            except PermissionError:
                # Reservation exists but the call row was never persisted
                # (crash between reserve and outcome): report uncertain so the
                # same request_key reconciles instead of duplicating effect.
                key = payload.get("start_request_key")
                reserved = db.execute("SELECT * FROM voice_requests WHERE owner=? AND project_id=? AND request_key=?",
                                      (owner, project_id, key)).fetchone() if isinstance(key, str) else None
                if reserved is None or reserved["project_id"] != project_id:
                    raise
                try:
                    configured = _provider_config(self.config)
                    provider_name = configured["name"] if configured else "unknown"
                except ValueError:
                    provider_name = "unknown"
                return {"call_id": reserved["call_id"], "answer_sdp": None,
                        "status": "uncertain", "transcript": [],
                        "provider": provider_name,
                        "start_request_key": key,
                        "reason": "start was interrupted before the provider outcome persisted; "
                                  "retry voice_start with the same request_key"}
            self._check_scope(row, project_id, payload)
            now = self.clock()
            status = str(row["status"])
            if status in {"active", "starting", "uncertain"} and now > float(row["expires_at"]):
                db.execute("BEGIN IMMEDIATE")
                db.execute("UPDATE voice_calls SET status='expired',updated=? WHERE call_id=?",
                           (now, row["call_id"]))
                db.commit()
                status = "expired"
            return {"call_id": row["call_id"], "status": status,
                    "transcript": self._transcript_view(db, row["call_id"]),
                    "provider": row["provider"],
                    "generation": int(row["generation"])}
        finally:
            db.close()

    def _ingest_sideband(self, owner, row):
        """Only host-authenticated provider events can set verified=True.

        Reading an event supplies provenance, never ChatTrust or a Grant.
        Generation/scope and terminal state are rechecked after provider I/O.
        """
        from .realtime_sideband import RealtimeSideband
        ref = row["provider_call_ref"]
        if row["status"] != "active":
            return {"available": False, "reason": "voice generation requires explicit reconciliation"}
        if not ref:
            return {"available": False, "reason": "provider call reference unavailable"}
        try:
            events = self._transport().sideband.drain(ref)
        except (ImportError, RuntimeError, OSError) as exc:
            with self.store.connect("chat_access") as db:
                db.execute("UPDATE voice_calls SET status='uncertain' WHERE owner=? AND call_id=? AND generation=? AND status='active'",
                           (owner, row["call_id"], row["generation"]))
            return {"available": False, "reason": "sideband unavailable: " + type(exc).__name__}
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM voice_calls WHERE owner=? AND call_id=?",
                                 (owner, row["call_id"])).fetchone()
            if (current is None or current["generation"] != row["generation"]
                    or current["provider_call_ref"] != ref or current["status"] != "active"
                    or self.clock() > current["expires_at"]):
                raise PermissionError("sideband belongs to an inactive voice generation")
            count = db.execute("SELECT COUNT(*) FROM voice_transcripts WHERE call_id=?",
                               (row["call_id"],)).fetchone()[0]
            recorded = 0
            for event in events:
                segment = RealtimeSideband.transcript(event)
                if segment is None:
                    continue
                event_id = segment["provider_receipt"]
                protected_event = {"v":1,"owner":owner,"project_id":row["project_id"],
                    "call_id":row["call_id"],"generation":row["generation"],"call_ref":ref,
                    "conversation_id":row["conversation_id"],"run_id":row["run_id"],
                    "work_item_id":row["work_item_id"],"event":event}
                existing = db.execute("SELECT protected_event FROM voice_provider_events "
                    "WHERE owner=? AND call_id=? AND generation=? AND event_id=?",
                    (owner, row["call_id"], row["generation"], event_id)).fetchone()
                if existing is not None:
                    if _decode(existing["protected_event"]) != protected_event:
                        raise PermissionError("provider event identity has conflicting content")
                    continue
                if count + recorded >= MAX_TRANSCRIPT_SEGMENTS:
                    raise ValueError("voice transcript retention budget exceeded")
                message_id = "voice-" + hashlib.sha256(
                    (ref + ":" + segment["message_id"]).encode()).hexdigest()[:32]
                latest = db.execute("SELECT MAX(revision) AS rev FROM voice_transcripts "
                    "WHERE call_id=? AND message_id=?", (row["call_id"], message_id)).fetchone()["rev"]
                revision = (latest or 0) + 1
                stored = segment["content"][:MAX_SEGMENT_CHARS]
                digest = hashlib.sha256(stored.encode()).hexdigest()
                db.execute("INSERT INTO voice_provider_events VALUES(?,?,?,?,?)",
                    (owner, row["call_id"], row["generation"], event_id, _encode(protected_event)))
                db.execute("INSERT INTO voice_transcripts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (row["call_id"], message_id, segment["role"], revision, digest, len(stored),
                     int(len(stored) != len(segment["content"])), event_id, self.clock(), _encode(stored), 1))
                recorded += 1
            db.commit()
            return {"available": True, "segments_recorded": recorded, "tools_executed": False}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _reserve_effect(self, db, owner, project_id, call_id, request_key, payload):
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
            raise ValueError("voice effect requires durable request_key")
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        prior = db.execute("SELECT * FROM voice_effect_requests WHERE owner=? AND project_id=? AND request_key=?",
                           (owner, project_id, request_key)).fetchone()
        if prior is not None:
            if prior["call_id"] != call_id or prior["fingerprint"] != fingerprint:
                raise PermissionError("voice request_key conflicts with recorded effect")
            return {**_decode(prior["protected_result"]), "idempotent_replay": True} if prior["protected_result"] else {
                "call_id": call_id, "status": "uncertain", "automatic_retry": False,
                "requires_reconciliation": True}
        db.execute("INSERT INTO voice_effect_requests VALUES(?,?,?,?,?,NULL)",
                   (owner, project_id, request_key, call_id, fingerprint))
        return None

    def _signal(self, project_id: str, owner: str,
                payload: dict[str, Any], request_key: str | None = None) -> dict[str, Any]:
        _validate("principal", owner, _PRINCIPAL)
        call_id = payload.get("call_id")
        kind = payload.get("kind")
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("voice_signal requires call_id")
        if kind not in {"ice-candidate", "heartbeat", "transcript", "rebind"}:
            raise ValueError("unsupported voice signal kind")
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM voice_calls WHERE call_id=? AND owner=?",
                             (call_id, owner)).fetchone()
            if row is None:
                raise PermissionError("voice call belongs to another owner or is unknown")
            self._check_scope(row, project_id, payload)
            rebind_intent = None
            if kind == "rebind":
                offer = payload.get("offer_sdp")
                if not isinstance(offer, str) or not 1 <= len(offer) <= MAX_SDP_CHARS or "v=" not in offer:
                    raise ValueError("rebind requires a complete replacement SDP offer")
                rebind_intent = {"kind":"rebind","call_id":call_id,
                    "offer_sha256":hashlib.sha256(offer.encode()).hexdigest(),"generation":payload.get("generation")}
                prior_row = db.execute("SELECT 1 FROM voice_effect_requests WHERE owner=? AND project_id=? AND request_key=?",
                                       (owner,project_id,request_key)).fetchone()
                if prior_row is not None:
                    # Replay compares the original intent before current
                    # generation/terminal checks; never renegotiates again.
                    return self._reserve_effect(db,owner,project_id,call_id,request_key,rebind_intent)
            if payload.get("generation") is not None and payload["generation"] != row["generation"]:
                raise PermissionError("voice generation changed")
            now = self.clock()
            if row["status"] in {"stopped", "revoked", "expired"}:
                raise ValueError("voice call is already %s" % row["status"])
            if kind == "heartbeat":
                db.execute("UPDATE voice_calls SET updated=?,expires_at=? WHERE call_id=?",
                           (now, now + CALL_TTL_S, call_id))
                db.commit()
                sideband = self._ingest_sideband(owner, row)
                return {"call_id": call_id, "status": str(row["status"]),
                        "generation": int(row["generation"]), "transcript_ingress": sideband}
            if kind == "ice-candidate":
                candidate = payload.get("candidate")
                if not isinstance(candidate, dict):
                    raise ValueError("ice-candidate requires a candidate object")
                db.execute("UPDATE voice_calls SET updated=? WHERE call_id=?",
                           (now, call_id))
                db.commit()
                return {"call_id": call_id, "status": str(row["status"]),
                        "generation": int(row["generation"]),
                        "candidate_accepted": False,
                        "reason": "non-trickle SDP negotiated; ICE candidate is observation only"}
            if kind == "rebind":
                # Tab loss recovery with real media renegotiation: the
                # replacement SDP offer is exchanged with the provider for a
                # fresh answer (new provider ref, old ref closed best-effort)
                # while SENTRA keeps the same call_id with generation+1.
                # Allowed only inside the rebind window after the last update;
                # anything older must start a new call explicitly. Provider
                # failure leaves the reserved generation uncertain; replay of
                # the SAME key only observes the original protected outcome.
                if now - float(row["updated"]) > REBIND_WINDOW_S:
                    raise ValueError("rebind window elapsed; start a new call")
                offer = payload.get("offer_sdp")
                if (not isinstance(offer, str) or not 1 <= len(offer) <= MAX_SDP_CHARS
                        or "v=" not in offer):
                    raise ValueError("rebind requires a complete replacement SDP offer")
                transport = self._transport()
                prior = self._reserve_effect(db, owner, project_id, call_id, request_key,
                    rebind_intent)
                if prior is not None:
                    return prior
                generation = int(row["generation"]) + 1
                db.execute("UPDATE voice_calls SET generation=?,status='uncertain',updated=? WHERE call_id=?",
                           (generation, now, call_id))
                db.commit()
                try:
                    answer = transport.exchange_offer(offer)
                except VoiceUnavailable as exc:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("UPDATE voice_calls SET status='uncertain',updated=? WHERE call_id=?",
                               (now, call_id))
                    db.commit()
                    return {"call_id": call_id, "status": "uncertain",
                            "generation": generation,
                            "answer_sdp": None,
                            "reason": "provider renegotiation failed: %s" % str(exc)[:200]}
                release = "confirmed"
                try:
                    transport.close_call(str(row["provider_call_ref"] or ""))
                except VoiceUnavailable:
                    release = "uncertain"
                db.execute("BEGIN IMMEDIATE")
                changed = db.execute("UPDATE voice_calls SET generation=?,status='active',answer_sdp=?,"
                           "provider_call_ref=?,updated=?,expires_at=? WHERE call_id=? AND generation=? AND status='uncertain'",
                           (generation, _encode(answer["answer_sdp"]),
                            answer.get("call_ref") if isinstance(answer.get("call_ref"), str) else None,
                            now, now + CALL_TTL_S, call_id, generation)).rowcount
                result = {"call_id": call_id, "status": "active" if changed == 1 else "uncertain", "generation": generation,
                          "rebound": changed == 1, "answer_sdp": answer["answer_sdp"] if changed == 1 else None,
                          "provider_call_ref": answer.get("call_ref"),
                          "requires_reconciliation": changed != 1, "previous_provider_release": release}
                db.execute("UPDATE voice_effect_requests SET protected_result=? WHERE owner=? AND project_id=? AND request_key=?",
                           (_encode(result), owner, project_id, request_key))
                db.commit()
                return result
            # kind == "transcript": client-supplied segments are PROVISIONAL
            # until verified server-side against the trusted provider.
            # Verification polls the provider; the current documented Realtime
            # protocol has no item-level REST endpoint, so segments stay
            # verified=false and tool-role segments are DENIED (they can never
            # authorize effects). Display use must surface the verified flag.
            segments = payload.get("segments")
            if not isinstance(segments, list) or not segments or len(segments) > 64:
                raise ValueError("transcript signal requires 1..64 segments")
            count = db.execute("SELECT COUNT(*) FROM voice_transcripts WHERE call_id=?",
                               (call_id,)).fetchone()[0]
            transport = self._transport()
            recorded = 0
            for segment in segments:
                if not isinstance(segment, dict):
                    raise ValueError("transcript segment must be an object")
                message_id = segment.get("message_id")
                role = segment.get("role")
                content = segment.get("content")
                receipt = segment.get("provider_receipt")
                _validate("message identity", message_id, _ID)
                if role not in {"user", "assistant", "tool"}:
                    raise ValueError("transcript role must be user, assistant or tool")
                if not isinstance(content, str) or not content:
                    raise ValueError("transcript content must be non-empty text")
                if not isinstance(receipt, str) or not receipt:
                    raise PermissionError("transcript segment lacks a provider receipt")
                revision = segment.get("revision")
                if type(revision) is not int or revision < 1:
                    raise ValueError("transcript revision must be a positive integer")
                latest = db.execute("SELECT MAX(revision) AS rev FROM voice_transcripts "
                                    "WHERE call_id=? AND message_id=?",
                                    (call_id, message_id)).fetchone()["rev"]
                if latest is not None and revision <= int(latest):
                    raise ValueError("transcript revision must increase per message")
                if int(count) >= MAX_TRANSCRIPT_SEGMENTS:
                    raise ValueError("transcript segment budget exceeded for call")
                verified, _reason = transport.verify_segment(
                    call_ref=str(row["provider_call_ref"] or ""), receipt=receipt)
                if role == "tool" and not verified:
                    raise PermissionError(
                        "tool transcript segment is unverified by the provider: %s" % _reason[:200])
                truncated = len(content) > MAX_SEGMENT_CHARS
                stored = content[:MAX_SEGMENT_CHARS]
                digest = hashlib.sha256(stored.encode("utf-8")).hexdigest()
                db.execute("INSERT INTO voice_transcripts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (call_id, message_id, role, revision, digest,
                            len(stored), int(truncated), receipt[:400], now,
                            _encode(stored), int(bool(verified))))
                count = int(count) + 1
                recorded += 1
            db.execute("UPDATE voice_calls SET updated=? WHERE call_id=?",
                       (now, call_id))
            db.commit()
            return {"call_id": call_id, "status": str(row["status"]),
                    "generation": int(row["generation"]),
                    "segments_recorded": recorded}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _finish(self, project_id: str, owner: str, action: str,
                payload: dict[str, Any], request_key: str | None) -> dict[str, Any]:
        _validate("principal", owner, _PRINCIPAL)
        call_id = payload.get("call_id")
        origin = payload.get("start_request_key")
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("%s requires call_id" % action)
        if not isinstance(origin, str) or not origin:
            raise ValueError("%s requires start_request_key" % action)
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
            raise ValueError("%s requires request_key 1..200" % action)
        target = "stopped" if action == "voice_stop" else "revoked"
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM voice_calls WHERE call_id=? AND owner=?",
                             (call_id, owner)).fetchone()
            if row is None:
                raise PermissionError("voice call belongs to another owner or is unknown")
            self._check_scope(row, project_id, payload)
            if row["start_request_key"] != origin:
                raise PermissionError("voice origin key mismatch")
            prior = self._reserve_effect(db, owner, project_id, call_id, request_key,
                                         {"action": action, "call_id": call_id, "origin": origin})
            if prior is not None:
                return prior
            if row["status"] == target or row["status"] == "revoked":
                result = {"call_id": call_id, "status": row["status"],
                          "transcript_sealed": row["status"] == "revoked", "idempotent_replay": True}
                db.execute("UPDATE voice_effect_requests SET protected_result=? WHERE owner=? AND project_id=? AND request_key=?",
                           (_encode(result), owner, project_id, request_key))
                db.commit()
                return result
            now = self.clock()
            # Best-effort provider release; local state commits regardless so
            # the client always cleans up immediately. Provider failure never
            # blocks stop/revoke and never resurrects the call.
            provider_error = None
            db.execute("UPDATE voice_calls SET status=?,updated=? WHERE call_id=?",
                       (target, now, call_id))
            db.commit()  # local revoke + request reservation precede external hangup
            try:
                self._transport().close_call(str(row["provider_call_ref"] or ""))
            except VoiceUnavailable as exc:
                provider_error = str(exc)[:200]
            result = {"call_id": call_id, "status": target,
                                      "idempotent_replay": False}
            if action == "voice_revoke":
                result["transcript_sealed"] = True
            if provider_error:
                result["provider_release"] = "uncertain: " + provider_error
            else:
                result["provider_release"] = "hangup_accepted" if row["provider_call_ref"] else "unavailable"
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE voice_effect_requests SET protected_result=? WHERE owner=? AND project_id=? AND request_key=?",
                       (_encode(result), owner, project_id, request_key))
            db.commit()
            return result
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def provider_event(self, owner, project_id, *, call_id, generation, event_id):
        """Recover original transcript overflow with exact owner/call scope."""
        _validate("principal", owner, _PRINCIPAL)
        db = self.store.connect("chat_access")
        try:
            call = db.execute("SELECT project_id,conversation_id,run_id,work_item_id FROM voice_calls WHERE owner=? AND call_id=?",
                              (owner, call_id)).fetchone()
            if call is None or call["project_id"] != project_id:
                raise PermissionError("voice event belongs to another project/owner")
            row = db.execute("SELECT protected_event FROM voice_provider_events "
                "WHERE owner=? AND call_id=? AND generation=? AND event_id=?",
                (owner, call_id, generation, event_id)).fetchone()
        finally:
            db.close()
        if row is None:
            raise FileNotFoundError("provider event not recoverable for this generation")
        envelope = _decode(row["protected_event"])
        if (not isinstance(envelope,dict) or envelope.get("v") != 1
                or any(envelope.get(key) != value for key,value in {"owner":owner,"project_id":project_id,
                    "call_id":call_id,"generation":generation,"conversation_id":call["conversation_id"],
                    "run_id":call["run_id"],"work_item_id":call["work_item_id"]}.items())):
            raise PermissionError("provider event lacks exact protected voice scope")
        event = envelope.get("event")
        if not isinstance(event, dict) or event.get("event_id") != event_id:
            raise PermissionError("provider event ciphertext identity mismatch")
        return {"call_id": call_id, "generation": generation, "provider_event": event,
                "tools_authorized": False, "grants_created": False}

    def protect_legacy_storage(self, owner, project_id, *, operator_approved=False):
        """Explicit, centrally admitted local migration using existing OS keys.

        Never treats SQLite secure_delete or replacement as forensic erasure;
        PostgreSQL legacy plaintext requires the administrator retention path.
        """
        if operator_approved is not True:
            raise PermissionError("operator-approved voice storage migration required")
        if getattr(self.store, "backend", "sqlite") != "sqlite":
            raise PermissionError("hosted legacy voice storage requires administrator retention migration")
        checkpoint(required=True)
        _validate("principal", owner, _PRINCIPAL)
        db = self.store.connect("chat_access")
        changed = 0
        try:
            db.execute("BEGIN IMMEDIATE")
            calls = db.execute("SELECT call_id,answer_sdp FROM voice_calls WHERE owner=? AND project_id=?",
                               (owner, project_id)).fetchall()
            for call in calls:
                raw = call["answer_sdp"]
                if raw and not raw.startswith(("dpapi:", "keyring:")):
                    if not isinstance(raw, str) or not 1 <= len(raw) <= MAX_SDP_CHARS:
                        raise PermissionError("legacy SDP outside bounds")
                    db.execute("UPDATE voice_calls SET answer_sdp=? WHERE owner=? AND call_id=?",
                               (_encode(raw), owner, call["call_id"]))
                    changed += 1
                segments = db.execute("SELECT message_id,revision,content,content_sha256,content_chars FROM voice_transcripts WHERE call_id=?",
                                      (call["call_id"],)).fetchall()
                for segment in segments:
                    raw = segment["content"]
                    if raw is not None and not raw.startswith(("dpapi:", "keyring:")):
                        if (len(raw) != segment["content_chars"] or len(raw) > MAX_SEGMENT_CHARS
                                or hashlib.sha256(raw.encode()).hexdigest() != segment["content_sha256"]):
                            raise PermissionError("legacy transcript differs from its receipt")
                        db.execute("UPDATE voice_transcripts SET content=?,verified=0 WHERE call_id=? AND message_id=? AND revision=?",
                                   (_encode(raw), call["call_id"], segment["message_id"], segment["revision"]))
                        changed += 1
            requests = db.execute("SELECT request_key,result FROM voice_requests WHERE owner=? AND project_id=? AND result IS NOT NULL",
                                  (owner, project_id)).fetchall()
            for request in requests:
                raw = request["result"]
                if not raw.startswith(("dpapi:", "keyring:")):
                    value = json.loads(raw)
                    if not isinstance(value, dict) or not isinstance(value.get("call_id"), str):
                        raise PermissionError("legacy voice request receipt malformed")
                    db.execute("UPDATE voice_requests SET result=? WHERE owner=? AND project_id=? AND request_key=?",
                               (_encode(value), owner, project_id, request["request_key"]))
                    changed += 1
            checkpoint(required=True)
            db.commit()
            return {"protected_rows": changed, "forensic_erasure": False, "grants_created": False}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
