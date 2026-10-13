"""Operator-reviewed Host account/profile schema and live snapshot attestation.

Enrollment is a server-only composition API, never a browser/model operation.
Catalog caches cannot attest a physical turn. Every proof reads the authenticated
Host again and checks reviewed collector/host bytes, profile, account, document,
authentication revision, approval and physical model selection. No new grants.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from contextlib import closing

from sentra_core.conversations import _encode, _decode
from .browser_host_identity import read_host_identity, read_host_approval, read_host_account_catalog


def _fingerprint(snapshot):
    values = [snapshot.get(key) for key in ("profile", "partition", "account_id", "user_id")]
    if any(not isinstance(value, str) or not 1 <= len(value) <= 512 for value in values):
        raise PermissionError("committed account/profile identity is incomplete")
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


class HostAccountAttestor:
    def __init__(self, control, *, clock=time.time):
        self.control, self.store, self.clock = control, control.store, clock
        with closing(self.store.connect("provider_content")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS host_account_profiles("
                "owner TEXT NOT NULL,profile_key TEXT NOT NULL,revision INTEGER NOT NULL,"
                "enabled INTEGER NOT NULL,protected_profile TEXT NOT NULL,updated REAL NOT NULL,"
                "PRIMARY KEY(owner,profile_key))")

    def enroll(self, *, owner, descriptor, tab, trace_id, browser_principal,
               reviewed_host_sha256, reviewed_collector_sha256, expected_revision=0,
               operator_approved=False):
        if operator_approved is not True:
            raise PermissionError("operator review of host collector schema is required")
        for value in (reviewed_host_sha256, reviewed_collector_sha256):
            if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
                raise ValueError("reviewed Host/collector source pins required")
        snapshot = read_host_identity(descriptor, tab, trace_id=trace_id)
        if (snapshot.get("host_source_sha256") != reviewed_host_sha256
                or snapshot.get("collector_sha256") != reviewed_collector_sha256):
            raise PermissionError("live Host/collector differs from reviewed sources")
        fingerprint = _fingerprint(snapshot)
        profile_key = hashlib.sha256(json.dumps([snapshot["profile"], snapshot["partition"]],
                                               separators=(",", ":")).encode()).hexdigest()
        record = {"fingerprint": fingerprint, "browser_principal": browser_principal,
            "profile": snapshot["profile"], "partition": snapshot["partition"],
            "host_sha256": reviewed_host_sha256, "collector_sha256": reviewed_collector_sha256,
            "collector_id": "electron-" + profile_key[:32]}
        with closing(self.store.connect("provider_content")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT revision FROM host_account_profiles WHERE owner=? AND profile_key=?",
                             (owner, profile_key)).fetchone()
            if (old["revision"] if old else 0) != expected_revision:
                raise ValueError("host account profile revision changed")
            db.execute("INSERT INTO host_account_profiles VALUES(?,?,?,1,?,?) "
                "ON CONFLICT(owner,profile_key) DO UPDATE SET revision=excluded.revision,enabled=1,"
                "protected_profile=excluded.protected_profile,updated=excluded.updated",
                (owner, profile_key, expected_revision + 1, _encode(record), self.clock()))
        return {"profile_key": profile_key, "revision": expected_revision + 1,
                "account_fingerprint": fingerprint, "grants_created": False}

    def revoke(self, owner, profile_key, *, expected_revision, operator_approved=False):
        if operator_approved is not True:
            raise PermissionError("operator approval required to revoke a Host profile")
        with closing(self.store.connect("provider_content")) as db, db:
            changed = db.execute("UPDATE host_account_profiles SET enabled=0,revision=revision+1,updated=? "
                "WHERE owner=? AND profile_key=? AND revision=?",
                (self.clock(), owner, profile_key, expected_revision)).rowcount
            if changed != 1:
                raise ValueError("Host profile revision changed")
        return {"enabled": False, "revision": expected_revision + 1, "grants_created": False}

    def _profile(self, owner, snapshot):
        profile_key = hashlib.sha256(json.dumps([snapshot.get("profile"), snapshot.get("partition")],
                                               separators=(",", ":")).encode()).hexdigest()
        with closing(self.store.connect("provider_content")) as db:
            row = db.execute("SELECT * FROM host_account_profiles WHERE owner=? AND profile_key=? AND enabled=1",
                             (owner, profile_key)).fetchone()
        if row is None:
            raise PermissionError("Host account/profile schema is not operator-enrolled")
        profile = _decode(row["protected_profile"])
        if (profile["fingerprint"] != _fingerprint(snapshot)
                or profile["host_sha256"] != snapshot.get("host_source_sha256")
                or profile["collector_sha256"] != snapshot.get("collector_sha256")):
            raise PermissionError("Host source, collector, or account/profile changed")
        return profile

    def __call__(self, cap, descriptor, tab):
        identity = read_host_identity(descriptor, tab, trace_id=cap.trace_id)
        profile = self._profile(cap.owner, identity)
        approval = read_host_approval(descriptor, tab, trace_id=cap.trace_id)
        if approval["state"] not in {"idle", "pending"}:
            raise PermissionError("Host approval observation is unknown")
        catalog = read_host_account_catalog(descriptor, tab, trace_id=cap.trace_id, provider="chatgpt",
            account_verifier=lambda snapshot: self._profile(cap.owner, snapshot) == profile)
        if catalog["authentication_revision"] != identity.get("authentication_revision"):
            raise PermissionError("Host authentication revision changed during attestation")
        with closing(self.store.connect("session_checkpoint")) as db:
            row = db.execute("SELECT r.request_id,r.protected_payload FROM web_response_requests r "
                "JOIN gateway_bound_web_turns b ON b.owner=r.owner AND b.request_hash=r.request_identity_sha256 "
                "WHERE b.owner=? AND b.token_hash=? AND b.run_id=?",
                (cap.owner, cap.token_hash, cap.run_id)).fetchone()
        if row is None:
            raise PermissionError("Host turn has no protected original request")
        from native_bridge.job_store import JobStore
        responses = JobStore._unseal(row["protected_payload"], row["request_id"], "responses_request")["responses"]
        requested_model, requested_effort = responses.get("model"), (responses.get("reasoning") or {}).get("effort")
        if catalog["model"] not in catalog["models"] or (catalog["effort"] is not None and catalog["effort"] not in catalog["efforts"]):
            raise PermissionError("selected physical model/effort not observed in current catalog")
        if (not isinstance(requested_model, str) or requested_model.removeprefix("sentra/chatgpt-web/").removeprefix("chatgpt-web/") != catalog["model"]
                or requested_effort != catalog["effort"] or catalog["selection_verified"] is not True):
            raise PermissionError("physical selection differs from the protected original request")
        collector, worker = profile["collector_id"], "electron:" + str(tab["tabId"])
        run = self.control.durable.run_status(cap.run_id, cap.owner, include_details=False)
        with closing(self.store.connect("chat_access")) as db:
            enrolled = db.execute("SELECT principal,source_sha256,workspace,enabled,kind FROM browser_collectors WHERE extension_id=?",
                                 (collector,)).fetchone()
        if (enrolled is None or enrolled["kind"] != "electron" or not enrolled["enabled"]
                or enrolled["principal"] != profile["browser_principal"] or enrolled["workspace"] != run["workspace"]
                or enrolled["source_sha256"] != profile["host_sha256"]):
            raise PermissionError("Host collector requires explicit central enrollment for this workspace")
        return {"account_verified": True, "collector_kind": "electron", "extension_id": collector,
            "source_sha256": profile["host_sha256"], "worker": worker,
            "browser_principal": profile["browser_principal"], "document_id": identity["document_id"],
            "identity_epoch": identity["identity_epoch"], "authentication_revision": catalog["authentication_revision"],
            "account_fingerprint": profile["fingerprint"], "approval_state": approval["state"],
            "selection_verified": True, "requested_model": requested_model, "requested_effort": requested_effort,
            "model": catalog["model"], "effort": catalog["effort"], "models": catalog["models"], "efforts": catalog["efforts"],
            "grants_created": False}
