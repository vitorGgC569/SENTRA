"""Slack/Telegram/WhatsApp triggers and notifications, subordinate to the
Control Plane.

Ownership split per contract: Lume owns adapters/protocol/transports;
this module owns the trigger/notification boundary that Pulso drives into
routines, workflows and receipts.

- Inbound: webhook events are authenticated with real signature
  verification (Slack ``v0`` HMAC-SHA256 with timestamp tolerance,
  Telegram ``secret_token`` constant-time comparison, WhatsApp Meta
  ``X-Hub-Signature-256`` HMAC-SHA256), checked against a replay window
  and an explicit workspace/user allowlist, deduplicated by provider
  event ID, and staged as trigger claims. Task admission itself stays
  with the host's existing central admission callback. An external
  identity never confers a grant.
- Outbound: notifications are staged with idempotent dedupe keys and
  delivered only through the host-injected sender. ``SENT`` records the
  provider ACK; ``DELIVERED`` is marked exclusively after a durable
  receipt is observed. A service ACK is never presented as task
  completion.
- Lifecycle: ``enable`` / ``renew`` / ``disable`` / ``revoke``. Disable
  removes the external subscription through the injected unsubscriber and
  records its receipt; revoke additionally purges the secret reference
  and the allowlist.

Secret material is never persisted here: only a ``secret_id`` reference
is stored, resolved per-call through the host-injected ``secret_resolver``.
Without the host callbacks every mutating path fails explicitly instead
of simulating delivery.
"""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .workflow_contracts import digest, ident

CHANNELS = frozenset({"slack", "telegram", "whatsapp"})
STATES = frozenset({"ENABLED", "DISABLED", "REVOKED"})
REPLAY_WINDOW_SECONDS = 300.0


class ChannelDenied(ValueError):
    pass


