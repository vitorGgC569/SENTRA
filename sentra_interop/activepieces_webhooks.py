"""Authenticated external AP webhook ingress; admission is an explicit next step."""
import hashlib
import hmac
import time
from sentra_core.conversations import _encode, _decode
from sentra_runtime.effect_boundary import current_effect_context
from .a2a_provider import decode, approved_url
from .workflow_contracts import digest, ident
from .workflow_storage import projection_db


class ActivepiecesWebhookIngress:
    def __init__(self, control, *, owner, schedule_bridge, secret_resolver, clock=time.time):
        if schedule_bridge.control is not control or not callable(secret_resolver):
            raise ValueError("same configured control and vault resolver required")
        self.control, self.owner, self.bridge, self.secret, self.clock = control, owner, schedule_bridge, secret_resolver, clock
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pulso_ap_webhook_profiles(
                owner TEXT NOT NULL,subscription_id TEXT NOT NULL,project_id TEXT NOT NULL,
                configuration TEXT NOT NULL,enabled INTEGER NOT NULL,
                PRIMARY KEY(owner,subscription_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS pulso_ap_webhook_inbox(
                owner TEXT NOT NULL,subscription_id TEXT NOT NULL,event_id TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,events_sha256 TEXT NOT NULL,protected_events TEXT NOT NULL,
                state TEXT NOT NULL,operation_id TEXT,received REAL NOT NULL,
                PRIMARY KEY(owner,subscription_id,event_id))""")

    def db(self):
        return projection_db(None, control=self.control)

    def configure(self, *, subscription_id, project_id, public_url, signing_secret_ref,
                  signature_header="x-sentra-signature", timestamp_header="x-sentra-timestamp",
                  event_id_header="x-sentra-event-id", signature_prefix="sha256=", operator_approved=False):
        if operator_approved is not True:
            raise PermissionError("host approval required for webhook profile")
        ident(subscription_id)
        approved_url(public_url)
        if not public_url.startswith("https://") or not signing_secret_ref:
            raise ValueError("HTTPS ingress and vault signature reference required")
        for header in (signature_header, timestamp_header, event_id_header):
            if not isinstance(header, str) or not header or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in header):
                raise ValueError("lowercase webhook header names required")
        config = dict(public_url=public_url, signing_secret_ref=signing_secret_ref,
            signature_header=signature_header, timestamp_header=timestamp_header,
            event_id_header=event_id_header, signature_prefix=signature_prefix)
        with self.db() as db:
            old = db.execute("SELECT project_id,configuration FROM pulso_ap_webhook_profiles WHERE owner=? AND subscription_id=?",
                (self.owner, subscription_id)).fetchone()
            if old and (old["project_id"] != project_id or _decode(old["configuration"]) != config):
                raise ValueError("webhook identity immutable; disable and configure a new subscription")
            db.execute("INSERT OR IGNORE INTO pulso_ap_webhook_profiles VALUES(?,?,?,?,1)",
                (self.owner, subscription_id, project_id, _encode(config)))
        return {"subscription_id": subscription_id, "project_id": project_id, "public_url": public_url, "ingress_only": True}

    def receive(self, *, subscription_id, raw_body, headers):
        if not isinstance(raw_body, bytes) or not 0 < len(raw_body) <= 1024 * 1024:
            raise ValueError("webhook raw body exceeds 1 MiB")
        with self.db() as db:
            profile = db.execute("SELECT * FROM pulso_ap_webhook_profiles WHERE owner=? AND subscription_id=? AND enabled=1",
                (self.owner, subscription_id)).fetchone()
        if profile is None:
            raise PermissionError("webhook profile unavailable")
        config = _decode(profile["configuration"])
        values = {key.lower(): value for key, value in headers.items()}
        timestamp = values.get(config["timestamp_header"], "")
        if not timestamp.isdigit() or abs(self.clock() - int(timestamp)) > 300:
            raise PermissionError("webhook timestamp expired")
        event_id = values.get(config["event_id_header"], "")
        ident(event_id)
        secret = self.secret(config["signing_secret_ref"])
        if not isinstance(secret, str) or not secret:
            raise PermissionError("webhook credential unavailable")
        expected = config["signature_prefix"] + hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
        signature = values.get(config["signature_header"], "")
        if not hmac.compare_digest(expected, signature):
            raise PermissionError("webhook signature mismatch")
        body = decode(raw_body)
        events = body.get("events") if isinstance(body, dict) else None
        if not isinstance(events, list) or not 1 <= len(events) <= 100 or any(not isinstance(event, dict) for event in events):
            raise ValueError("bounded webhook event array required")
        raw_sha, events_sha = hashlib.sha256(raw_body).hexdigest(), digest(events)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT raw_sha256,state FROM pulso_ap_webhook_inbox WHERE owner=? AND subscription_id=? AND event_id=?",
                (self.owner, subscription_id, event_id)).fetchone()
            if old and old["raw_sha256"] != raw_sha:
                raise ValueError("webhook event identity conflict")
            db.execute("INSERT OR IGNORE INTO pulso_ap_webhook_inbox VALUES(?,?,?,?,?,?,'PENDING',NULL,?)",
                (self.owner, subscription_id, event_id, raw_sha, events_sha, _encode(events), self.clock()))
        return {"subscription_id": subscription_id, "event_id": event_id, "project_id": profile["project_id"],
            "status": old["state"] if old else "PENDING", "duplicate": old is not None, "effects_started": False}

    def process_admitted(self, *, subscription_id, event_id):
        context = current_effect_context.get()
        if context is None or context.receipt.owner != self.owner:
            raise PermissionError("webhook admission requires the central effect context")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM pulso_ap_webhook_inbox WHERE owner=? AND subscription_id=? AND event_id=?",
                (self.owner, subscription_id, event_id)).fetchone()
            profile = db.execute("SELECT * FROM pulso_ap_webhook_profiles WHERE owner=? AND subscription_id=? AND enabled=1",
                (self.owner, subscription_id)).fetchone()
            if row is None or profile is None or row["state"] != "PENDING":
                raise PermissionError("webhook already processed or uncertain; lookup existing tasks")
            if context.request.capability_id != "activepieces:trigger_ingest" or context.request.arguments.get("subscription_id") != subscription_id or context.request.arguments.get("events_sha256") != row["events_sha256"]:
                raise PermissionError("webhook admission intent mismatch")
            item = self.control.work_item_info(context.request.work_item_id, self.owner)
            if item.get("metadata", {}).get("workspace_id") != profile["project_id"]:
                raise PermissionError("webhook WorkItem outside configured project")
            db.execute("UPDATE pulso_ap_webhook_inbox SET state='CLAIMED',operation_id=? WHERE owner=? AND subscription_id=? AND event_id=?",
                (context.request.operation_id, self.owner, subscription_id, event_id))
        context.checkpoint()
        result = self.bridge.webhook_handler(subscription_id=subscription_id, events=_decode(row["protected_events"]))
        if any(entry.get("status") == "UNCERTAIN" for entry in result):
            from sentra_runtime.contracts import OperationResult
            return OperationResult(context.request.operation_id, "UNCERTAIN",
                evidence={"event_id": event_id, "tasks": result}, error="TRIGGER_ADMISSION_UNCERTAIN")
        with self.db() as db:
            db.execute("UPDATE pulso_ap_webhook_inbox SET state='ADMITTED' WHERE owner=? AND subscription_id=? AND event_id=?",
                (self.owner, subscription_id, event_id))
        return {"event_id": event_id, "tasks": result, "operation_id": context.request.operation_id}

    def disable(self, *, subscription_id, operator_approved=False):
        if operator_approved is not True:
            raise PermissionError("host approval required")
        with self.db() as db:
            db.execute("UPDATE pulso_ap_webhook_profiles SET enabled=0 WHERE owner=? AND subscription_id=?", (self.owner, subscription_id))
        return {"subscription_id": subscription_id, "ingress_disabled": True,
                "external_hook_cleanup": "separate admitted onDisable receipt"}

    def revoke(self, *, subscription_id, operator_approved=False):
        result = self.disable(subscription_id=subscription_id, operator_approved=operator_approved)
        with self.db() as db:
            row = db.execute("SELECT configuration FROM pulso_ap_webhook_profiles WHERE owner=? AND subscription_id=?",
                (self.owner, subscription_id)).fetchone()
            if row:
                config = _decode(row["configuration"])
                config["signing_secret_ref"] = None
                db.execute("UPDATE pulso_ap_webhook_profiles SET configuration=? WHERE owner=? AND subscription_id=?",
                    (_encode(config), self.owner, subscription_id))
        return {**result, "credential_reference_revoked": True}
