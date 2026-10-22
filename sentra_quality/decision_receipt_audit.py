"""Append-only audit from a model decision to a central receipt.

The ledger observes. It does not issue Grants, acquire leases, dispatch
effects, or resend an operation. A model decision stays advisory.
``authorizes_effect`` is always false, including after a SUCCEEDED receipt.
An UNCERTAIN receipt stays non-resendable. Reconciliation may record a later
central outcome, and it does not clear that hold or start another effect.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_MODEL = re.compile(r"[A-Za-z0-9_.:/@#-]{1,128}")
_SHA = re.compile(r"[0-9a-f]{64}")
_GRANT_ID = re.compile(r"grant-[0-9a-f]{32}")
_CHOICE = re.compile(r"[a-z0-9_.:-]{1,64}")
_TOOL = re.compile(r"[a-z][a-z0-9._:-]{0,63}")
_CAPABILITY = re.compile(r"[A-Za-z0-9_.:*-]{1,64}")
_GENESIS = "0" * 64

_SOURCES = {"model", "deterministic_fallback", "quality_gate"}
_AUTH_SOURCES = {"grant", "local_owner", "policy"}
_PRINCIPALS = {"user", "agent"}
_SCOPES = {"instance", "workspace", "project", "goal", "work_item", "agent", "device"}
_OUTCOMES = {"observed", "failed", "withheld"}
_RECEIPTS = {"SUCCEEDED", "FAILED", "UNCERTAIN", "CANCELLED"}
_RECONCILED = {"SUCCEEDED", "FAILED", "CANCELLED"}
_REVIEWS = {"noted", "rejected"}

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ignore_previous", re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I)),
    ("ignore_previous_pt", re.compile(
        r"ignor[ea]\s+as\s+instru[cç][oõ]es\s+anteriores", re.I)),
    ("you_are_now", re.compile(r"you\s+are\s+now", re.I)),
    ("voce_agora", re.compile(r"voc[eê]\s+agora\s+[eé]", re.I)),
    ("grant_yourself", re.compile(r"grant\s+yourself", re.I)),
    ("issue_grant", re.compile(r"issue\s+a\s+grant|emita\s+um\s+grant|conceda\s+um\s+grant", re.I)),
    ("resend_operation", re.compile(r"resend\s+the\s+operation|reenvie\s+a\s+opera[cç][aã]o", re.I)),
    ("retry_uncertain", re.compile(r"retry\s+uncertain|reenvie\s+o\s+uncertain", re.I)),
    ("override_grant", re.compile(r"override\s+(the\s+)?grant", re.I)),
    ("system_tag", re.compile(r"<\s*system\s*>|<\|im_start\|>|\[INST\]", re.I)),
    ("embedded_grant", re.compile(r'"effect"\s*:\s*"allow"', re.I)),
)


class AuditRefusal(PermissionError):
    """Fail-closed audit refusal. This is not an authorization decision."""


class AuditConflict(AuditRefusal):
    """The same stage was already sealed with a different body."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ident(label: str, value: Any, *, minimum: int = 1) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value) or len(value) < minimum:
        raise ValueError(f"invalid {label}")
    return value