def verify_slack_signature(*, secret: str, timestamp: str,
                           raw_body: bytes, signature: str,
                           now: float) -> None:
    """Verify a Slack ``X-Slack-Signature`` header value.

    Raises :class:`ChannelDenied` on any mismatch, stale timestamp or
    malformed envelope. Pure function: the caller resolves the secret.
    """
    if not isinstance(secret, str) or not secret:
        raise ChannelDenied("Slack signing secret not configured")
    if not isinstance(raw_body, (bytes, bytearray)) or len(raw_body) > 2_000_000:
        raise ChannelDenied("invalid Slack webhook body")
    try:
        event_time = float(timestamp)
    except (TypeError, ValueError):
        raise ChannelDenied("invalid Slack request timestamp")
    if abs(now - event_time) > REPLAY_WINDOW_SECONDS:
        raise ChannelDenied("stale Slack webhook (replay window exceeded)")
    if not isinstance(signature, str) or not signature.startswith("v0="):
        raise ChannelDenied("invalid Slack signature envelope")
    expected = "v0=" + hmac.new(secret.encode(),
                                f"v0:{timestamp}:".encode() + bytes(raw_body),
                                hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ChannelDenied("Slack signature mismatch")


def verify_telegram_secret(*, expected_token: str, provided_token: str) -> None:
    """Verify Telegram's ``X-Telegram-Bot-Api-Secret-Token`` header."""
    if not isinstance(expected_token, str) or not expected_token:
        raise ChannelDenied("Telegram secret token not configured")
    if not isinstance(provided_token, str) or not hmac.compare_digest(
            expected_token, provided_token):
        raise ChannelDenied("Telegram secret token mismatch")


def verify_whatsapp_signature(*, secret: str, raw_body: bytes,
                              signature: str) -> None:
    """Verify Meta's ``X-Hub-Signature-256`` header value (``sha256=...``)."""
    if not isinstance(secret, str) or not secret:
        raise ChannelDenied("WhatsApp app secret not configured")
    if not isinstance(raw_body, (bytes, bytearray)) or len(raw_body) > 2_000_000:
        raise ChannelDenied("invalid WhatsApp webhook body")
    if not isinstance(signature, str) or not signature.startswith("sha256="):
        raise ChannelDenied("invalid WhatsApp signature envelope")
    expected = "sha256=" + hmac.new(secret.encode(), bytes(raw_body),
                                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ChannelDenied("WhatsApp signature mismatch")


class ChannelTriggerBridge:
    """Trigger/notification boundary for messaging channels."""

    def __init__(self, database: str, *, workspace: str,
                 secret_resolver: Callable | None = None,
                 trigger_admitter: Callable | None = None,
                 trigger_lookup: Callable | None = None,
                 outbound_sender: Callable | None = None,
                 external_unsubscriber: Callable | None = None,
                 clock=time.time, control=None, channel_service=None) -> None:
        self.control = control
        self.channel_service = channel_service
        root, target = Path(workspace).resolve(), Path(database).resolve()
        if target == root or not target.is_relative_to(root):
            raise ValueError("channel projection outside workspace")
        from .workflow_storage import projection_path
        projection_path(database,workspace,control=control)
        self.database, self.clock = str(target), clock
        self.secret_resolver = secret_resolver
        self.trigger_admitter = trigger_admitter
        self.trigger_lookup = trigger_lookup
        self.outbound_sender = outbound_sender
        self.external_unsubscriber = external_unsubscriber
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS channel_subscriptions(
                subscription_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                channel TEXT NOT NULL, project_id TEXT NOT NULL,
                allow_workspaces TEXT NOT NULL, allow_users TEXT NOT NULL,
                secret_id TEXT, external_subscription_id TEXT,
                state TEXT NOT NULL, expires_at REAL,
                created REAL NOT NULL, updated REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS channel_inbound_events(
                subscription_id TEXT NOT NULL, event_id TEXT NOT NULL,
                event_sha256 TEXT NOT NULL, sender TEXT NOT NULL,
                work_item_id TEXT, received REAL NOT NULL,
                PRIMARY KEY(subscription_id, event_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS channel_outbound(
                dedupe_key TEXT PRIMARY KEY, subscription_id TEXT NOT NULL,
                recipient TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                protected_payload TEXT,
                provider_message_id TEXT, state TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS channel_senders(
                subscription_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                connector_id TEXT NOT NULL, updated REAL NOT NULL)""")
            from .workflow_storage import ensure_column
            ensure_column(db,"channel_outbound","protected_payload","TEXT")
            ensure_column(db,"channel_outbound","operation_id","TEXT")

    @contextmanager
    def _db(self):
        from .workflow_storage import projection_db
        with projection_db(self.database,control=self.control) as conn:
            yield conn

    # -- lifecycle -----------------------------------------------------
    def enable(self, *, owner: str, subscription_id: str, channel: str,
               project_id: str, allow_workspaces: list[str],
               allow_users: list[str], secret_id: str | None,
               external_subscription_id: str | None = None,
               ttl_seconds: float | None = None,
               operator_approved: bool = False) -> dict[str, Any]:
        if operator_approved is not True:
            raise PermissionError("host owner approval required to enable channel")
        if channel not in CHANNELS:
            raise ChannelDenied("unknown messaging channel")
        ident(subscription_id)
        if not isinstance(owner, str) or not owner:
            raise ChannelDenied("owner scope required")
        if not isinstance(project_id, str) or not project_id:
            raise ChannelDenied("project scope required")
        for allowlist in (allow_workspaces, allow_users):
            if (not isinstance(allowlist, list) or not allowlist
                    or len(allowlist) > 500
                    or any(not isinstance(entry, str) or not entry
                           or len(entry) > 256 for entry in allowlist)):
                raise ChannelDenied("non-empty bounded channel allowlist required")
        if secret_id is not None and (
                not isinstance(secret_id, str) or not secret_id):
            raise ChannelDenied("invalid channel secret reference")
        expires = (self.clock() + float(ttl_seconds)) if ttl_seconds else None
        if ttl_seconds is not None and not 60 <= ttl_seconds <= 31_536_000:
            raise ChannelDenied("subscription TTL must be 60..31536000 seconds")
        now = self.clock()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM channel_subscriptions "
                             "WHERE subscription_id=?", (subscription_id,)).fetchone()
            if old is not None and old["state"] == "REVOKED":
                raise ChannelDenied("revoked channel subscription cannot be re-enabled")
            if old is not None and (old["owner"], old["channel"]) != (owner, channel):
                raise ChannelDenied("subscription already bound to another scope")
            db.execute(
                "INSERT INTO channel_subscriptions VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(subscription_id) DO UPDATE SET state='ENABLED',"
                "allow_workspaces=excluded.allow_workspaces,"
                "allow_users=excluded.allow_users,secret_id=excluded.secret_id,"
                "external_subscription_id=excluded.external_subscription_id,"
                "expires_at=excluded.expires_at,updated=excluded.updated",
                (subscription_id, owner, channel, project_id,
                 ",".join(sorted(set(allow_workspaces))),
                 ",".join(sorted(set(allow_users))), secret_id,
                 external_subscription_id, "ENABLED", expires, now, now))
        return self.info(subscription_id, owner)

    def renew(self, *, owner: str, subscription_id: str,
              ttl_seconds: float,
              operator_approved: bool = False) -> dict[str, Any]:
        if operator_approved is not True:
            raise PermissionError("host owner approval required to renew channel")
        if not 60 <= float(ttl_seconds) <= 31_536_000:
            raise ChannelDenied("subscription TTL must be 60..31536000 seconds")
        with self._db() as db:
            row = db.execute("SELECT * FROM channel_subscriptions "
                             "WHERE subscription_id=?", (subscription_id,)).fetchone()
            if row is None:
                raise FileNotFoundError("channel subscription not found")
            if row["owner"] != owner:
                raise PermissionError("subscription belongs to another owner")
            if row["state"] != "ENABLED":
                raise ChannelDenied("only an enabled subscription can be renewed")
            db.execute("UPDATE channel_subscriptions SET expires_at=?,updated=? "
                       "WHERE subscription_id=?",
                       (self.clock() + float(ttl_seconds), self.clock(),
                        subscription_id))
        return self.info(subscription_id, owner)

    def disable(self, *, owner: str, subscription_id: str,
                operator_approved: bool = False) -> dict[str, Any]:
        """Disable and remove the external subscription, with receipt."""
        if operator_approved is not True:
            raise PermissionError("host owner approval required to disable channel")
        with self._db() as db:
            row = db.execute("SELECT * FROM channel_subscriptions "
                             "WHERE subscription_id=?", (subscription_id,)).fetchone()
            if row is None:
                raise FileNotFoundError("channel subscription not found")
            if row["owner"] != owner:
                raise PermissionError("subscription belongs to another owner")
            if row["state"] == "REVOKED":
                raise ChannelDenied("revoked subscription stays revoked")
            db.execute("UPDATE channel_subscriptions SET state='DISABLED',updated=? "
                       "WHERE subscription_id=?", (self.clock(), subscription_id))
        removal: dict[str, Any] = {"external_removal": "no external subscription id"}
        if row["external_subscription_id"]:
            if self.external_unsubscriber is None:
                raise ChannelDenied(
                    "no external unsubscriber configured; external subscription "
                    f"{row['external_subscription_id']} must be removed by the host")
            removal = self.external_unsubscriber(
                row["channel"], row["external_subscription_id"])
            if not isinstance(removal, dict) or removal.get("removed") is not True:
                raise ChannelDenied("external subscription removal unconfirmed")
        return {"subscription_id": subscription_id, "state": "DISABLED",
                "removal_receipt": removal}

    def revoke(self, *, owner: str, subscription_id: str,
               operator_approved: bool = False) -> dict[str, Any]:
        """Revoke: disable plus purge secret reference and allowlists."""
        outcome = self.disable(owner=owner, subscription_id=subscription_id,
                               operator_approved=operator_approved)
        with self._db() as db:
            db.execute("UPDATE channel_subscriptions SET state='REVOKED',secret_id=NULL,"
                       "allow_workspaces='',allow_users='',updated=? "
                       "WHERE subscription_id=?", (self.clock(), subscription_id))
        return {**outcome, "state": "REVOKED", "secret_purged": True,
                "allowlists_cleared": True}

    def info(self, subscription_id: str, owner: str) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute("SELECT * FROM channel_subscriptions "
                             "WHERE subscription_id=?", (subscription_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("channel subscription not found")
        if row["owner"] != owner:
            raise PermissionError("subscription belongs to another owner")
        item = dict(row)
        item.pop("secret_id", None)
        return {**item, "secret_configured": row["secret_id"] is not None,
                "secret_material": "never exposed"}

    def list(self, owner: str, limit: int = 100) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ChannelDenied("channel page limit must be 1..500")
        with self._db() as db:
            rows = db.execute("SELECT subscription_id,channel,project_id,state,"
                              "expires_at,updated FROM channel_subscriptions "
                              "WHERE owner=? ORDER BY updated DESC LIMIT ?",
                              (owner, limit)).fetchall()
        return [dict(row) for row in rows]

    # -- inbound -------------------------------------------------------
    def _secret(self, secret_id: str | None) -> str:
        if not secret_id:
            raise ChannelDenied("channel has no signing secret configured")
        if self.secret_resolver is None:
            raise ChannelDenied("no channel secret resolver configured")
        secret = self.secret_resolver(secret_id)
        if not isinstance(secret, str) or not secret:
            raise ChannelDenied("channel secret resolution failed")
        return secret

    def ingest(self, *, subscription_id: str, event_id: str,
               sender: str, sender_workspace: str,
               payload: dict, raw_body: bytes,
               signature: str, timestamp: str | None = None) -> dict[str, Any]:
        """Authenticate, allowlist, dedupe and stage one inbound event."""
        if self.trigger_admitter is None:
            raise ChannelDenied(
                "no central trigger admission configured; inbound channel "
                "events refuse to invent tasks")
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 256:
            raise ChannelDenied("bounded provider event ID required")
        if not isinstance(payload, dict):
            raise ChannelDenied("channel event payload must be a mapping")
        digest(payload)
        with self._db() as db:
            subscription = db.execute(
                "SELECT * FROM channel_subscriptions WHERE subscription_id=?",
                (subscription_id,)).fetchone()
        if subscription is None:
            raise FileNotFoundError("channel subscription not found")
        if subscription["state"] != "ENABLED":
            raise ChannelDenied("channel subscription is not enabled")
        if (subscription["expires_at"] is not None
                and self.clock() >= subscription["expires_at"]):
            raise ChannelDenied("channel subscription expired; renew first")
        secret = self._secret(subscription["secret_id"])
        channel = subscription["channel"]
        if channel == "slack":
            verify_slack_signature(secret=secret, timestamp=timestamp or "",
                                   raw_body=raw_body, signature=signature,
                                   now=self.clock())
        elif channel == "telegram":
            verify_telegram_secret(expected_token=secret, provided_token=signature)
        elif channel == "whatsapp":
            verify_whatsapp_signature(secret=secret, raw_body=raw_body,
                                      signature=signature)
        else:
            raise ChannelDenied("unknown messaging channel")
        allowed_workspaces = set(filter(None, subscription["allow_workspaces"].split(",")))
        allowed_users = set(filter(None, subscription["allow_users"].split(",")))
        if sender_workspace not in allowed_workspaces or sender not in allowed_users:
            raise ChannelDenied("sender not on the channel allowlist")
        event_sha = digest({"event_id": event_id, "sender": sender,
                            "payload": payload})
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM channel_inbound_events "
                             "WHERE subscription_id=? AND event_id=?",
                             (subscription_id, event_id)).fetchone()
            if old is not None:
                if old["event_sha256"] != event_sha:
                    raise ChannelDenied("event ID bound to different content")
                return {"event_id": event_id, "status": "REUSED",
                        "work_item_id": old["work_item_id"]}
            db.execute("INSERT INTO channel_inbound_events VALUES(?,?,?,?,?,?)",
                       (subscription_id, event_id, event_sha, sender, None,
                        self.clock()))
        admitted = self.trigger_admitter(channel, subscription_id, event_id,
                                         {"sender": sender, "payload": payload})
        if not isinstance(admitted, dict) or not admitted.get("work_item_id"):
            raise ChannelDenied("central trigger admission returned no WorkItem")
        with self._db() as db:
            db.execute("UPDATE channel_inbound_events SET work_item_id=? "
                       "WHERE subscription_id=? AND event_id=?",
                       (admitted["work_item_id"], subscription_id, event_id))
        return {"event_id": event_id, "status": "ADMITTED",
                "work_item_id": admitted["work_item_id"]}

    def reconcile_inbound(self, *, subscription_id: str,
                          event_id: str) -> dict[str, Any] | None:
        """Recover a claim whose admission reply was lost (lookup only)."""
        if self.trigger_lookup is None:
            raise ChannelDenied("no central trigger lookup configured")
        with self._db() as db:
            claim = db.execute("SELECT * FROM channel_inbound_events "
                               "WHERE subscription_id=? AND event_id=?",
                               (subscription_id, event_id)).fetchone()
        if claim is None:
            return None
        if claim["work_item_id"] is not None:
            return {"event_id": event_id, "status": "ADMITTED",
                    "work_item_id": claim["work_item_id"]}
        found = self.trigger_lookup(subscription_id, event_id)
        if isinstance(found, dict) and found.get("work_item_id"):
            with self._db() as db:
                db.execute("UPDATE channel_inbound_events SET work_item_id=? "
                           "WHERE subscription_id=? AND event_id=?",
                           (found["work_item_id"], subscription_id, event_id))
            return {"event_id": event_id, "status": "RECOVERED",
                    "work_item_id": found["work_item_id"]}
        return {"event_id": event_id, "status": "PENDING"}

    def inbound_events(self, owner: str, subscription_id: str,
                       limit: int = 100) -> list[dict[str, Any]]:
        """List staged inbound events (sender + admission state, no payloads)."""
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ChannelDenied("inbox page limit must be 1..500")
        with self._db() as db:
            subscription = db.execute(
                "SELECT owner FROM channel_subscriptions WHERE subscription_id=?",
                (subscription_id,)).fetchone()
            if subscription is None:
                raise FileNotFoundError("channel subscription not found")
            if subscription["owner"] != owner:
                raise PermissionError("subscription belongs to another owner")
            rows = db.execute("SELECT event_id,sender,work_item_id,received "
                              "FROM channel_inbound_events WHERE subscription_id=? "
                              "ORDER BY received DESC LIMIT ?",
                              (subscription_id, limit)).fetchall()
        return [{"event_id": row["event_id"], "sender": row["sender"],
                 "status": "ADMITTED" if row["work_item_id"] else "PENDING",
                 "work_item_id": row["work_item_id"],
                 "received": row["received"]} for row in rows]

    # -- outbound ------------------------------------------------------
    def stage_notification(self, *, owner: str, subscription_id: str,
                           recipient: str, payload: dict,
                           dedupe_key: str) -> dict[str, Any]:
        """Stage one outbound notification (idempotent by dedupe key).

        The protected payload is stored alongside its digest so the host
        can resolve the exact send text server-side at admission time.
        """
        from sentra_core.conversations import _encode
        if not isinstance(recipient, str) or not 1 <= len(recipient) <= 256:
            raise ChannelDenied("bounded notification recipient required")
        if not isinstance(dedupe_key, str) or not 8 <= len(dedupe_key) <= 128:
            raise ChannelDenied("bounded notification dedupe key required")
        if not isinstance(payload, dict):
            raise ChannelDenied("notification payload must be a mapping")
        digest(payload)
        with self._db() as db:
            subscription = db.execute(
                "SELECT * FROM channel_subscriptions WHERE subscription_id=?",
                (subscription_id,)).fetchone()
        if subscription is None:
            raise FileNotFoundError("channel subscription not found")
        if subscription["owner"] != owner or subscription["state"] != "ENABLED":
            raise ChannelDenied("subscription not enabled for this owner")
        payload_sha = digest(payload)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM channel_outbound WHERE dedupe_key=?",
                             (dedupe_key,)).fetchone()
            if old is not None:
                if (old["subscription_id"], old["recipient"],
                        old["payload_sha256"]) != (
                        subscription_id, recipient, payload_sha):
                    raise ChannelDenied("dedupe key bound to a different message")
                return {"dedupe_key": dedupe_key, "state": old["state"],
                        "provider_message_id": old["provider_message_id"],
                        "replayed": True}
            db.execute("INSERT INTO channel_outbound(dedupe_key,subscription_id,recipient,payload_sha256,protected_payload,provider_message_id,state,created,updated) VALUES(?,?,?,?,?,NULL,'STAGED',?,?)",
                       (dedupe_key, subscription_id, recipient, payload_sha,
                        _encode(payload), self.clock(), self.clock()))
        return {"dedupe_key": dedupe_key, "state": "STAGED", "replayed": False}

    def bind_sender(self, *, owner: str, subscription_id: str,
                    connector_id: str,
                    operator_approved: bool = False) -> dict[str, Any]:
        """Map a local subscription to a Lume connector (host action).

        Outbound ``send`` runs against the mapped connector; the mapping
        itself requires host owner approval and never carries secrets.
        """
        if operator_approved is not True:
            raise PermissionError("host owner approval required to bind sender")
        ident(subscription_id)
        ident(connector_id)
        with self._db() as db:
            subscription = db.execute(
                "SELECT * FROM channel_subscriptions WHERE subscription_id=?",
                (subscription_id,)).fetchone()
            if subscription is None:
                raise FileNotFoundError("channel subscription not found")
            if subscription["owner"] != owner:
                raise PermissionError("subscription belongs to another owner")
            db.execute("INSERT INTO channel_senders VALUES(?,?,?,?) "
                       "ON CONFLICT(subscription_id) DO UPDATE SET "
                       "connector_id=excluded.connector_id,updated=excluded.updated",
                       (subscription_id, owner, connector_id, self.clock()))
        return {"subscription_id": subscription_id, "connector_id": connector_id}

    def resolve_send(self, owner: str, dedupe_key: str) -> dict[str, Any]:
        """Resolve staged text server-side for an admitted ``channel:send``.

        Returns ``{connector_id, recipient, text}`` with text validated to
        the provider bound. The caller (host root) admits the central
        operation with ``text_sha256`` over this exact text, then drives
        Lume's ``send`` inside admission.
        """
        from sentra_core.conversations import _decode
        with self._db() as db:
            row = db.execute("SELECT * FROM channel_outbound WHERE dedupe_key=?",
                             (dedupe_key,)).fetchone()
            if row is None:
                raise FileNotFoundError("staged notification not found")
            mapping = db.execute("SELECT * FROM channel_senders WHERE subscription_id=?",
                                 (row["subscription_id"],)).fetchone()
            subscription = db.execute(
                "SELECT * FROM channel_subscriptions WHERE subscription_id=?",
                (row["subscription_id"],)).fetchone()
        if subscription is None or subscription["owner"] != owner:
            raise PermissionError("staged notification belongs to another owner")
        if subscription["state"] != "ENABLED":
            raise ChannelDenied("subscription not enabled for this owner")
        if mapping is None or mapping["owner"] != owner:
            raise ChannelDenied("subscription has no bound Lume connector; "
                                "host must bind_sender first")
        if row["protected_payload"] is None:
            raise ChannelDenied("staged notification predates payload capture; "
                                "re-stage under a new dedupe key")
        payload = _decode(row["protected_payload"])
        if digest(payload) != row["payload_sha256"]:
            raise ChannelDenied("staged notification payload changed")
        text = payload.get("text")
        if not isinstance(text, str) or not text or len(text.encode()) > 16000:
            raise ChannelDenied("staged notification carries no sendable text")
        return {"connector_id": mapping["connector_id"],
                "recipient": row["recipient"], "text": text,
                "subscription_id": row["subscription_id"],
                "dedupe_key": dedupe_key}

    async def send_staged(self, *, dedupe_key: str) -> dict[str, Any]:
        """Deliver one staged notification through the host sender.

        Records ``SENT`` on provider ACK. ``DELIVERED`` is marked only by
        :meth:`mark_delivered` after a durable receipt is observed — a
        service ACK is never presented as completion.
        """
        from sentra_runtime.effect_boundary import current_effect_context
        context=current_effect_context.get()
        if context is None or context.request.capability_id!="channel:send":
            raise ChannelDenied("send_staged requires its admitted channel send Operation")
        if self.outbound_sender is None:
            raise ChannelDenied("no channel outbound sender configured")
        with self._db() as db:
            row = db.execute("SELECT * FROM channel_outbound WHERE dedupe_key=?",
                             (dedupe_key,)).fetchone()
            subscription = db.execute(
                "SELECT channel FROM channel_subscriptions WHERE subscription_id=?",
                (row["subscription_id"],)).fetchone() if row else None
        if row is None or subscription is None:
            raise FileNotFoundError("staged notification not found")
        if row["state"] == "DELIVERED":
            return {"dedupe_key": dedupe_key, "state": "DELIVERED",
                    "provider_message_id": row["provider_message_id"],
                    "replayed": True}
        if row["state"]!="STAGED":
            raise ChannelDenied("notification already sent or uncertain; no replay")
        from sentra_core.conversations import _decode
        payload=_decode(row["protected_payload"])
        if digest(payload)!=row["payload_sha256"]:
            raise ChannelDenied("notification payload changed")
        with self._db() as db:
            changed=db.execute("UPDATE channel_outbound SET state='IN_FLIGHT',updated=? WHERE dedupe_key=? AND state='STAGED'",(self.clock(),dedupe_key)).rowcount
        if changed!=1:
            raise ChannelDenied("notification claimed concurrently")
        context.checkpoint()
        resolved=self.resolve_send(context.receipt.owner,dedupe_key)
        if context.request.arguments!={"connector_id":resolved["connector_id"],"recipient":row["recipient"],"text_sha256":digest(resolved["text"])}:
            raise ChannelDenied("notification does not match the exact admitted send intent")
        context.checkpoint()
        ack = self.outbound_sender(context.request, subscription["channel"], row["recipient"], payload)
        if hasattr(ack, "__await__"):
            ack = await ack
        if not isinstance(ack, dict) or not ack.get("provider_message_id"):
            raise ChannelDenied("channel sender returned no provider ACK")
        with self._db() as db:
            db.execute("UPDATE channel_outbound SET provider_message_id=?,"
                       "state='SENT',updated=? WHERE dedupe_key=? "
                       "AND state='IN_FLIGHT'",
                       (str(ack["provider_message_id"]), self.clock(), dedupe_key))
        return {"dedupe_key": dedupe_key, "state": "SENT",
                "provider_message_id": str(ack["provider_message_id"]),
                "delivered": False,
                "note": "provider ACK only; DELIVERED after receipt"}

    def note_provider_ack(self, *, owner, dedupe_key, operation_id):
        if self.channel_service is None or self.channel_service.owner!=owner:
            raise ChannelDenied("configured ChannelService required for ACK projection")
        resolved=self.resolve_send(owner,dedupe_key)
        with self._db() as db:
            subscription=db.execute("SELECT project_id FROM channel_subscriptions WHERE subscription_id=?",(resolved["subscription_id"],)).fetchone()
            previous=db.execute("SELECT operation_id FROM channel_outbound WHERE dedupe_key=?",(dedupe_key,)).fetchone()
        if previous["operation_id"] not in (None,operation_id):
            raise ChannelDenied("notification already bound to another operation")
        receipt=self.channel_service.owner_receipt(connector_id=resolved["connector_id"],project_id=subscription["project_id"],operation_id=operation_id)
        provider=receipt.get("provider_receipt")
        if not provider:
            return {"state":"UNCERTAIN","automatic_retry":False}
        with self._db() as db:
            db.execute("UPDATE channel_outbound SET provider_message_id=?,state='SENT',operation_id=?,updated=? WHERE dedupe_key=? AND state!='DELIVERED'",
                (provider["external_message_id"],operation_id,self.clock(),dedupe_key))
        return {"state":"SENT","recipient_receipt":receipt.get("recipient_receipt"),"provider_ack_only":True}

    def mark_delivered(self, *, dedupe_key: str,
                       receipt_id: str) -> dict[str, Any]:
        """Mark DELIVERED exclusively on observed durable receipt evidence."""
        if not isinstance(receipt_id, str) or not receipt_id:
            raise ChannelDenied("durable receipt identity required")
        if self.channel_service is None:
            raise ChannelDenied("recipient receipt observer unavailable")
        with self._db() as db:
            message=db.execute("SELECT * FROM channel_outbound WHERE dedupe_key=?",(dedupe_key,)).fetchone()
            subscription=db.execute("SELECT * FROM channel_subscriptions WHERE subscription_id=?",(message["subscription_id"],)).fetchone() if message else None
            mapping=db.execute("SELECT * FROM channel_senders WHERE subscription_id=?",(message["subscription_id"],)).fetchone() if message else None
        if not message or not subscription or not mapping or message["operation_id"]!=receipt_id:
            raise ChannelDenied("recipient receipt must identify the exact send operation")
        receipt=self.channel_service.owner_receipt(connector_id=mapping["connector_id"],project_id=subscription["project_id"],operation_id=receipt_id)
        recipient=receipt.get("recipient_receipt") or {}
        if recipient.get("status") not in {"delivered","read","recipient_replied"}:
            raise ChannelDenied("provider ACK is insufficient for recipient delivery")
        with self._db() as db:
            updated = db.execute(
                "UPDATE channel_outbound SET state='DELIVERED',updated=? "
                "WHERE dedupe_key=? AND state='SENT'",
                (self.clock(), dedupe_key)).rowcount
            if updated != 1:
                raise ChannelDenied(
                    "notification is not in SENT state; delivery requires "
                    "provider ACK first and a durable receipt")
            row = db.execute("SELECT * FROM channel_outbound WHERE dedupe_key=?",
                             (dedupe_key,)).fetchone()
        return {"dedupe_key": dedupe_key, "state": "DELIVERED",
                "provider_message_id": row["provider_message_id"],
                "receipt_id": receipt_id}
