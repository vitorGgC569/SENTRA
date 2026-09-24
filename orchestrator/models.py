from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    REJECTED = "REJECTED"
    REPAIRING = "REPAIRING"
    READY = "READY"
    DISPUTED = "DISPUTED"
    QUALITY_GATE = "QUALITY_GATE"
    READY_FOR_MASTER = "READY_FOR_MASTER"
    MASTER_REVIEW = "MASTER_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"


class TaskPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Severity(str, Enum):
    INFO = "INFO"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ValidatorRole(str, Enum):
    LOGIC = "validator.logic"
    REQUIREMENTS = "validator.requirements"
    ADVERSARIAL = "validator.adversarial"
    EDGE_CASES = "validator.edge_cases"
    SECURITY = "validator.security"
    PERFORMANCE = "validator.performance"
    GENERAL = "validator.general"


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    model: str = ""
    estimated_cost: float = 0.0
    accounting: str = "estimated"  # provider | estimated; never equate estimates with billed tokens

    def add(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            model=other.model or self.model,
            estimated_cost=self.estimated_cost + other.estimated_cost,
            accounting="provider" if self.accounting == other.accounting == "provider" else "estimated",
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TokenUsage:
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


@dataclass
class Finding:
    finding_id: str = field(default_factory=lambda: f"fnd_{uuid.uuid4().hex[:8]}")
    severity: Severity = Severity.MINOR
    category: str = "GENERAL"
    description: str = ""
    suggested_fix: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value if isinstance(self.severity, Severity) else str(self.severity)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Finding:
        data_copy = dict(data)
        if "severity" in data_copy and isinstance(data_copy["severity"], str):
            try:
                data_copy["severity"] = Severity(data_copy["severity"].upper())
            except ValueError:
                data_copy["severity"] = Severity.MINOR
        return cls(**{k: v for k, v in data_copy.items() if k in cls.__annotations__})


@dataclass
class Evidence:
    evidence_id: str = field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:8]}")
    type: str = "TEST_OUTPUT"  # TEST_OUTPUT, DIFF, LOG, STATIC_ANALYSIS, METRIC
    description: str = ""
    content: str = ""
    passed: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Evidence:
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