def _sha(label: str, value: Any) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def classify_untrusted(text: str) -> dict[str, Any]:
    """Classify untrusted text. The text is not an instruction and is not returned."""
    if not isinstance(text, str):
        raise ValueError("untrusted content must be text")
    if len(text) > 200_000:
        raise ValueError("untrusted content exceeds bound")
    rules = [name for name, pattern in _RULES if pattern.search(text)]
    return {
        "untrusted": True,
        "injection": bool(rules),
        "rules": rules,
        "digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


@dataclass(frozen=True, slots=True)
class DecisionObservation:
    decision_id: str
    owner: str
    dot_id: str
    workspace_id: str
    run_id: str
    work_item_id: str
    model: str
    choice: str
    confidence: float
    prompt_sha256: str
    source: str

    def __post_init__(self) -> None:
        _ident("decision_id", self.decision_id, minimum=4)
        _ident("owner", self.owner, minimum=2)
        _ident("dot_id", self.dot_id, minimum=2)
        _ident("workspace_id", self.workspace_id, minimum=2)
        _ident("run_id", self.run_id, minimum=4)
        _ident("work_item_id", self.work_item_id, minimum=4)
        if not isinstance(self.model, str) or not _MODEL.fullmatch(self.model):
            raise ValueError("invalid model")
        if not isinstance(self.choice, str) or not _CHOICE.fullmatch(self.choice):
            raise ValueError("invalid choice")
        if self.source not in _SOURCES:
            raise ValueError("invalid decision source")
        _sha("prompt_sha256", self.prompt_sha256)
        confidence = self.confidence
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            raise ValueError("confidence must be in [0, 1]")
        object.__setattr__(self, "confidence", float(confidence))


@dataclass(frozen=True, slots=True)
class AuthorizationObservation:
    owner: str
    principal_type: str
    principal_id: str
    capability: str
    scope_type: str
    allowed: bool
    source: str
    reason: str
    scope_id: str | None = None
    grant_id: str | None = None

    def __post_init__(self) -> None:
        _ident("owner", self.owner, minimum=2)
        if self.principal_type not in _PRINCIPALS:
            raise ValueError("invalid principal_type")
        _ident("principal_id", self.principal_id, minimum=2)
        if not isinstance(self.capability, str) or not _CAPABILITY.fullmatch(self.capability):
            raise ValueError("invalid capability")
        if self.scope_type not in _SCOPES:
            raise ValueError("invalid scope_type")
        if self.scope_type == "instance":
            if self.scope_id is not None:
                raise ValueError("instance scope has no scope_id")
        else:
            _ident("scope_id", self.scope_id, minimum=2)
        if type(self.allowed) is not bool:
            raise ValueError("allowed must be a boolean")
        if self.source not in _AUTH_SOURCES:
            raise ValueError("invalid authorization source")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("authorization reason required")
        if self.grant_id is not None and not _GRANT_ID.fullmatch(self.grant_id):
            raise ValueError("invalid grant_id")


@dataclass(frozen=True, slots=True)
class ExecutionObservation:
    operation_id: str
    run_id: str
    work_item_id: str
    lease_id: str
    fence_token: str
    effect_started: bool
    fencing_token: int | None = None

    def __post_init__(self) -> None:
        _ident("operation_id", self.operation_id, minimum=4)
        _ident("run_id", self.run_id, minimum=4)
        _ident("work_item_id", self.work_item_id, minimum=4)
        _ident("lease_id", self.lease_id, minimum=8)
        _ident("fence_token", self.fence_token, minimum=8)
        if type(self.effect_started) is not bool:
            raise ValueError("effect_started must be a boolean")
        if self.fencing_token is not None and (
            isinstance(self.fencing_token, bool)
            or type(self.fencing_token) is not int
            or self.fencing_token <= 0
        ):
            raise ValueError("fencing_token must be a positive integer")


@dataclass(frozen=True, slots=True)
class ResultObservation:
    outcome: str
    evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.outcome not in _OUTCOMES:
            raise ValueError("invalid result outcome")
        if self.evidence_sha256 is not None:
            _sha("evidence_sha256", self.evidence_sha256)


@dataclass(frozen=True, slots=True)
class ReceiptObservation:
    receipt_id: str
    operation_id: str
    run_id: str
    work_item_id: str
    intent_sha256: str
    state: str
    evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        _ident("receipt_id", self.receipt_id, minimum=4)
        _ident("operation_id", self.operation_id, minimum=4)
        _ident("run_id", self.run_id, minimum=4)
        _ident("work_item_id", self.work_item_id, minimum=4)
        _sha("intent_sha256", self.intent_sha256)
        if self.state not in _RECEIPTS:
            raise ValueError("invalid receipt state")
        if self.evidence_sha256 is not None:
            _sha("evidence_sha256", self.evidence_sha256)


@dataclass(frozen=True, slots=True)
class ReconciliationObservation:
    operation_id: str
    intent_sha256: str
    state: str
    resend: bool

    def __post_init__(self) -> None:
        _ident("operation_id", self.operation_id, minimum=4)
        _sha("intent_sha256", self.intent_sha256)
        if self.state not in _RECONCILED:
            raise ValueError("invalid reconciliation state")
        if type(self.resend) is not bool:
            raise ValueError("resend must be a boolean")


@dataclass(frozen=True, slots=True)
class ReviewObservation:
    reviewer_id: str
    verdict: str
    note_sha256: str

    def __post_init__(self) -> None:
        _ident("reviewer_id", self.reviewer_id, minimum=2)
        if self.verdict not in _REVIEWS:
            raise AuditRefusal("review does not grant or approve an effect")
        _sha("note_sha256", self.note_sha256)


def decision_from_gate(
    observation: dict[str, Any],
    *,
    decision_id: str,
    owner: str,
    dot_id: str,
    workspace_id: str,
    run_id: str,
    work_item_id: str,
    model: str,
) -> DecisionObservation:
    """Turn a quality-gate observation into an advisory decision. No grant is read."""
    if not isinstance(observation, dict):
        raise AuditRefusal("quality gate observation must be an object")
    if observation.get("authorizes_effect") is not False or observation.get("grant_id") not in (None, ""):
        raise AuditRefusal("quality gate observation cannot carry a grant")
    if observation.get("stage") != "quality_gate" or type(observation.get("passed")) is not bool:
        raise AuditRefusal("quality gate observation is incomplete")
    reason = str(observation.get("reason") or "")
    return DecisionObservation(
        decision_id=decision_id,
        owner=owner,
        dot_id=dot_id,
        workspace_id=workspace_id,
        run_id=run_id,
        work_item_id=work_item_id,
        model=model,
        choice="pass" if observation["passed"] else "fail",
        confidence=1.0 if observation["passed"] else 0.0,
        prompt_sha256=_sha256(reason),
        source="quality_gate",
    )


class DecisionReceiptLedger:
    """SQLite chain of custody. Visibility is owner plus Dot. Effects stay outside."""

    def __init__(
        self,
        state_root: Path | str,
        *,
        clock: Callable[[], float] = time.time,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        root = Path(state_root)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "decision_receipt_audit.sqlite3"
        self.clock = clock
        self.on_event = on_event
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS chains(
                    chain_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    dot_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    work_item_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    decision_sha256 TEXT NOT NULL,
                    authorizes_effect INTEGER NOT NULL DEFAULT 0,
                    uncertain INTEGER NOT NULL DEFAULT 0,
                    resend_allowed INTEGER NOT NULL DEFAULT 0,
                    opened_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL,
                    body_json TEXT NOT NULL,
                    prev_sha256 TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(chain_id, stage)
                );
                CREATE TABLE IF NOT EXISTS refusals(
                    refusal_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    dot_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    rules_json TEXT NOT NULL,
                    subject_sha256 TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(owner, dot_id, kind, subject_sha256)
                );
                """
            )

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def _emit(self, event: str) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _refusal(self, db, owner: str, dot_id: str, kind: str, rules: list[str], subject: str) -> None:
        subject_sha = subject if _SHA.fullmatch(subject) else _sha256(subject)
        refusal_id = "refusal-" + _sha256(_canonical({
            "owner": owner, "dot_id": dot_id, "kind": kind, "subject": subject_sha,
        }))[:32]
        db.execute(
            "INSERT OR IGNORE INTO refusals VALUES(?,?,?,?,?,?,?)",
            (refusal_id, owner, dot_id, kind, _canonical(rules), subject_sha, self.clock()),
        )

    def open_chain(
        self,
        decision: DecisionObservation,
        *,
        untrusted_content: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(decision, DecisionObservation):
            raise ValueError("typed decision observation required")
        content_sha = None
        if untrusted_content is not None:
            verdict = classify_untrusted(untrusted_content)
            content_sha = verdict["digest"]
            if verdict["injection"]:
                self._persist_refusal(
                    decision.owner, decision.dot_id, "injection", verdict["rules"], content_sha,
                )
                self._emit("injection_refused")
                raise AuditRefusal("injection: untrusted content cannot instruct or grant")
        body = self._decision_body(decision, content_sha)
        sealed = _canonical(body)
        decision_sha = _sha256(sealed)
        key = _sha256(_canonical({
            "owner": decision.owner,
            "dot_id": decision.dot_id,
            "workspace_id": decision.workspace_id,
            "run_id": decision.run_id,
            "work_item_id": decision.work_item_id,
            "decision_id": decision.decision_id,
        }))
        chain_id = "audit-" + key[:32]
        created = False
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM chains WHERE idempotency_key=?", (key,),
            ).fetchone()
            if existing is not None:
                if existing["decision_sha256"] != decision_sha:
                    db.rollback()
                    raise AuditConflict("idempotency: decision already sealed with a different body")
                view = self._view(db, existing)
                db.rollback()
                return view
            now = self.clock()
            db.execute(
                "INSERT INTO chains VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (chain_id, decision.owner, decision.dot_id, decision.workspace_id,
                 decision.run_id, decision.work_item_id, decision.decision_id, key,
                 decision_sha, 0, 0, 0, now),
            )
            db.execute(
                "INSERT INTO events(chain_id,stage,body_sha256,body_json,prev_sha256,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (chain_id, "decision", decision_sha, sealed, _GENESIS, now),
            )
            view = self._view(db, db.execute(
                "SELECT * FROM chains WHERE chain_id=?", (chain_id,),
            ).fetchone())
            db.commit()
            created = True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        if created:
            self._emit("chains_opened")
        return view

    def observe_tool(
        self,
        chain_id: str,
        *,
        owner: str,
        dot_id: str,
        tool_name: str,
        args_sha256: str | None = None,
        raw_args: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(tool_name, str) or not _TOOL.fullmatch(tool_name):
            raise ValueError("invalid tool name")
        if raw_args is not None:
            verdict = classify_untrusted(raw_args)
            if verdict["injection"]:
                self._persist_refusal(owner, dot_id, "injection", verdict["rules"], verdict["digest"])
                self._emit("injection_refused")
                raise AuditRefusal("injection: tool arguments cannot instruct or grant")
            if args_sha256 is not None and args_sha256 != verdict["digest"]:
                raise AuditRefusal("tool args digest mismatch")
            args_sha256 = verdict["digest"]
        digest = _sha("args_sha256", args_sha256)
        body = {
            "stage": "tool",
            "tool_name": tool_name,
            "args_sha256": digest,
            "authorizes_effect": False,
        }
        return self._append(chain_id, owner, dot_id, "tool", body)

    def observe_authorization(
        self,
        chain_id: str,
        *,
        owner: str,
        dot_id: str,
        observation: AuthorizationObservation,
    ) -> dict[str, Any]:
        if not isinstance(observation, AuthorizationObservation):
            raise ValueError("typed authorization observation required")
        if observation.owner != owner:
            self._persist_refusal(owner, dot_id, "isolation", ["owner_mismatch"], _sha256(chain_id))
            self._emit("isolation_refused")
            raise AuditRefusal("isolation: authorization owner mismatch")
        self._check_principal(owner, dot_id, observation)
        reason = self._clean_reason(observation.reason)
        verdict = classify_untrusted(reason)
        if verdict["injection"]:
            self._persist_refusal(owner, dot_id, "injection", verdict["rules"], verdict["digest"])
            self._emit("injection_refused")
            raise AuditRefusal("injection: authorization reason cannot instruct or grant")
        self._check_auth_shape(observation)
        body = {
            "stage": "authorization",
            "owner": observation.owner,
            "principal_type": observation.principal_type,
            "principal_id": observation.principal_id,
            "capability": observation.capability,
            "scope_type": observation.scope_type,
            "scope_id": observation.scope_id,
            "allowed": observation.allowed,
            "source": observation.source,
            "grant_id": observation.grant_id,
            "reason": reason,
            "authorizes_effect": False,
        }
        return self._append(chain_id, owner, dot_id, "authorization", body)

    def observe_execution(
        self,
        chain_id: str,
        *,
        owner: str,
        dot_id: str,
        observation: ExecutionObservation,
    ) -> dict[str, Any]:
        if not isinstance(observation, ExecutionObservation):
            raise ValueError("typed execution observation required")
        body = {
            "stage": "execution",
            "operation_id": observation.operation_id,
            "run_id": observation.run_id,
            "work_item_id": observation.work_item_id,
            "lease_id": observation.lease_id,
            "fence_token": observation.fence_token,
            "fencing_token": observation.fencing_token,
            "effect_started": observation.effect_started,
            "authorizes_effect": False,
        }
        return self._append(chain_id, owner, dot_id, "execution", body, observation=observation)

    def observe_result(
        self,
        chain_id: str,
        *,
        owner: str,
        dot_id: str,
        observation: ResultObservation,
    ) -> dict[str, Any]:
        if not isinstance(observation, ResultObservation):
            raise ValueError("typed result observation required")
        body = {
            "stage": "result",
            "outcome": observation.outcome,
            "evidence_sha256": observation.evidence_sha256,
            "authorizes_effect": False,
        }
        return self._append(chain_id, owner, dot_id, "result", body)

    def observe_receipt(
        self,
        chain_id: str,
        *,
        owner: str,
        dot_id: str,
        observation: ReceiptObservation,
    ) -> dict[str, Any]:
        if not isinstance(observation, ReceiptObservation):
            raise ValueError("typed receipt observation required")
        body = {
            "stage": "receipt",
            "receipt_id": observation.receipt_id,
            "operation_id": observation.operation_id,
            "run_id": observation.run_id,
            "work_item_id": observation.work_item_id,
            "intent_sha256": observation.intent_sha256,
            "state": observation.state,
            "evidence_sha256": observation.evidence_sha256,
            "resend_allowed": False,
            "authorizes_effect": False,
        }
        return self._append(chain_id, owner, dot_id, "receipt", body, observation=observation)

    def observe_reconciliation(
        self,
        chain_id: str,
        *,
        owner: str,
        dot_id: str,
        observation: ReconciliationObservation,
    ) -> dict[str, Any]:
        if not isinstance(observation, ReconciliationObservation):
            raise ValueError("typed reconciliation observation required")
        if observation.resend is not False:
            self._persist_refusal(owner, dot_id, "resend", ["reconciliation_resend"], _sha256(chain_id))
            self._emit("resend_refused")
            raise AuditRefusal("UNCERTAIN operation is not resent")
        body = {
            "stage": "reconciliation",
            "operation_id": observation.operation_id,
            "intent_sha256": observation.intent_sha256,
            "state": observation.state,
            "resend": False,
            "authorizes_effect": False,
        }
        return self._append(chain_id, owner, dot_id, "reconciliation", body, observation=observation)

    def observe_review(
        self,
        chain_id: str,
        *,
        owner: str,
        dot_id: str,
        observation: ReviewObservation,
    ) -> dict[str, Any]:
        if not isinstance(observation, ReviewObservation):
            raise ValueError("typed review observation required")
        body = {
            "stage": "review",
            "reviewer_id": observation.reviewer_id,
            "verdict": observation.verdict,
            "note_sha256": observation.note_sha256,
            "authorizes_effect": False,
        }
        return self._append(chain_id, owner, dot_id, "review", body)

    def bind_central_receipt(
        self,
        chain_id: str,
        *,
        owner: str,
        dot_id: str,
        durable: Any,
        governance: Any,
        authorization: Any,
    ) -> dict[str, Any]:
        """Read the central Run, WorkItem, Operation receipt and Grant.

        The cited objects must already exist. This method does not reserve an
        intent, issue a Grant, renew a lease, or dispatch an effect.
        """
        view = self.read(chain_id, owner=owner, dot_id=dot_id)
        events = {event["stage"]: event for event in view["events"]}
        auth = events.get("authorization")
        execution = events.get("execution")
        if auth is None or execution is None:
            raise AuditRefusal("central receipt requires authorization and execution")
        if auth.get("source") != "grant" or not auth.get("grant_id") or auth.get("allowed") is not True:
            raise AuditRefusal("central receipt requires an observed grant")
        operation_id = execution["operation_id"]
        try:
            from sentra_runtime.central_authority import CentralDurableIntentAuthority
            receipt = CentralDurableIntentAuthority(durable).receipt_for_operation(operation_id, owner)
            operation = durable.operation_status(operation_id, owner)
            run = durable.run_status(receipt.run_id, owner, include_details=False)
            progress = operation.get("progress") if isinstance(operation.get("progress"), dict) else {}
            work_item_id = progress.get("work_item_id")
            work = governance.work_item_info(work_item_id, owner)
            grant = authorization.info(auth["grant_id"], owner)
        except AuditRefusal:
            raise
        except Exception as exc:
            raise AuditRefusal("central operation receipt unavailable") from exc
        self._check_central_binding(
            view, auth, execution, receipt, operation, run, work, grant,
        )
        body = {
            "stage": "central_receipt",
            "run_id": run["run_id"],
            "work_item_id": work["work_item_id"],
            "operation_id": operation["operation_id"],
            "grant_id": grant["grant_id"],
            "intent_sha256": receipt.intent_sha256,
            "fencing_token": receipt.fencing_token,
            "central_state": operation["state"],
            "resend_allowed": False,
            "authorizes_effect": False,
        }
        return self._append(chain_id, owner, dot_id, "central_receipt", body)

    @staticmethod
    def _check_central_binding(view, auth, execution, receipt, operation, run, work, grant) -> None:
        if (
            receipt.owner != view["owner"]
            or receipt.run_id != view["run_id"]
            or run.get("run_id") != view["run_id"]
            or run.get("owner") != view["owner"]
        ):
            raise AuditRefusal("central receipt Run mismatch")
        if (
            work.get("work_item_id") != view["work_item_id"]
            or work.get("run_id") != view["run_id"]
            or work.get("owner") != view["owner"]
        ):
            raise AuditRefusal("central receipt WorkItem mismatch")
        progress = operation.get("progress") if isinstance(operation.get("progress"), dict) else {}
        if (
            operation.get("operation_id") != execution["operation_id"]
            or operation.get("run_id") != view["run_id"]
            or operation.get("owner") != view["owner"]
            or progress.get("work_item_id") != view["work_item_id"]
            or receipt.operation_id != execution["operation_id"]
            or not _SHA.fullmatch(str(receipt.intent_sha256 or ""))
        ):
            raise AuditRefusal("central receipt Operation mismatch")
        scope_id = grant.get("scope_id")
        if (
            grant.get("grant_id") != auth.get("grant_id")
            or grant.get("owner") != view["owner"]
            or grant.get("revoked") is True
            or grant.get("effect") != "allow"
            or grant.get("principal_type") != auth.get("principal_type")
            or grant.get("principal_id") != auth.get("principal_id")
            or grant.get("capability") != auth.get("capability")
            or grant.get("scope_type") != auth.get("scope_type")
            or scope_id != auth.get("scope_id")
            or progress.get("principal_id") != grant.get("principal_id")
            or progress.get("capability_id") != grant.get("capability")
        ):
            raise AuditRefusal("central receipt Grant mismatch")
        expires = grant.get("expires_at")
        if expires is not None and float(expires) <= time.time():
            raise AuditRefusal("central receipt Grant mismatch")
        if not re.fullmatch(r"[A-Z_]{1,40}", str(operation.get("state") or "")):
            raise AuditRefusal("central receipt Operation mismatch")

    def request_resend(self, chain_id: str, *, owner: str, dot_id: str) -> None:
        """The ledger never dispatches. UNCERTAIN is called out explicitly."""
        view = self.read(chain_id, owner=owner, dot_id=dot_id)
        self._persist_refusal(owner, dot_id, "resend", ["request_resend"], _sha256(chain_id))
        self._emit("resend_refused")
        if view["uncertain"]:
            raise AuditRefusal("UNCERTAIN operation is not resent")
        raise AuditRefusal("audit ledger does not dispatch or resend effects")

    def allows(self, chain_id: str, *, owner: str, dot_id: str, capability: str) -> bool:
        """Visibility check only. A recorded chain never admits an effect."""
        self.read(chain_id, owner=owner, dot_id=dot_id)
        if not isinstance(capability, str):
            raise ValueError("capability must be text")
        return False

    def read(self, chain_id: str, *, owner: str, dot_id: str) -> dict[str, Any]:
        _ident("owner", owner, minimum=2)
        _ident("dot_id", dot_id, minimum=2)
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM chains WHERE chain_id=?", (chain_id,)).fetchone()
            if row is None or row["owner"] != owner or row["dot_id"] != dot_id:
                self._refusal(db, owner, dot_id, "isolation", ["chain_not_visible"], chain_id)
                db.commit()
                hidden = True
                view = None
            else:
                view = self._view(db, row)
                db.rollback()
                hidden = False
        except AuditRefusal:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        if hidden or view is None:
            self._emit("isolation_refused")
            raise AuditRefusal("isolation: chain not visible to this owner and dot")
        return view

    def _persist_refusal(self, owner: str, dot_id: str, kind: str, rules: list[str], subject: str) -> None:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._refusal(db, owner, dot_id, kind, rules, subject)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _append(
        self,
        chain_id: str,
        owner: str,
        dot_id: str,
        stage: str,
        body: dict[str, Any],
        *,
        observation: Any = None,
    ) -> dict[str, Any]:
        sealed = _canonical(body)
        body_sha = _sha256(sealed)
        uncertain_held = False
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM chains WHERE chain_id=?", (chain_id,)).fetchone()
            if row is None or row["owner"] != owner or row["dot_id"] != dot_id:
                self._refusal(db, owner, dot_id, "isolation", ["chain_not_visible"], chain_id)
                db.commit()
                hidden = True
            else:
                hidden = False
                events = self._event_rows(db, chain_id)
                self._verify_rows(row, events)
                match = [event for event in events if event["stage"] == stage]
                if match:
                    if match[0]["body_sha256"] == body_sha and match[0]["body_json"] == sealed:
                        view = json.loads(match[0]["body_json"])
                        db.rollback()
                        return view
                    db.rollback()
                    raise AuditConflict(f"idempotency: {stage} already recorded with a different body")
                self._assert_stage(row, events, stage, body, observation)
                prev = events[-1]["body_sha256"] if events else _GENESIS
                db.execute(
                    "INSERT INTO events(chain_id,stage,body_sha256,body_json,prev_sha256,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (chain_id, stage, body_sha, sealed, prev, self.clock()),
                )
                if stage == "receipt" and body["state"] == "UNCERTAIN":
                    db.execute(
                        "UPDATE chains SET uncertain=1, resend_allowed=0 WHERE chain_id=?",
                        (chain_id,),
                    )
                    uncertain_held = True
                if stage == "reconciliation":
                    db.execute(
                        "UPDATE chains SET uncertain=1, resend_allowed=0 WHERE chain_id=?",
                        (chain_id,),
                    )
                if stage == "central_receipt" and body.get("central_state") == "UNCERTAIN":
                    db.execute(
                        "UPDATE chains SET uncertain=1, resend_allowed=0 WHERE chain_id=?",
                        (chain_id,),
                    )
                    uncertain_held = True
                db.commit()
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()
        if hidden:
            self._emit("isolation_refused")
            raise AuditRefusal("isolation: chain not visible to this owner and dot")
        if uncertain_held:
            self._emit("uncertain_held")
        return body

    def _assert_stage(self, row, events, stage: str, body: dict[str, Any], observation: Any) -> None:
        present = {event["stage"] for event in events}
        required = {
            "tool": ["decision"],
            "authorization": ["decision", "tool"],
            "execution": ["decision", "tool", "authorization"],
            "result": ["decision", "tool", "authorization", "execution"],
            "receipt": ["decision", "tool", "authorization", "execution", "result"],
            "reconciliation": ["decision", "tool", "authorization", "execution", "result", "receipt"],
            "review": ["decision", "tool", "authorization", "execution", "result", "receipt"],
            "central_receipt": ["decision", "tool", "authorization", "execution"],
        }[stage]
        missing = [item for item in required if item not in present]
        if missing:
            raise AuditRefusal("audit stage " + stage + " requires " + ",".join(missing))
        parsed = {event["stage"]: json.loads(event["body_json"]) for event in events}
        if stage == "execution":
            auth = parsed["authorization"]
            if auth.get("allowed") is not True:
                raise AuditRefusal("execution requires an observed allow; denial is not an effect")
            if observation.run_id != row["run_id"] or observation.work_item_id != row["work_item_id"]:
                raise AuditRefusal("execution Run/WorkItem mismatch")
        if stage == "receipt":
            execution = parsed["execution"]
            result = parsed["result"]
            if body["operation_id"] != execution["operation_id"]:
                raise AuditRefusal("receipt operation mismatch")
            if body["run_id"] != row["run_id"] or body["work_item_id"] != row["work_item_id"]:
                raise AuditRefusal("receipt Run/WorkItem mismatch")
            if body["state"] == "SUCCEEDED":
                if execution["effect_started"] is not True or result["outcome"] != "observed":
                    raise AuditRefusal("SUCCEEDED receipt requires effect_started and an observed result")
            elif body["state"] == "UNCERTAIN":
                if result["outcome"] != "withheld":
                    raise AuditRefusal("UNCERTAIN receipt cannot claim an observed result")
            elif result["outcome"] not in {"failed", "withheld"}:
                raise AuditRefusal("terminal failure receipt disagrees with the result")
            if (
                result.get("evidence_sha256")
                and body.get("evidence_sha256")
                and result["evidence_sha256"] != body["evidence_sha256"]
            ):
                raise AuditRefusal("receipt evidence digest mismatch")
        if stage == "reconciliation":
            receipt = parsed["receipt"]
            if receipt["state"] != "UNCERTAIN":
                raise AuditRefusal("reconciliation only follows an UNCERTAIN receipt")
            if body["operation_id"] != receipt["operation_id"] or body["intent_sha256"] != receipt["intent_sha256"]:
                raise AuditRefusal("reconciliation binding mismatch")
            if body["resend"] is not False:
                raise AuditRefusal("UNCERTAIN operation is not resent")
        if stage == "central_receipt":
            auth = parsed["authorization"]
            execution = parsed["execution"]
            if auth.get("source") != "grant" or not auth.get("grant_id") or auth.get("allowed") is not True:
                raise AuditRefusal("central receipt requires an observed grant")
            if body["operation_id"] != execution["operation_id"]:
                raise AuditRefusal("central receipt Operation mismatch")
            if body["run_id"] != row["run_id"] or body["work_item_id"] != row["work_item_id"]:
                raise AuditRefusal("central receipt Run/WorkItem mismatch")
            if body.get("resend_allowed") is not False or body.get("authorizes_effect") is not False:
                raise AuditRefusal("central receipt cannot authorize an effect or a resend")
            local = parsed.get("receipt")
            if local is not None and (
                local["operation_id"] != body["operation_id"]
                or local["intent_sha256"] != body["intent_sha256"]
            ):
                raise AuditRefusal("central receipt disagrees with the sealed receipt")
            if body.get("central_state") == "UNCERTAIN" and body.get("resend_allowed") is not False:
                raise AuditRefusal("UNCERTAIN operation is not resent")

    def _check_principal(self, owner: str, dot_id: str, observation: AuthorizationObservation) -> None:
        if observation.source == "local_owner":
            return
        if observation.principal_type == "agent" and observation.principal_id == dot_id:
            return
        if observation.principal_type == "user" and observation.principal_id == owner:
            return
        self._persist_refusal(owner, dot_id, "isolation", ["principal_mismatch"], _sha256(observation.principal_id))
        self._emit("isolation_refused")
        raise AuditRefusal("isolation: principal is outside this owner and dot")

    @staticmethod
    def _check_auth_shape(observation: AuthorizationObservation) -> None:
        if observation.source == "policy":
            if observation.allowed or observation.grant_id is not None:
                raise AuditRefusal("policy observation cannot allow or cite a grant")
            return
        if observation.source == "local_owner":
            if (
                observation.allowed is not True
                or observation.principal_type != "user"
                or observation.principal_id != observation.owner
                or observation.grant_id is not None
            ):
                raise AuditRefusal("local_owner observation is only a user principal without a grant id")
            return
        if observation.allowed and observation.grant_id is None:
            raise AuditRefusal("an allow observation requires a grant id")
        if observation.grant_id is None and observation.allowed:
            raise AuditRefusal("an allow observation requires a grant id")

    @staticmethod
    def _clean_reason(reason: str) -> str:
        text = "".join(ch for ch in reason.replace("\r", " ").replace("\n", " ") if ch.isprintable())
        text = text.strip()[:200]
        if not text:
            raise ValueError("authorization reason required")
        return text

    @staticmethod
    def _decision_body(decision: DecisionObservation, content_sha: str | None) -> dict[str, Any]:
        return {
            "stage": "decision",
            "decision_id": decision.decision_id,
            "owner": decision.owner,
            "dot_id": decision.dot_id,
            "workspace_id": decision.workspace_id,
            "run_id": decision.run_id,
            "work_item_id": decision.work_item_id,
            "model": decision.model,
            "choice": decision.choice,
            "confidence": decision.confidence,
            "prompt_sha256": decision.prompt_sha256,
            "source": decision.source,
            "untrusted_sha256": content_sha,
            "authorizes_effect": False,
        }

    def _event_rows(self, db, chain_id: str):
        return list(db.execute(
            "SELECT * FROM events WHERE chain_id=? ORDER BY seq", (chain_id,),
        ))

    def _verify_rows(self, row, events) -> None:
        if int(row["authorizes_effect"]) != 0 or int(row["resend_allowed"]) != 0:
            raise AuditRefusal("audit chain must not authorize an effect or a resend")
        if int(row["uncertain"]) and int(row["resend_allowed"]) != 0:
            raise AuditRefusal("UNCERTAIN chain cannot allow resend")
        prev = _GENESIS
        for event in events:
            if event["prev_sha256"] != prev:
                raise AuditRefusal("audit hash chain mismatch")
            if _sha256(event["body_json"]) != event["body_sha256"]:
                raise AuditRefusal("audit hash chain mismatch")
            body = json.loads(event["body_json"])
            if body.get("authorizes_effect") is not False:
                raise AuditRefusal("audit event must not authorize an effect")
            if event["stage"] == "receipt" and body.get("state") == "UNCERTAIN":
                if int(row["uncertain"]) != 1 or body.get("resend_allowed") is not False:
                    raise AuditRefusal("UNCERTAIN receipt is not resendable")
            prev = event["body_sha256"]

    def _view(self, db, row) -> dict[str, Any]:
        events = self._event_rows(db, row["chain_id"])
        self._verify_rows(row, events)
        bodies = [json.loads(event["body_json"]) for event in events]
        return {
            "chain_id": row["chain_id"],
            "owner": row["owner"],
            "dot_id": row["dot_id"],
            "workspace_id": row["workspace_id"],
            "run_id": row["run_id"],
            "work_item_id": row["work_item_id"],
            "decision_id": row["decision_id"],
            "authorizes_effect": False,
            "uncertain": bool(row["uncertain"]),
            "resend_allowed": False,
            "central_receipt_reached": any(event["stage"] == "central_receipt" for event in events),
            "stages": [event["stage"] for event in events],
            "events": bodies,
        }
