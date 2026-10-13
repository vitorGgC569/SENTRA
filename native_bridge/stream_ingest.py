"""Streaming ingest: Brisa frames -> Rastro durable history (Rastro).

Composes `browser/streaming.py::StreamingLedger` (Brisa, partial prefix +
overflow ref keyed by durable message_id/revision) with
`sentra_mcp/services/web_history_store.py::WebHistoryStore` (Rastro,
OS-protected bodies keyed by the same message_id/revision) and the
`AuthenticatedWebFrameIngress` host proof.

Rules: frames are data, never delivery proof. A frame is stored only for a
durable message_id resolved via `message_identity` (never a DOM index
alone), with a monotonically increasing revision enforced on BOTH ledgers.
Oversized bodies keep Brisa's overflow_ref; the durable store keeps its own
quota (131072 bytes) and rejects over-quota frames instead of truncating
silently. Also provides the `assistant_attestor` callback factory used by
`WebSendAuthority`/`DurableWebTransport`, bound to the same revision and
the Brisa streaming ledger observation.
"""
from __future__ import annotations

from typing import Any


def record_stream_frame(control: Any, history: Any, streaming: Any, *,
                        owner: str, run_id: str, browser_principal: str,
                        request_id: str, worker: str, conversation_id: str,
                        message_id: str, revision: int, role: str, state: str,
                        text: str, identity_epoch: str | None = None) -> dict[str, Any]:
    """Persist one observed frame on both ledgers after exact proof."""
    from native_bridge.message_identity import resolve_by_request
    from native_bridge.web_evidence_ingress import AuthenticatedWebReceiptBroker
    if role not in ("assistant", "user", "tool") or state not in ("partial", "complete"):
        raise ValueError("invalid Web message role/state")
    if not isinstance(text, str):
        raise ValueError("stream text required")
    binding = resolve_by_request(control, browser_principal=browser_principal,
                                 request_id=request_id)
    if binding["message_id"] != message_id or binding["worker"] != worker:
        raise PermissionError("stream frame worker/message binding mismatch")
    if (binding["identity_epoch"] is not None
            and identity_epoch is not None
            and binding["identity_epoch"] != identity_epoch):
        raise PermissionError("stream frame identity epoch mismatch")
    broker = AuthenticatedWebReceiptBroker(control, relay=None)
    workspace = broker.prove_message(
        owner=owner, run_id=run_id, browser_principal=browser_principal,
        request_id=request_id, worker=worker, conversation_id=conversation_id,
        message_id=message_id, identity_epoch=identity_epoch)
    frame = streaming.record_frame(principal=browser_principal,
                                   conversation_id=conversation_id,
                                   message_id=message_id, revision=revision,
                                   text=text)
    stored = history.record_frame(
        owner, workspace, conversation_id=conversation_id, message_id=message_id,
        revision=revision, role=role, state=state, body=text)
    return {"message_id": message_id, "revision": revision,
            "workspace": workspace, "overflow_ref": frame.get("overflow_ref"),
            "truncated": frame.get("truncated"),
            "idempotent_replay": stored.get("idempotent_replay", False),
            "grants_created": False}


