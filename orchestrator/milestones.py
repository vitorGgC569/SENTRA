"""WS4 — validacao que compoe em escala (funcoes puras).

Teste por fatia nao garante o sistema: barra 9.5 por tarefa nao impede
deriva arquitetural em 100 tarefas. Este modulo adiciona a camada de
composicao — contratos entre tarefas, gates de marco, budgets por marco e
integridade de evidencia visual — sem tocar a engine.

WIRING SPEC (para o integrador; nenhuma fiacao e feita aqui):
  1. validate_contracts(tasks)
     ONDE: logo apos o planner decompor o objetivo (engine.plan_initial_tasks,
     depois de enfileirar), e a cada replanejamento que altere metadata de
     provides/requires. Falha aqui = abortar o run cedo (DEPENDENCY_ERROR),
     nunca executar tarefas com produtor ausente/versao incompativel/ciclo.
  2. evaluate_milestone(name, task_ids, tasks, validations, min_bar, required_evidence)
     ONDE: no fechamento de cada marco (conjunto de task_ids que forma uma
     entrega parcial), antes de promover o pacote agregado; e no final do run
     como gate global. Entradas: tasks = mapa id->Task (queue._all_tasks),
     validations = mapa task_id->[ValidationReport] (ou scores ja agregados).
     FAIL = nao promove / escala para o operador.
  3. check_budgets(work_dir, budgets, test_command, timeout)
     ONDE: junto de cada gate de marco, com work_dir = workspace de integracao
     e budgets vindos da config do run. test_command = comando de teste do
     marco (ex.: [sys.executable, "-m", "pytest", "tests/...", "-q"]);
     timeout = teto wall-clock (sugestao: max_test_seconds + margem).
  4. evaluate_visual_evidence(evidence, work_dir)
     ONDE: apos captura de screenshot de um viewpoint declarado, antes de
     anexar ao pacote do marco. PASS aqui libera apenas INTEGRIDADE; o
     julgamento de qualidade continua do operador (ver docstring da funcao).

Tudo aqui e deterministico, sem rede e sem estado global.
"""
from __future__ import annotations

import hashlib
import math
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Contratos entre tarefas
# ---------------------------------------------------------------------------

@dataclass
class ContractViolation:
    kind: str = ""  # missing_producer | version_mismatch | provision_cycle | malformed_contract
    consumer_id: Optional[str] = None
    producer_id: Optional[str] = None
    artifact: str = ""
    required_version: Optional[str] = None
    producer_version: Optional[str] = None
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "consumer_id": self.consumer_id,
            "producer_id": self.producer_id,
            "artifact": self.artifact,
            "required_version": self.required_version,
            "producer_version": self.producer_version,
            "detail": self.detail,
        }


def _task_id(task: Any) -> str:
    if isinstance(task, dict):
        return str(task.get("id", ""))
    return str(getattr(task, "id", ""))