def _opt_score(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ValidationReport:
    report_id: str = field(default_factory=lambda: f"val_{uuid.uuid4().hex[:8]}")
    candidate_id: str = ""
    task_id: str = ""
    validator_id: str = ""
    validator_role: str = ValidatorRole.GENERAL.value
    status: str = "APPROVED"  # APPROVED, REJECTED, DISPUTED
    confidence: float = 1.0
    # Critic score 0-10 (release bar: minimum across critics). None = unset
    # (legacy reports); readers fall back to confidence*10. Set at build time
    # by validators (explicit model score, else confidence-derived).
    score: Optional[float] = None
    # ran=False: o validador NÃO produziu julgamento (falha de transporte,
    # budget, timeout antes do modelo). Não é evidência contra o candidato e o
    # Quality Gate o exclui do quorum (INSUFFICIENT_VALIDATION, nunca REJECTED).
    ran: bool = True
    error: str = ""
    summary: str = ""
    findings: List[Finding] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    tests: List[Dict[str, Any]] = field(default_factory=list)
    requirements_checked: List[str] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    created_at: float = field(default_factory=time.time)

    def has_critical_findings(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.findings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "candidate_id": self.candidate_id,
            "task_id": self.task_id,
            "validator_id": self.validator_id,
            "validator_role": self.validator_role,
            "status": self.status,
            "confidence": self.confidence,
            "score": self.score,
            "ran": self.ran,
            "error": self.error,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
            "evidence": [e.to_dict() for e in self.evidence],
            "tests": self.tests,
            "requirements_checked": self.requirements_checked,
            "token_usage": self.token_usage.to_dict(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ValidationReport:
        findings = [Finding.from_dict(f) for f in data.get("findings", [])]
        evidence = [Evidence.from_dict(e) for e in data.get("evidence", [])]
        tok = TokenUsage.from_dict(data.get("token_usage", {})) if "token_usage" in data else TokenUsage()
        return cls(
            report_id=data.get("report_id", f"val_{uuid.uuid4().hex[:8]}"),
            candidate_id=data.get("candidate_id", ""),
            task_id=data.get("task_id", ""),
            validator_id=data.get("validator_id", ""),
            validator_role=data.get("validator_role", ValidatorRole.GENERAL.value),
            status=data.get("status", "APPROVED"),
            confidence=float(data.get("confidence", 1.0)),
            score=_opt_score(data.get("score")),
            ran=bool(data.get("ran", True)),
            error=data.get("error", ""),
            summary=data.get("summary", ""),
            findings=findings,
            evidence=evidence,
            tests=data.get("tests", []),
            requirements_checked=data.get("requirements_checked", []),
            token_usage=tok,
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class Candidate:
    candidate_id: str = field(default_factory=lambda: f"cand_{uuid.uuid4().hex[:8]}")
    task_id: str = ""
    run_id: str = ""
    version: int = 1
    summary: str = ""
    solution: str = ""
    patch: str = ""
    files_affected: List[str] = field(default_factory=list)
    validation_commands: List[str] = field(default_factory=list)
    created_by: str = "executor"
    status: str = "CREATED"  # CREATED, VALIDATED, REJECTED, READY, PROMOTED
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "version": self.version,
            "summary": self.summary,
            "solution": self.solution,
            "patch": self.patch,
            "files_affected": self.files_affected,
            "validation_commands": self.validation_commands,
            "created_by": self.created_by,
            "status": self.status,
            "token_usage": self.token_usage.to_dict(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Candidate:
        tok = TokenUsage.from_dict(data.get("token_usage", {})) if "token_usage" in data else TokenUsage()
        return cls(
            candidate_id=data.get("candidate_id", f"cand_{uuid.uuid4().hex[:8]}"),
            task_id=data.get("task_id", ""),
            run_id=data.get("run_id", ""),
            version=int(data.get("version", 1)),
            summary=data.get("summary", ""),
            solution=data.get("solution", ""),
            patch=data.get("patch", ""),
            files_affected=data.get("files_affected", []),
            validation_commands=data.get("validation_commands", []),
            created_by=data.get("created_by", "executor"),
            status=data.get("status", "CREATED"),
            token_usage=tok,
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class CandidatePackage:
    candidate_id: str
    task_id: str
    task_objective: str
    solution_summary: str
    solution: str
    patch: str
    validators_count: int = 0
    approvals_count: int = 0
    rejections_count: int = 0
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    requirements_coverage: float = 1.0
    calculated_confidence: float = 1.0
    min_validator_score: float = 0.0
    mean_validator_score: float = 0.0
    execution_iterations: int = 1
    repair_rounds: int = 0
    critical_risks: List[str] = field(default_factory=list)
    remaining_risks: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    status: str = "READY_FOR_MASTER"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CandidatePackage:
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


@dataclass
class MasterDecision:
    decision: str = "APPROVED"  # APPROVED, REJECTED, REPLAN
    selected_candidate_id: Optional[str] = None
    confidence: float = 1.0
    critical_issues: List[str] = field(default_factory=list)
    remaining_risks: List[str] = field(default_factory=list)
    needs_more_work: bool = False
    new_tasks: List[Dict[str, Any]] = field(default_factory=list)
    final_response: Optional[str] = None
    reasoning: str = ""
    token_usage: TokenUsage = field(default_factory=TokenUsage)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["token_usage"] = self.token_usage.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MasterDecision:
        tok = TokenUsage.from_dict(data.get("token_usage", {})) if "token_usage" in data else TokenUsage()
        clean = {k: v for k, v in data.items() if k in cls.__annotations__ and k != "token_usage"}
        return cls(token_usage=tok, **clean)


@dataclass
class Task:
    id: str
    run_id: str
    objective: str
    description: str = ""
    dependencies: List[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.MEDIUM
    risk: str = "LOW"
    required_capabilities: List[str] = field(default_factory=list)
    validation_strategy: str = "standard"
    status: TaskStatus = TaskStatus.PENDING
    max_iterations: int = 4
    max_repair_rounds: int = 4
    current_repair_round: int = 0
    token_budget: int = 30000
    retry_count: int = 0
    max_retries: int = 3
    depth: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    target_files: List[str] = field(default_factory=list)
    side_effect_scope: str = "ISOLATED"
    resource_locks: List[str] = field(default_factory=list)
    timeout_s: float = 900.0
    heartbeat_timeout_s: float = 120.0
    idempotency_key: str = ""
    active_candidate_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.idempotency_key:
            basis = f"{self.run_id}\0{self.id}\0{self.objective}"
            self.idempotency_key = (
                "task-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "objective": self.objective,
            "description": self.description,
            "dependencies": self.dependencies,
            "priority": self.priority.value if isinstance(self.priority, TaskPriority) else str(self.priority),
            "risk": self.risk,
            "required_capabilities": self.required_capabilities,
            "validation_strategy": self.validation_strategy,
            "status": self.status.value if isinstance(self.status, TaskStatus) else str(self.status),
            "max_iterations": self.max_iterations,
            "max_repair_rounds": self.max_repair_rounds,
            "current_repair_round": self.current_repair_round,
            "token_budget": self.token_budget,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "depth": self.depth,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "target_files": self.target_files,
            "side_effect_scope": self.side_effect_scope,
            "resource_locks": self.resource_locks,
            "timeout_s": self.timeout_s,
            "heartbeat_timeout_s": self.heartbeat_timeout_s,
            "idempotency_key": self.idempotency_key,
            "active_candidate_id": self.active_candidate_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Task:
        data_copy = dict(data)
        if "priority" in data_copy and isinstance(data_copy["priority"], str):
            try:
                data_copy["priority"] = TaskPriority(data_copy["priority"].upper())
            except ValueError:
                data_copy["priority"] = TaskPriority.MEDIUM
        if "status" in data_copy and isinstance(data_copy["status"], str):
            try:
                data_copy["status"] = TaskStatus(data_copy["status"].upper())
            except ValueError:
                data_copy["status"] = TaskStatus.PENDING
        return cls(**{k: v for k, v in data_copy.items() if k in cls.__annotations__})