def assistant_attestor_from_streaming(control: Any, streaming: Any, *, host_observer=None):
    """Require independent host proof; renderer streaming is only content data.

    host_observer(**expected) is a SERVER-SELECTED callback. It independently
    reads the owned physical browser, proves role/parent/full body/doc/epoch,
    and returns {**expected, authenticated:True, host_observation:{revision,
    body_sha256,state,collector_id,source_sha256,document_id,identity_epoch}}.
    No callback, prefix-only evidence or renderer ledger => unauthenticated.
    Host revision and renderer frame revision are distinct clocks.
    """
    def attest(**expected: Any) -> dict[str, Any]:
        from contextlib import closing
        import hashlib
        import re
        try:
            if not callable(host_observer) or expected.get("role") != "assistant" or expected.get("state") not in {"partial", "complete"}:
                return {"authenticated": False, "reason": "independent_host_observer_required"}
            for key in ("owner", "run_id", "job_id", "worker", "conversation_id", "message_id", "parent_user_message_id", "identity_epoch"):
                if not isinstance(expected.get(key), str) or not expected[key]:
                    return {"authenticated": False}
            if (type(expected.get("revision")) is not int or not 0 <= expected["revision"] <= 1000000
                    or not re.fullmatch(r"[a-f0-9]{64}", str(expected.get("body_sha256", "")))):
                return {"authenticated": False}
            with closing(control.store.connect("session_checkpoint")) as db:
                receipt = db.execute("SELECT r.*,i.work_item_id,i.operation_id,i.principal_id,i.workspace,"
                    "i.worker AS send_worker,i.send_fence FROM authenticated_web_receipts r "
                    "JOIN web_send_intents i ON i.job_id=r.job_id AND i.owner=r.owner AND i.run_id=r.run_id "
                    "WHERE r.job_id=? AND r.owner=? AND r.run_id=?",
                    (expected["job_id"], expected["owner"], expected["run_id"])).fetchone()
            if (receipt is None or not receipt["send_fence"]
                    or receipt["worker"] != expected["worker"] or receipt["send_worker"] != expected["worker"]
                    or receipt["conversation_id"] != expected["conversation_id"]
                    or receipt["message_id"] != expected["parent_user_message_id"]
                    or receipt["message_id"] == expected["message_id"]
                    or receipt["identity_epoch"] != expected["identity_epoch"]):
                return {"authenticated": False}
            run = control.durable.run_status(expected["run_id"], expected["owner"], include_details=False)
            operation = control.durable.operation_status(receipt["operation_id"], expected["owner"])
            work = control.work_item_info(receipt["work_item_id"], expected["owner"])
            if (run.get("workspace") != receipt["workspace"] or operation["run_id"] != expected["run_id"]
                    or work["run_id"] != expected["run_id"] or work.get("assignee_agent_id") != receipt["principal_id"]):
                return {"authenticated": False}
            from .message_identity import resolve_by_request
            from .web_evidence_ingress import AuthenticatedWebReceiptBroker
            binding = resolve_by_request(control, browser_principal=receipt["browser_principal"], request_id=receipt["request_id"])
            if (binding["message_id"] != expected["parent_user_message_id"] or binding["worker"] != expected["worker"]
                    or not binding["document_id"] or binding["identity_epoch"] != expected["identity_epoch"]):
                return {"authenticated": False}
            AuthenticatedWebReceiptBroker(control, None).prove_message(owner=expected["owner"], run_id=expected["run_id"],
                browser_principal=receipt["browser_principal"], request_id=receipt["request_id"], worker=expected["worker"],
                conversation_id=expected["conversation_id"], message_id=expected["parent_user_message_id"],
                document_id=binding["document_id"], identity_epoch=expected["identity_epoch"])
            # Matching prefix hashes do not prove the full body. Recover the
            # exact protected frame and compare its full SHA before host I/O.
            latest = streaming.latest(receipt["browser_principal"], expected["conversation_id"], expected["message_id"])
            if not latest.get("present") or latest.get("revision") != expected["revision"]:
                return {"authenticated": False}
            content = streaming.read_content(receipt["browser_principal"], expected["conversation_id"], expected["message_id"], expected["revision"])
            if content["sha256"] != expected["body_sha256"] or hashlib.sha256(content["content"].encode()).hexdigest() != expected["body_sha256"]:
                return {"authenticated": False}
            selectors = {**expected, "browser_principal": receipt["browser_principal"], "request_id": receipt["request_id"],
                         "document_id": binding["document_id"], "work_item_id": receipt["work_item_id"],
                         "operation_id": receipt["operation_id"], "workspace": receipt["workspace"]}
            observed = host_observer(**selectors)
            if (not isinstance(observed, dict) or observed.get("authenticated") is not True
                    or any(observed.get(key) != value for key, value in selectors.items())):
                return {"authenticated": False}
            host = observed.get("host_observation")
            if (not isinstance(host, dict) or type(host.get("revision")) is not int or host["revision"] < 1
                    or host.get("body_sha256") != expected["body_sha256"] or host.get("state") != expected["state"]
                    or host.get("document_id") != binding["document_id"] or host.get("identity_epoch") != expected["identity_epoch"]
                    or not isinstance(host.get("collector_id"), str) or not host["collector_id"]
                    or not re.fullmatch(r"[a-f0-9]{64}", str(host.get("source_sha256", "")))):
                return {"authenticated": False}
            return {**selectors, "authenticated": True, "host_observation": {
                key: host[key] for key in ("revision", "body_sha256", "state", "collector_id",
                                          "source_sha256", "document_id", "identity_epoch")}}
        except (PermissionError, ValueError, KeyError, AttributeError, FileNotFoundError, OSError, RuntimeError):
            return {"authenticated": False, "reason": "scoped_host_observation_unavailable"}
    return attest
