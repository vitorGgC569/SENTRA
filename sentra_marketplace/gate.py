"""Admission for optional connectors, skills, plugins and marketplace packages.

A real effect is bound to a Run, a WorkItem, an Operation and a host Grant.
This module never calls ``grant``. A plugin, skill or connector cannot be
the principal of its own capability. External content is fenced as data.
An UNCERTAIN receipt is never resent.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from sentra_runtime.contracts import OperationRequest

from .absence import absence_stamp
from .content_fence import fence_external_content, superior_digest
from .packages import claims_self_grant, verify_pin
from .policy import AllowPolicy, DenyOnlyPolicy

_ID = re.compile(r"^[A-Za-z0-9_:.@/-]{1,256}\Z")
_KINDS = {"connector", "skill", "plugin", "marketplace_package", "visual_model"}
_PACKAGE_KINDS = {"connector", "plugin", "marketplace_package", "visual_model"}
_SELF_KINDS = {"connector", "plugin", "marketplace_package", "visual_model"}
_GRANT_RESULT_KEYS = {"grant", "grants", "grant_id", "grants_created", "self_grant", "issue_grant"}


class EffectUncertain(RuntimeError):
    """The effect may have started. The receipt must not be replayed."""


@dataclass(frozen=True)
class HostBinding:
    """Host-supplied authority. The optional subject does not build this."""

    owner: str
    run_id: str
    work_item_id: str
    operation: OperationRequest
    principal_type: str
    superior_instruction: str

    def validate(self) -> None:
        if type(self.owner) is not str or not _ID.fullmatch(self.owner):
            raise ValueError("owner required")
        if type(self.run_id) is not str or not _ID.fullmatch(self.run_id):
            raise ValueError("run_id required")
        if type(self.work_item_id) is not str or not _ID.fullmatch(self.work_item_id):
            raise ValueError("work_item_id required")
        if not isinstance(self.operation, OperationRequest):
            raise ValueError("host OperationRequest required")
        if self.operation.work_item_id != self.work_item_id:
            raise ValueError("operation is not bound to this WorkItem")
        if type(self.principal_type) is not str or self.principal_type not in {"user", "agent"}:
            raise ValueError("optional capability principal must be user or agent")
        if not _ID.fullmatch(self.operation.operation_id):
            raise ValueError("operation_id required")
        if not _ID.fullmatch(self.operation.idempotency_key):
            raise ValueError("idempotency_key required")
        if not _ID.fullmatch(self.operation.principal_id):
            raise ValueError("principal_id required")
        superior_digest(self.superior_instruction)


@dataclass(frozen=True)
class PackagePin:
    package_id: str
    kind: str
    path: str
    sha256: str


@dataclass(frozen=True)
class Subject:
    kind: str
    subject_id: str
    capability: str
    manifest: Mapping[str, Any] = field(default_factory=dict)
    content: str = ""

    def validate(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError("unknown optional subject")
        if type(self.subject_id) is not str or not _ID.fullmatch(self.subject_id):
            raise ValueError("subject_id required")
        if type(self.capability) is not str or not _ID.fullmatch(self.capability):
            raise ValueError("capability required")
        if "*" in self.capability or "?" in self.capability:
            raise ValueError("capability wildcards are rejected")
        if not isinstance(self.manifest, Mapping):
            raise ValueError("manifest must be an object")
        if type(self.content) is not str:
            raise ValueError("external content must be text")


class OptionalCapabilityGate:
    """Fail-closed opt-in. Does not mint Grants and does not touch the network."""

    def __init__(self, state_root: Path | str):
        self.root = Path(state_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "optional_receipts.sqlite3"
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS optional_receipts(
                    owner TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    body_json TEXT NOT NULL,
                    created REAL NOT NULL,
                    updated REAL NOT NULL,
                    PRIMARY KEY(owner, operation_id),
                    UNIQUE(owner, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS optional_opt_in(
                    owner TEXT NOT NULL,
                    package_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    grant_id TEXT,
                    created REAL NOT NULL,
                    PRIMARY KEY(owner, package_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def grant(self, *args, **kwargs):
        raise PermissionError("optional surface cannot mint a Grant")

    def opted_in(self, owner: str) -> set[str]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT package_id FROM optional_opt_in WHERE owner=?", (owner,)
            ).fetchall()
        return {row["package_id"] for row in rows}

    def record_opt_in(self, owner: str, package_id: str, operation_id: str, grant_id: str | None) -> None:
        if not _ID.fullmatch(owner) or not _ID.fullmatch(package_id) or not _ID.fullmatch(operation_id):
            raise ValueError("opt-in identity required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO optional_opt_in VALUES(?,?,?,?,?) "
                "ON CONFLICT(owner, package_id) DO NOTHING",
                (owner, package_id, operation_id, grant_id, time.time()),
            )

    def invoke(
        self,
        *,
        authorization,
        binding: HostBinding,
        policy,
        subject: Subject,
        package: PackagePin | None = None,
        effect: Callable[[Mapping[str, Any]], Any] | None = None,
        unavailable_reason: str | None = None,
        local_process: bool = False,
        package_path: str | None = None,
    ) -> dict[str, Any]:
        binding.validate()
        subject.validate()
        if not isinstance(policy, (AllowPolicy, DenyOnlyPolicy)):
            raise ValueError("allow or deny-only policy required")
        if subject.kind in _PACKAGE_KINDS and package is not None and package.kind != subject.kind:
            raise ValueError("package kind does not match the subject")
        replay = self._lookup(binding)
        if replay is not None:
            return replay
        try:
            fenced = fence_external_content(subject.content)
        except ValueError as exc:
            if str(exc) != "CONTENT_UNBOUNDED":
                raise
            return self._commit(binding, self._spec(
                binding, subject, None, outcome="REFUSED", reason="CONTENT_UNBOUNDED",
                capability_closed=False, effect="not_called",
                fenced={"sha256": "", "override_attempt": False, "bytes": 0},
            ))
        prepared = self._decide(
            authorization, binding, policy, subject, fenced, package, unavailable_reason, effect,
        )
        if isinstance(prepared, dict):
            return self._commit(binding, prepared)
        return self._run_effect(
            authorization, binding, subject, fenced, package, effect, prepared,
            local_process=bool(local_process) and subject.kind == "connector",
            package_path=package_path,
        )

    def _lookup(self, binding: HostBinding) -> dict[str, Any] | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM optional_receipts WHERE owner=? AND (operation_id=? OR idempotency_key=?)",
                (binding.owner, binding.operation.operation_id, binding.operation.idempotency_key),
            ).fetchone()
            if row is None:
                return None
            return self._replay(db, row, binding)

    def _replay(self, db, row, binding: HostBinding) -> dict[str, Any]:
        if (row["operation_id"] != binding.operation.operation_id
                or row["idempotency_key"] != binding.operation.idempotency_key):
            body = json.loads(row["body_json"])
            body["conflict"] = True
            body["resent"] = False
            body["automatic_retry"] = False
            return body
        body = json.loads(row["body_json"])
        if body.get("outcome") == "PENDING":
            body = self._rewrite(
                db, binding, body, outcome="UNCERTAIN",
                reason="PENDING_EFFECT_NOT_RESENT", effect="uncertain",
            )
        body["resent"] = False
        body["conflict"] = False
        body["automatic_retry"] = False
        body["grants_created"] = False
        return body

    def _decide(self, authorization, binding, policy, subject, fenced, package, unavailable_reason, effect):
        opened, reason, closed = policy.decide(subject.capability)
        if not opened:
            return self._spec(
                binding, subject, None, outcome="REFUSED", reason=reason,
                capability_closed=closed, effect="not_called", fenced=fenced,
            )
        if subject.kind in _SELF_KINDS and binding.operation.principal_id == subject.subject_id:
            return self._spec(
                binding, subject, None, outcome="REFUSED", reason="PLUGIN_SELF_GRANT",
                capability_closed=False, effect="not_called", fenced=fenced,
            )
        if claims_self_grant(dict(subject.manifest)):
            return self._spec(
                binding, subject, None, outcome="REFUSED", reason="PLUGIN_SELF_GRANT",
                capability_closed=False, effect="not_called", fenced=fenced,
            )
        if binding.operation.capability_id != subject.capability:
            return self._spec(
                binding, subject, None, outcome="REFUSED", reason="OPERATION_CAPABILITY_MISMATCH",
                capability_closed=False, effect="not_called", fenced=fenced,
            )
        try:
            decision = authorization.authorize(
                binding.owner,
                principal_type=binding.principal_type,
                principal_id=binding.operation.principal_id,
                capability=subject.capability,
                scope_type="work_item",
                scope_id=binding.work_item_id,
                local_owner=False,
            )
        except Exception as exc:
            return self._spec(
                binding, subject, None, outcome="FAILED",
                reason=("AUTHORIZATION_" + type(exc).__name__)[:200],
                capability_closed=False, effect="not_called", fenced=fenced,
            )
        if not isinstance(decision, dict) or not decision.get("allowed") or decision.get("source") != "grant" or not decision.get("grant_id"):
            reason = "GRANT_REQUIRED"
            if isinstance(decision, dict) and decision.get("reason"):
                reason = str(decision["reason"])[:200]
                if decision.get("source") == "local_owner":
                    reason = "GRANT_REQUIRED"
            return self._spec(
                binding, subject, None, outcome="REFUSED", reason=reason,
                capability_closed=False, effect="not_called", fenced=fenced,
            )
        grant_id = str(decision["grant_id"])
        if subject.kind == "skill" and not subject.content.strip():
            return self._spec(
                binding, subject, grant_id, outcome="UNAVAILABLE", reason="SKILL_ABSENT",
                capability_closed=False, effect="not_called", fenced=fenced,
            )
        if subject.kind in _PACKAGE_KINDS:
            if package is None:
                absent = "MODEL_PACKAGE_ABSENT" if subject.kind == "visual_model" else "PACKAGE_ABSENT"
                return self._spec(
                    binding, subject, grant_id, outcome="UNAVAILABLE", reason=absent,
                    capability_closed=False, effect="not_called", fenced=fenced,
                )
            checked = verify_pin(package)
            if not checked.get("ok"):
                reason = str(checked.get("reason") or "PACKAGE_ABSENT")
                outcome = "REFUSED" if reason == "PLUGIN_SELF_GRANT" else "UNAVAILABLE"
                return self._spec(
                    binding, subject, grant_id, outcome=outcome, reason=reason,
                    capability_closed=False, effect="not_called", fenced=fenced,
                )
        if unavailable_reason:
            return self._spec(
                binding, subject, grant_id, outcome="UNAVAILABLE",
                reason=str(unavailable_reason)[:200],
                capability_closed=False, effect="not_called", fenced=fenced,
            )
        if effect is None and subject.kind != "skill":
            reason = "VISUAL_RUNTIME_ABSENT" if subject.kind == "visual_model" else "EXECUTOR_ABSENT"
            return self._spec(
                binding, subject, grant_id, outcome="UNAVAILABLE", reason=reason,
                capability_closed=False, effect="not_called", fenced=fenced,
            )
        return grant_id

    def _run_effect(self, authorization, binding, subject, fenced, package, effect, grant_id: str,
                    local_process: bool = False, package_path: str | None = None):
        try:
            decision = authorization.authorize(
                binding.owner,
                principal_type=binding.principal_type,
                principal_id=binding.operation.principal_id,
                capability=subject.capability,
                scope_type="work_item",
                scope_id=binding.work_item_id,
                local_owner=False,
            )
        except Exception as exc:
            return self._commit(binding, self._spec(
                binding, subject, grant_id, outcome="FAILED",
                reason=("AUTHORIZATION_" + type(exc).__name__)[:200],
                capability_closed=False, effect="not_called", fenced=fenced,
            ))
        if (not isinstance(decision, dict) or not decision.get("allowed")
                or decision.get("source") != "grant" or decision.get("grant_id") != grant_id):
            return self._commit(binding, self._spec(
                binding, subject, None, outcome="REFUSED", reason="GRANT_REQUIRED",
                capability_closed=False, effect="not_called", fenced=fenced,
            ))
        claimed = self._spec(
            binding, subject, grant_id, outcome="PENDING", reason="EFFECT_CLAIMED",
            capability_closed=False, effect="claimed", fenced=fenced,
        )
        self._commit(binding, claimed)
        context = {
            "superior_instruction": binding.superior_instruction,
            "content": fenced,
            "subject_id": subject.subject_id,
            "subject_kind": subject.kind,
            "capability": subject.capability,
            "operation_id": binding.operation.operation_id,
            "run_id": binding.run_id,
            "work_item_id": binding.work_item_id,
            "package_sha256": None if package is None else package.sha256,
            "grant_id": grant_id,
            "network": False,
            "package_path": package_path,
        }
        if subject.kind == "skill" and effect is None:
            finished = self._spec(
                binding, subject, grant_id, outcome="SUCCEEDED", reason="DISCLOSED_AS_DATA",
                capability_closed=False, effect="disclosed_as_data", fenced=fenced,
                result={"content": fenced, "executed": False, "instruction_authority": False},
            )
            return self._commit(binding, finished)
        try:
            result = effect(context)
        except EffectUncertain as exc:
            finished = self._spec(
                binding, subject, grant_id, outcome="UNCERTAIN",
                reason=str(exc)[:200] or "EFFECT_UNCERTAIN",
                capability_closed=False, effect="uncertain", fenced=fenced,
            )
            return self._commit(binding, finished)
        except Exception as exc:
            finished = self._spec(
                binding, subject, grant_id, outcome="FAILED",
                reason=f"{type(exc).__name__}: {exc}"[:200],
                capability_closed=False, effect="invoked", fenced=fenced,
                local_process=local_process, package_path=package_path,
            )
            return self._commit(binding, finished)
        ignored = isinstance(result, Mapping) and any(key in result for key in _GRANT_RESULT_KEYS)
        cleaned = _strip_grant(result) if isinstance(result, Mapping) else {"value": result}
        finished = self._spec(
            binding, subject, grant_id, outcome="SUCCEEDED", reason="EFFECT_SUCCEEDED",
            capability_closed=False, effect="invoked", fenced=fenced,
            result=cleaned, effect_grant_claim_ignored=ignored,
            local_process=local_process, package_path=package_path,
            transport_only=context.get("transport_only") is True,
        )
        return self._commit(binding, finished)

    def _spec(self, binding, subject, grant_id, *, outcome, reason, capability_closed,
              effect, fenced, result=None, effect_grant_claim_ignored=False,
              local_process: bool = False, package_path: str | None = None,
              transport_only: bool = False) -> dict[str, Any]:
        return self._body(
            binding, subject, grant_id=grant_id, outcome=outcome, reason=reason,
            capability_closed=capability_closed, effect=effect, fenced=fenced,
            result=result, effect_grant_claim_ignored=effect_grant_claim_ignored,
            local_process=local_process, package_path=package_path,
            transport_only=transport_only,
        )

    def _body(self, binding, subject, *, grant_id, outcome, reason, capability_closed,
              effect, fenced, result=None, effect_grant_claim_ignored=False,
              local_process: bool = False, package_path: str | None = None,
              transport_only: bool = False) -> dict[str, Any]:
        superior = superior_digest(binding.superior_instruction)
        # In-process connector only. Absence, deny-only, a failed call, and a
        # test transport stay false. The transport payload is not an account.
        connector_real = bool(
            local_process and subject.kind == "connector"
            and outcome == "SUCCEEDED" and effect == "invoked"
            and not transport_only
        )
        cited_package = bool(
            package_path and local_process and subject.kind == "connector" and effect == "invoked"
        )
        return {
            "owner": binding.owner,
            "run_id": binding.run_id,
            "work_item_id": binding.work_item_id,
            "operation_id": binding.operation.operation_id,
            "idempotency_key": binding.operation.idempotency_key,
            "grant_id": grant_id,
            "capability": subject.capability,
            "subject_kind": subject.kind,
            "subject_id": subject.subject_id,
            "outcome": outcome,
            "reason": reason,
            "capability_closed": bool(capability_closed),
            "effect": effect,
            "grants_created": False,
            "network": False,
            "instruction_authority": False,
            "superior_instruction": binding.superior_instruction,
            "superior_sha256": superior,
            "content_sha256": fenced.get("sha256", ""),
            "override_attempt": bool(fenced.get("override_attempt")),
            "effect_grant_claim_ignored": bool(effect_grant_claim_ignored),
            "automatic_retry": False,
            "homologated": False,
            "resent": False,
            "conflict": False,
            "result": result,
            "connector_real": connector_real,
            "account_contacted": False,
            "package_path": package_path if cited_package else None,
            "visual_weights": False,
            "quickjs": False,
            "absence_probe": False,
            **absence_stamp(reason),
        }

    def _terminal(self, binding, subject, grant_id, **kwargs) -> dict[str, Any]:
        spec = self._spec(binding, subject, grant_id, **kwargs)
        return self._commit(binding, spec)

    def _commit(self, binding: HostBinding, body: dict[str, Any]) -> dict[str, Any]:
        stored = dict(body)
        stored["grants_created"] = False
        stored["network"] = False
        stored["automatic_retry"] = False
        stored["homologated"] = False
        stored["account_contacted"] = False
        raw = json.dumps(stored, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT outcome, body_json, idempotency_key FROM optional_receipts "
                "WHERE owner=? AND operation_id=?",
                (binding.owner, binding.operation.operation_id),
            ).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO optional_receipts VALUES(?,?,?,?,?,?,?)",
                    (binding.owner, binding.operation.operation_id,
                     binding.operation.idempotency_key, stored["outcome"], raw, now, now),
                )
            else:
                if existing["idempotency_key"] != binding.operation.idempotency_key:
                    current = json.loads(existing["body_json"])
                    current["conflict"] = True
                    current["resent"] = False
                    return current
                db.execute(
                    "UPDATE optional_receipts SET outcome=?, body_json=?, updated=? "
                    "WHERE owner=? AND operation_id=?",
                    (stored["outcome"], raw, now, binding.owner, binding.operation.operation_id),
                )
        stored["resent"] = False
        stored["conflict"] = False
        return stored

    def _rewrite(self, db, binding, body, *, outcome, reason, effect) -> dict[str, Any]:
        body = dict(body)
        body["outcome"] = outcome
        body["reason"] = reason
        body["effect"] = effect
        body["grants_created"] = False
        body["automatic_retry"] = False
        body["resent"] = False
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        db.execute(
            "UPDATE optional_receipts SET outcome=?, body_json=?, updated=? "
            "WHERE owner=? AND operation_id=?",
            (outcome, raw, time.time(), binding.owner, binding.operation.operation_id),
        )
        return body


_FORGED_SURFACE = {
    "connector_real", "network", "quickjs", "visual_weights", "absence_probe",
    "homologated", "account_contacted", "transport_only",
}


def _strip_grant(result: Mapping[str, Any]) -> dict[str, Any]:
    blocked = _GRANT_RESULT_KEYS | _FORGED_SURFACE
    return {key: value for key, value in result.items() if key not in blocked}