def _task_metadata(task: Any) -> Dict[str, Any]:
    if isinstance(task, dict):
        meta = task.get("metadata", {})
        return dict(meta) if isinstance(meta, dict) else {}
    meta = getattr(task, "metadata", {}) or {}
    return dict(meta) if isinstance(meta, dict) else {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _norm_ver(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return str(value).strip() or None


def _normalize_contract_entry(entry: Any) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (name, version, error)."""
    if not isinstance(entry, dict):
        return None, None, f"contract entry must be a mapping, got {type(entry).__name__}"
    name = entry.get("name", None)
    if not isinstance(name, str) or not name.strip():
        return None, None, f"contract entry missing non-empty 'name': {entry!r:.120}"
    return name.strip(), _norm_ver(entry.get("schema_version", None)), None


def validate_contracts(tasks: Any) -> List[ContractViolation]:
    """Validate provides/requires contracts declared in task metadata.

    Each task may declare in ``metadata``:
      provides: [{name, schema_version}, ...]
      requires: [{name, schema_version}, ...]

    Rules (documented for the integrator):
      - requires without any producer of that name -> missing_producer.
      - requires with a version accepts any producer whose normalized
        schema_version is exactly equal; a requires WITHOUT version is a
        wildcard and accepts any producer version. Producers exist but none
        matches -> version_mismatch.
      - compatible provision edges (consumer -> producer) must be acyclic;
        every directed cycle (including a self-loop) -> provision_cycle.
      - entries that are not {name, schema_version} mappings ->
        malformed_contract (never raises; reports honestly).

    Accepts a mapping id->Task or a sequence of Task/dict. Pure.
    """
    if tasks is None:
        return []
    items: List[Any] = list(tasks.values()) if isinstance(tasks, dict) else list(tasks)
    violations: List[ContractViolation] = []
    provides_by_name: Dict[str, List[Tuple[str, Optional[str]]]] = {}
    requires: List[Tuple[str, str, Optional[str]]] = []

    for task in items:
        tid = _task_id(task)
        meta = _task_metadata(task)
        for entry in _as_list(meta.get("provides", [])):
            name, ver, err = _normalize_contract_entry(entry)
            if err:
                violations.append(ContractViolation(
                    kind="malformed_contract", producer_id=tid or None,
                    artifact=str(entry)[:120], detail=f"provides: {err}"))
                continue
            assert name is not None
            provides_by_name.setdefault(name, []).append((tid, ver))
        for entry in _as_list(meta.get("requires", [])):
            name, ver, err = _normalize_contract_entry(entry)
            if err:
                violations.append(ContractViolation(
                    kind="malformed_contract", consumer_id=tid or None,
                    artifact=str(entry)[:120], detail=f"requires: {err}"))
                continue
            assert name is not None
            requires.append((tid, name, ver))

    for consumer_id, name, req_ver in requires:
        producers = provides_by_name.get(name, [])
        if not producers:
            violations.append(ContractViolation(
                kind="missing_producer", consumer_id=consumer_id,
                artifact=name, required_version=req_ver,
                detail=f"task '{consumer_id}' requires '{name}'"
                       + (f"@{req_ver}" if req_ver else "")
                       + " but no task provides it"))
        elif req_ver:
            if not any(_norm_ver(pver) == req_ver for _, pver in producers):
                available = sorted({str(pver) if pver is not None else "<unversioned>"
                                    for _, pver in producers})
                violations.append(ContractViolation(
                    kind="version_mismatch", consumer_id=consumer_id,
                    artifact=name, required_version=req_ver,
                    producer_version=", ".join(available),
                    detail=f"task '{consumer_id}' requires '{name}@{req_ver}'"
                           f" but producers offer [{', '.join(available)}]"))

    adjacency: Dict[str, set] = {}
    nodes: List[str] = sorted({_task_id(t) for t in items if _task_id(t)})
    adjacency = {n: set() for n in nodes}
    for consumer_id, name, req_ver in requires:
        for pid, pver in provides_by_name.get(name, []):
            if not req_ver or _norm_ver(pver) == req_ver:
                if consumer_id in adjacency:
                    adjacency[consumer_id].add(pid)

    color: Dict[str, str] = {n: "white" for n in nodes}
    stack: List[str] = []
    seen_cycles: set = set()
    cycles: List[Tuple[str, ...]] = []

    def _dfs(node: str) -> None:
        color[node] = "gray"
        stack.append(node)
        for nxt in sorted(adjacency.get(node, ())):
            if nxt not in color:
                continue
            if color[nxt] == "gray":
                idx = stack.index(nxt)
                cycle = tuple(stack[idx:] + [nxt])
                if cycle not in seen_cycles:
                    seen_cycles.add(cycle)
                    cycles.append(cycle)
            elif color[nxt] == "white":
                _dfs(nxt)
        stack.pop()
        color[node] = "black"

    for node in nodes:
        if color[node] == "white":
            _dfs(node)

    for cycle in cycles:
        path = " -> ".join(cycle)
        violations.append(ContractViolation(
            kind="provision_cycle", consumer_id=cycle[0],
            producer_id=cycle[-2] if len(cycle) > 1 else cycle[0],
            artifact=path, detail=f"provision cycle: {path}"))

    violations.sort(key=lambda v: (v.kind, v.consumer_id or "",
                                   v.producer_id or "", v.artifact, v.detail))
    return violations


# ---------------------------------------------------------------------------
# Gates de marco
# ---------------------------------------------------------------------------

@dataclass
class MilestoneVerdict:
    name: str = ""
    verdict: str = "FAIL"  # PASS | FAIL
    passed: bool = False
    reasons: List[str] = field(default_factory=list)
    min_score: Optional[float] = None
    completed: int = 0
    total: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "verdict": self.verdict,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "min_score": self.min_score,
            "completed": self.completed,
            "total": self.total,
        }


def _task_status(task: Any) -> str:
    if isinstance(task, dict):
        status = task.get("status", "")
    else:
        status = getattr(task, "status", "")
    value = getattr(status, "value", status)
    try:
        return str(value).upper()
    except Exception:
        return ""


def _report_min_score(report: Any) -> Optional[float]:
    if report is None:
        return None
    if isinstance(report, bool):
        return None
    ran = getattr(report, "ran", True)
    if isinstance(ran, bool) and not ran:
        return None
    score = getattr(report, "score", None)
    if isinstance(score, bool):
        score = None
    if isinstance(score, (int, float)) and math.isfinite(score):
        try:
            return round(max(0.0, min(10.0, float(score))), 2)
        except (TypeError, ValueError):
            pass
    try:
        conf = float(getattr(report, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(conf):
        return None
    return round(max(0.0, min(1.0, conf)) * 10.0, 2)


def _min_score_for_task(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, dict):
        for key in ("min_score", "min_validator_score", "score"):
            candidate = value.get(key, None)
            if isinstance(candidate, bool):
                continue
            if isinstance(candidate, (int, float)) and math.isfinite(candidate):
                return float(candidate)
        if "reports" in value:
            return _min_score_for_task(value.get("reports"))
        return None
    if isinstance(value, (list, tuple)):
        scores = [_min_score_for_task(v) for v in value]
        valid = [s for s in scores if s is not None]
        return min(valid) if valid else None
    pkg_score = getattr(value, "min_validator_score", None)
    if isinstance(pkg_score, bool):
        pass
    elif isinstance(pkg_score, (int, float)) and math.isfinite(pkg_score):
        return float(pkg_score)
    if hasattr(value, "status") or hasattr(value, "validator_role") or hasattr(value, "score"):
        return _report_min_score(value)
    return None


def _evidence_ids_for_task(task: Any, validation: Any) -> set:
    found: set = set()

    def _absorb(items: Any) -> None:
        for item in _as_list(items):
            if item is None:
                continue
            if isinstance(item, str):
                if item.strip():
                    found.add(item.strip())
            elif isinstance(item, dict):
                for key in ("evidence_id", "type", "id", "name"):
                    val = item.get(key, None)
                    if isinstance(val, str) and val.strip():
                        found.add(val.strip())
            else:
                evid = getattr(item, "evidence_id", None)
                if isinstance(evid, str) and evid.strip():
                    found.add(evid.strip())
                etype = getattr(item, "type", None)
                if isinstance(etype, str) and etype.strip():
                    found.add(etype.strip())

    meta = _task_metadata(task)
    for key in ("evidence", "evidence_ids", "accepted_evidence", "attachments"):
        if key in meta:
            _absorb(meta.get(key))

    def _from_validation(value: Any) -> None:
        if value is None or isinstance(value, (bool, int, float, str)):
            return
        if isinstance(value, dict):
            for key in ("evidence", "evidence_ids"):
                if key in value:
                    _absorb(value.get(key))
            if "reports" in value:
                _from_validation(value.get("reports"))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                _from_validation(item)
            return
        _absorb(getattr(value, "evidence", None))
        _absorb(getattr(value, "evidence_ids", None))

    _from_validation(validation)
    return found


def evaluate_milestone(
    name: str,
    task_ids: Sequence[str],
    tasks: Any,
    validations: Optional[Mapping[str, Any]] = None,
    min_bar: float = 9.5,
    required_evidence: Sequence[str] = (),
) -> MilestoneVerdict:
    """Evaluate a milestone gate over a set of tasks (pure).

    PASS requires ALL of: every task_id known and COMPLETED; every task
    with a validation score (minimum critic score, same fallback as the
    per-task gate: explicit score else confidence*10; abstained ran=False
    reports are not evidence) at/above min_bar; every required_evidence
    item present for every task (matched against task metadata evidence
    lists and validation-report evidence ids/types).

    ``tasks`` accepts a mapping id->Task or a sequence of Task/dict.
    ``validations`` maps task_id -> score | report | [reports] | package |
    {score/min_score/min_validator_score/reports}. Pure, no I/O.
    """
    if isinstance(min_bar, bool) or not isinstance(min_bar, (int, float)) \
            or not math.isfinite(min_bar) or not 0.0 <= float(min_bar) <= 10.0:
        raise ValueError("min_bar must be a finite number in 0..10")
    bar = float(min_bar)
    ids = list(task_ids or [])
    if isinstance(tasks, dict):
        index: Dict[str, Any] = dict(tasks)
    elif tasks is None:
        index = {}
    else:
        index = {}
        for task in tasks:
            tid = _task_id(task)
            if tid:
                index[tid] = task
    evidence_required = [str(r).strip() for r in (required_evidence or [])
                         if str(r).strip()]
    validations_map: Mapping[str, Any] = validations or {}

    reasons: List[str] = []
    if not ids:
        return MilestoneVerdict(name=str(name), verdict="FAIL", passed=False,
                                reasons=["empty milestone: no tasks"],
                                min_score=None, completed=0, total=0)
    scores: List[float] = []
    completed = 0
    for tid in ids:
        task = index.get(tid, None)
        if task is None:
            reasons.append(f"unknown task '{tid}'")
            continue
        status = _task_status(task)
        if status == "COMPLETED":
            completed += 1
        else:
            reasons.append(f"incomplete task '{tid}': status={status or 'UNKNOWN'}")
        score = _min_score_for_task(validations_map.get(tid, None))
        if score is None:
            reasons.append(f"missing validation for task '{tid}'")
        else:
            scores.append(float(score))
            if float(score) < bar:
                reasons.append(f"task '{tid}' below bar: {score:.2f} < {bar:.2f}")
        if evidence_required:
            have = _evidence_ids_for_task(task, validations_map.get(tid, None))
            for req in evidence_required:
                if req not in have:
                    reasons.append(f"missing evidence '{req}' for task '{tid}'")

    overall = min(scores) if scores else None
    passed = not reasons
    return MilestoneVerdict(name=str(name), verdict="PASS" if passed else "FAIL",
                            passed=passed, reasons=reasons, min_score=overall,
                            completed=completed, total=len(ids))


# ---------------------------------------------------------------------------
# Budgets de performance por marco
# ---------------------------------------------------------------------------

@dataclass
class BudgetViolation:
    kind: str = ""  # missing_dir | file_lines | file_bytes | test_seconds | test_timeout | test_error | file_error
    path: Optional[str] = None
    actual: Optional[float] = None
    limit: Optional[float] = None
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "actual": self.actual,
            "limit": self.limit,
            "detail": self.detail,
        }


def _count_lines(path: Path) -> int:
    newlines = 0
    total = 0
    trailing_newline = True
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            total += len(chunk)
            newlines += chunk.count(b"\n")
            trailing_newline = chunk.endswith(b"\n")
    if total == 0:
        return 0
    return newlines if trailing_newline else newlines + 1


def check_budgets(
    work_dir: Any,
    budgets: Optional[Mapping[str, Any]] = None,
    test_command: Optional[Sequence[str]] = None,
    timeout: Optional[float] = None,
) -> List[BudgetViolation]:
    """Measure real files against per-file budgets and optionally time a test command.

    ``budgets`` keys (all optional): max_file_lines, max_file_bytes,
    max_test_seconds. Every regular file under work_dir (symlinks skipped,
    no exclusions) violating max_file_lines/max_file_bytes is reported.
    If ``test_command`` is given it is executed locally with cwd=work_dir
    (no network involved) and wall-clock timed; elapsed > max_test_seconds
    -> test_seconds; TimeoutExpired -> test_timeout; OSError on spawn ->
    test_error. A non-zero exit code is NOT a budget violation (correctness
    belongs to the quality gate, not to the budget).
    """
    cfg: Dict[str, Any] = dict(budgets) if budgets else {}
    max_lines = cfg.get("max_file_lines", None)
    max_bytes = cfg.get("max_file_bytes", None)
    max_seconds = cfg.get("max_test_seconds", None)
    for key, value in (("max_file_lines", max_lines),
                       ("max_file_bytes", max_bytes),
                       ("max_test_seconds", max_seconds)):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or float(value) < 0:
            raise ValueError(f"budget '{key}' must be a finite number >= 0")
    if timeout is not None and (isinstance(timeout, bool)
                                or not isinstance(timeout, (int, float))
                                or not math.isfinite(timeout)
                                or float(timeout) <= 0):
        raise ValueError("timeout must be a finite number > 0")

    base = Path(work_dir)
    violations: List[BudgetViolation] = []
    if not base.exists() or not base.is_dir():
        return [BudgetViolation(kind="missing_dir", path=str(base),
                                detail=f"work_dir not found: {base}")]

    limit_lines = float(max_lines) if max_lines is not None else None
    limit_bytes = float(max_bytes) if max_bytes is not None else None
    for path in sorted(base.rglob("*")):
        try:
            if path.is_symlink() or not path.is_file():
                continue
        except OSError:
            continue
        rel = str(path.relative_to(base))
        try:
            size = path.stat().st_size
        except OSError as exc:
            violations.append(BudgetViolation(kind="file_error", path=rel,
                                              detail=f"cannot stat '{rel}': {exc}"))
            continue
        if limit_bytes is not None and float(size) > float(limit_bytes):
            violations.append(BudgetViolation(
                kind="file_bytes", path=rel, actual=float(size),
                limit=float(limit_bytes),
                detail=f"file '{rel}' has {size} bytes > budget {int(limit_bytes)}"))
        if limit_lines is not None:
            try:
                lines = _count_lines(path)
            except OSError as exc:
                violations.append(BudgetViolation(kind="file_error", path=rel,
                                                  detail=f"cannot read '{rel}': {exc}"))
                continue
            if float(lines) > float(limit_lines):
                violations.append(BudgetViolation(
                    kind="file_lines", path=rel, actual=float(lines),
                    limit=float(limit_lines),
                    detail=f"file '{rel}' has {lines} lines > budget {int(limit_lines)}"))

    if test_command is not None:
        cmd = [str(c) for c in test_command]
        if not cmd:
            raise ValueError("test_command must be a non-empty command")
        start = time.monotonic()
        try:
            subprocess.run(cmd, cwd=str(base), capture_output=True,
                           timeout=float(timeout) if timeout is not None else None,
                           check=False)
            elapsed = time.monotonic() - start
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            violations.append(BudgetViolation(
                kind="test_timeout", actual=elapsed,
                limit=float(timeout) if timeout is not None else None,
                detail=f"test command exceeded timeout after {elapsed:.2f}s"))
            violations.sort(key=lambda v: (v.kind, v.path or "", v.detail))
            return violations
        except OSError as exc:
            violations.append(BudgetViolation(
                kind="test_error", detail=f"cannot execute test command: {exc}"))
            violations.sort(key=lambda v: (v.kind, v.path or "", v.detail))
            return violations
        if max_seconds is not None and elapsed > float(max_seconds):
            violations.append(BudgetViolation(
                kind="test_seconds", actual=elapsed, limit=float(max_seconds),
                detail=f"test command took {elapsed:.2f}s > budget {float(max_seconds):.2f}s"))

    violations.sort(key=lambda v: (v.kind, v.path or "", v.detail))
    return violations


# ---------------------------------------------------------------------------
# Gate visual honesto (integridade, nao julgamento)
# ---------------------------------------------------------------------------

@dataclass
class VisualEvidence:
    png_path: str = ""
    viewpoint: str = ""
    sha256: str = ""
    captured_at: float = 0.0
    run_id: str = ""
    task_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "png_path": self.png_path,
            "viewpoint": self.viewpoint,
            "sha256": self.sha256,
            "captured_at": self.captured_at,
            "run_id": self.run_id,
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VisualEvidence":
        return cls(
            png_path=str(data.get("png_path", "")),
            viewpoint=str(data.get("viewpoint", "")),
            sha256=str(data.get("sha256", "")),
            captured_at=data.get("captured_at", 0.0),
            run_id=str(data.get("run_id", "")),
            task_id=str(data.get("task_id", "")),
        )


@dataclass
class VisualVerdict:
    passed: bool = False
    verdict: str = "FAIL"  # PASS | FAIL
    reasons: List[str] = field(default_factory=list)
    actual_sha256: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "actual_sha256": self.actual_sha256,
        }


def _as_visual(evidence: Any) -> VisualEvidence:
    if isinstance(evidence, VisualEvidence):
        return evidence
    if isinstance(evidence, dict):
        return VisualEvidence.from_dict(evidence)
    return VisualEvidence(
        png_path=str(getattr(evidence, "png_path", "") or ""),
        viewpoint=str(getattr(evidence, "viewpoint", "") or ""),
        sha256=str(getattr(evidence, "sha256", "") or ""),
        captured_at=getattr(evidence, "captured_at", 0.0),
        run_id=str(getattr(evidence, "run_id", "") or ""),
        task_id=str(getattr(evidence, "task_id", "") or ""),
    )


def evaluate_visual_evidence(evidence: Any, work_dir: Any) -> VisualVerdict:
    """Verify EXISTENCE and INTEGRITY of a visual evidence file.

    Checks: metadata completa; arquivo existe dentro de work_dir; bytes
    conferem com o sha256 declarado; conteudo e PNG valido por magic bytes.

    THIS IS NOT VISUAL QUALITY JUDGMENT. A PASS HERE MEANS ONLY THAT THE
    FILE EXISTS, IS INTACT, AND IS A REAL PNG — IT SAYS NOTHING ABOUT
    WHETHER THE SCREENSHOT LOOKS CORRECT, COMPLETE, OR ACCEPTABLE. VISUAL
    QUALITY JUDGMENT REMAINS WITH THE HUMAN OPERATOR UNTIL A REAL
    MULTIMODAL EVALUATOR IS CONNECTED. NOTHING IN THIS FUNCTION FAKES,
    SCORES, OR SIMULATES SUCH A JUDGMENT.

    Pure quanto a estado (le apenas o arquivo sob work_dir); sem rede.
    """
    item = _as_visual(evidence)
    reasons: List[str] = []

    if not item.png_path.strip():
        reasons.append("incomplete metadata: png_path is empty")
    if not item.viewpoint.strip():
        reasons.append("incomplete metadata: viewpoint is empty")
    digest = item.sha256.strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        reasons.append("incomplete metadata: sha256 must be 64 hex chars")
    captured = item.captured_at
    if isinstance(captured, bool) or not isinstance(captured, (int, float)) \
            or not math.isfinite(float(captured)) or float(captured) <= 0:
        reasons.append("incomplete metadata: captured_at must be a positive timestamp")
    if not item.run_id.strip():
        reasons.append("incomplete metadata: run_id is empty")
    if not item.task_id.strip():
        reasons.append("incomplete metadata: task_id is empty")

    base = Path(work_dir).resolve()
    candidate = Path(item.png_path)
    resolved = (base / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        reasons.append(f"path escapes work_dir: {item.png_path}")

    actual: Optional[str] = None
    data: Optional[bytes] = None
    if not resolved.exists() or not resolved.is_file():
        reasons.append(f"missing file: {item.png_path}")
        passed = False
        return VisualVerdict(passed=False, verdict="FAIL",
                             reasons=reasons, actual_sha256=None)
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        reasons.append(f"unreadable file '{item.png_path}': {exc}")
        return VisualVerdict(passed=False, verdict="FAIL",
                             reasons=reasons, actual_sha256=None)

    assert data is not None
    actual = hashlib.sha256(data).hexdigest()
    if len(digest) == 64 and actual.lower() != digest:
        reasons.append(f"sha256 mismatch for '{item.png_path}': "
                       f"expected {digest} actual {actual}")
    if len(data) < 8 or data[:8] != PNG_MAGIC:
        reasons.append(f"not a valid PNG (magic bytes mismatch): {item.png_path}")

    passed = not reasons
    return VisualVerdict(passed=passed, verdict="PASS" if passed else "FAIL",
                         reasons=reasons, actual_sha256=actual)
