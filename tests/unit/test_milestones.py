"""WS4: validacao que compoe em escala — testes reais, sem rede, sem simulacao."""
import hashlib
import struct
import sys
import time
import zlib

from orchestrator.milestones import (
    VisualEvidence,
    check_budgets,
    evaluate_milestone,
    evaluate_visual_evidence,
    validate_contracts,
)
from orchestrator.models import Task, TaskStatus, ValidationReport


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _task(tid, provides=None, requires=None, status=TaskStatus.COMPLETED, evidence=None):
    meta = {}
    if provides is not None:
        meta["provides"] = provides
    if requires is not None:
        meta["requires"] = requires
    if evidence is not None:
        meta["evidence"] = evidence
    task = Task(id=tid, run_id="r-ws4", objective=f"obj {tid}", metadata=meta)
    task.status = status
    return task


def _report(score=None, confidence=0.99, status="APPROVED", role="v", ran=True):
    return ValidationReport(validator_role=role, status=status,
                            confidence=confidence, score=score, ran=ran)


def _write_minimal_png(path):
    """Write a real decodable 1x1 PNG using stdlib only."""
    def chunk(ctype, payload):
        body = ctype + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    path.write_bytes(png)
    return png


# ---------------------------------------------------------------------------
# a) contratos entre tarefas
# ---------------------------------------------------------------------------

def test_contracts_ok_matching_version():
    tasks = [
        _task("A", provides=[{"name": "schema", "schema_version": "v2"}]),
        _task("B", requires=[{"name": "schema", "schema_version": "v2"}]),
    ]
    assert validate_contracts(tasks) == []


def test_contracts_wildcard_requires_accepts_any_version():
    tasks = [
        _task("A", provides=[{"name": "schema", "schema_version": "v7"}]),
        _task("B", requires=[{"name": "schema"}]),
    ]
    assert validate_contracts(tasks) == []


def test_contracts_missing_producer():
    tasks = [_task("B", requires=[{"name": "ghost", "schema_version": "v1"}])]
    violations = validate_contracts(tasks)
    assert len(violations) == 1
    assert violations[0].kind == "missing_producer"
    assert violations[0].consumer_id == "B"
    assert violations[0].artifact == "ghost"


def test_contracts_version_mismatch():
    tasks = [
        _task("A", provides=[{"name": "schema", "schema_version": "v1"}]),
        _task("B", requires=[{"name": "schema", "schema_version": "v2"}]),
    ]
    violations = validate_contracts(tasks)
    assert len(violations) == 1
    assert violations[0].kind == "version_mismatch"
    assert violations[0].required_version == "v2"


def test_contracts_version_match_any_producer_passes():
    tasks = [
        _task("A", provides=[{"name": "schema", "schema_version": "v1"}]),
        _task("A2", provides=[{"name": "schema", "schema_version": "v2"}]),
        _task("B", requires=[{"name": "schema", "schema_version": "v2"}]),
    ]
    assert validate_contracts(tasks) == []


def test_contracts_provision_cycle_two_nodes():
    tasks = [
        _task("A", provides=[{"name": "x", "schema_version": "v1"}],
              requires=[{"name": "y", "schema_version": "v1"}]),
        _task("B", provides=[{"name": "y", "schema_version": "v1"}],
              requires=[{"name": "x", "schema_version": "v1"}]),
    ]
    violations = validate_contracts(tasks)
    cycles = [v for v in violations if v.kind == "provision_cycle"]
    assert len(cycles) == 1
    assert "A" in cycles[0].detail and "B" in cycles[0].detail


def test_contracts_provision_cycle_three_nodes():
    tasks = [
        _task("A", provides=[{"name": "a"}], requires=[{"name": "c"}]),
        _task("B", provides=[{"name": "b"}], requires=[{"name": "a"}]),
        _task("C", provides=[{"name": "c"}], requires=[{"name": "b"}]),
    ]
    kinds = [v.kind for v in validate_contracts(tasks)]
    assert "provision_cycle" in kinds


def test_contracts_acyclic_chain_passes():
    tasks = [
        _task("A", provides=[{"name": "a"}]),
        _task("B", provides=[{"name": "b"}], requires=[{"name": "a"}]),
        _task("C", requires=[{"name": "b"}]),
    ]
    assert validate_contracts(tasks) == []


def test_contracts_malformed_entry_reported_not_raised():
    tasks = [_task("A", provides=[{"schema_version": "v1"}])]
    violations = validate_contracts(tasks)
    assert len(violations) == 1
    assert violations[0].kind == "malformed_contract"


def test_contracts_accepts_mapping_and_empty():
    tasks = {"A": _task("A", provides=[{"name": "x", "schema_version": "v1"}])}
    assert validate_contracts(tasks) == []
    assert validate_contracts([]) == []
    assert validate_contracts({}) == []


# ---------------------------------------------------------------------------
# b) gates de marco
# ---------------------------------------------------------------------------

def _milestone_tasks():
    return {
        "T1": _task("T1", evidence=["report.html"]),
        "T2": _task("T2", evidence=["report.html"]),
    }


def test_milestone_pass():
    tasks = _milestone_tasks()
    validations = {"T1": [_report(score=9.5, role="a"), _report(score=10.0, role="b")],
                   "T2": [_report(score=9.8, role="a"), _report(score=9.6, role="b")]}
    verdict = evaluate_milestone("M1", ["T1", "T2"], tasks, validations,
                                 required_evidence=("report.html",))
    assert verdict.passed is True
    assert verdict.verdict == "PASS"
    assert verdict.reasons == []
    assert verdict.completed == 2 and verdict.total == 2
    assert verdict.min_score == 9.5


def test_milestone_fail_incomplete_task():
    tasks = {"T1": _task("T1", status=TaskStatus.RUNNING),
             "T2": _task("T2")}
    validations = {"T1": [_report(score=10.0, role="a")],
                   "T2": [_report(score=10.0, role="a")]}
    verdict = evaluate_milestone("M1", ["T1", "T2"], tasks, validations)
    assert verdict.passed is False
    assert any("incomplete task 'T1'" in r for r in verdict.reasons)


def test_milestone_fail_below_bar():
    tasks = _milestone_tasks()
    validations = {"T1": [_report(score=9.6, role="a"), _report(score=9.4, role="b")],
                   "T2": [_report(score=10.0, role="a")]}
    verdict = evaluate_milestone("M1", ["T1", "T2"], tasks, validations)
    assert verdict.passed is False
    assert any("below bar" in r and "T1" in r for r in verdict.reasons)
    assert any("9.40" in r and "9.50" in r for r in verdict.reasons)


def test_milestone_fail_missing_validation_and_unknown_and_empty():
    tasks = _milestone_tasks()
    verdict = evaluate_milestone("M1", ["T1"], tasks, {})
    assert verdict.passed is False
    assert any("missing validation" in r for r in verdict.reasons)
    verdict = evaluate_milestone("M1", ["NOPE"], tasks, {})
    assert verdict.passed is False
    assert any("unknown task" in r for r in verdict.reasons)
    verdict = evaluate_milestone("M1", [], tasks, {})
    assert verdict.passed is False
    assert any("empty milestone" in r for r in verdict.reasons)


def test_milestone_fail_missing_evidence():
    tasks = {"T1": _task("T1", evidence=["other.html"])}
    validations = {"T1": [_report(score=9.9, role="a")]}
    verdict = evaluate_milestone("M1", ["T1"], tasks, validations,
                                 required_evidence=("report.html",))
    assert verdict.passed is False
    assert any("missing evidence 'report.html'" in r for r in verdict.reasons)


def test_milestone_abstained_reports_are_not_evidence():
    tasks = _milestone_tasks()
    validations = {"T1": [_report(score=10.0, role="a", ran=False)],
                   "T2": [_report(score=10.0, role="a")]}
    verdict = evaluate_milestone("M1", ["T1", "T2"], tasks, validations)
    assert verdict.passed is False
    assert any("missing validation for task 'T1'" in r for r in verdict.reasons)


def test_milestone_legacy_confidence_fallback_and_custom_bar():
    tasks = {"T1": _task("T1")}
    validations = {"T1": [_report(score=None, confidence=0.96, role="a"),
                          _report(score=None, confidence=0.97, role="b")]}
    verdict = evaluate_milestone("M1", ["T1"], tasks, validations)
    assert verdict.passed is True  # min 9.6 >= 9.5
    verdict = evaluate_milestone("M1", ["T1"], tasks, validations, min_bar=9.7)
    assert verdict.passed is False


def test_milestone_accepts_sequence_tasks_and_numeric_scores():
    tasks = [_task("T1"), _task("T2")]
    verdict = evaluate_milestone("M1", ["T1", "T2"], tasks,
                                 {"T1": 9.5, "T2": 9.9})
    assert verdict.passed is True
    assert verdict.min_score == 9.5


# ---------------------------------------------------------------------------
# c) budgets por marco
# ---------------------------------------------------------------------------

def test_budgets_pass_small_files(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    violations = check_budgets(tmp_path, {"max_file_lines": 100,
                                          "max_file_bytes": 10000})
    assert violations == []


def test_budgets_file_lines_violation(tmp_path):
    (tmp_path / "big.py").write_text("x\n" * 50, encoding="utf-8")
    violations = check_budgets(tmp_path, {"max_file_lines": 10})
    assert len(violations) == 1
    assert violations[0].kind == "file_lines"
    assert violations[0].actual == 50.0
    assert "big.py" in (violations[0].path or "")


def test_budgets_file_bytes_violation(tmp_path):
    (tmp_path / "blob.bin").write_bytes(b"0123456789" * 100)
    violations = check_budgets(tmp_path, {"max_file_bytes": 10})
    assert any(v.kind == "file_bytes" for v in violations)


def test_budgets_test_seconds_violation_real_command(tmp_path):
    cmd = [sys.executable, "-c", "import time; time.sleep(0.5)"]
    violations = check_budgets(tmp_path, {"max_test_seconds": 0.05},
                               test_command=cmd, timeout=10)
    assert len(violations) == 1
    assert violations[0].kind == "test_seconds"
    assert violations[0].actual is not None and violations[0].actual >= 0.4


def test_budgets_test_command_fast_passes(tmp_path):
    cmd = [sys.executable, "-c", "pass"]
    violations = check_budgets(tmp_path, {"max_test_seconds": 30},
                               test_command=cmd, timeout=30)
    assert violations == []


def test_budgets_test_timeout_real(tmp_path):
    cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
    start = time.monotonic()
    violations = check_budgets(tmp_path, {"max_test_seconds": 60},
                               test_command=cmd, timeout=1)
    elapsed = time.monotonic() - start
    assert any(v.kind == "test_timeout" for v in violations)
    assert elapsed < 5


def test_budgets_missing_dir(tmp_path):
    violations = check_budgets(tmp_path / "nope", {"max_file_lines": 5})
    assert len(violations) == 1
    assert violations[0].kind == "missing_dir"


def test_budgets_invalid_config_raises(tmp_path):
    try:
        check_budgets(tmp_path, {"max_file_lines": -1})
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


# ---------------------------------------------------------------------------
# d) gate visual honesto — integridade, nao julgamento
# ---------------------------------------------------------------------------

def _evidence_for(path, data, viewpoint="front", run_id="run-1", task_id="T1"):
    return VisualEvidence(png_path=path.name, viewpoint=viewpoint,
                          sha256=hashlib.sha256(data).hexdigest(),
                          captured_at=time.time(), run_id=run_id, task_id=task_id)


def test_visual_valid(tmp_path):
    png = _write_minimal_png(tmp_path / "shot.png")
    verdict = evaluate_visual_evidence(_evidence_for(tmp_path / "shot.png", png), tmp_path)
    assert verdict.passed is True
    assert verdict.verdict == "PASS"
    assert verdict.actual_sha256 == hashlib.sha256(png).hexdigest()


def test_visual_missing_file(tmp_path):
    ev = VisualEvidence(png_path="absent.png", viewpoint="front",
                        sha256="0" * 64, captured_at=time.time(),
                        run_id="run-1", task_id="T1")
    verdict = evaluate_visual_evidence(ev, tmp_path)
    assert verdict.passed is False
    assert any("missing file" in r for r in verdict.reasons)


def test_visual_corrupted_not_png(tmp_path):
    data = b"this is not a png file"
    (tmp_path / "shot.png").write_bytes(data)
    ev = _evidence_for(tmp_path / "shot.png", data)
    verdict = evaluate_visual_evidence(ev, tmp_path)
    assert verdict.passed is False
    assert any("magic bytes" in r for r in verdict.reasons)


def test_visual_divergent_sha(tmp_path):
    png = _write_minimal_png(tmp_path / "shot.png")
    ev = _evidence_for(tmp_path / "shot.png", png)
    ev.sha256 = "1" * 64
    verdict = evaluate_visual_evidence(ev, tmp_path)
    assert verdict.passed is False
    assert any("sha256 mismatch" in r for r in verdict.reasons)
    assert verdict.actual_sha256 == hashlib.sha256(png).hexdigest()


def test_visual_incomplete_metadata(tmp_path):
    png = _write_minimal_png(tmp_path / "shot.png")
    ev = _evidence_for(tmp_path / "shot.png", png, viewpoint="", run_id="")
    verdict = evaluate_visual_evidence(ev, tmp_path)
    assert verdict.passed is False
    assert any("viewpoint" in r for r in verdict.reasons)
    assert any("run_id" in r for r in verdict.reasons)


def test_visual_docstring_discloses_no_quality_judgment():
    doc = (evaluate_visual_evidence.__doc__ or "")
    assert "NOT VISUAL QUALITY JUDGMENT" in doc
    assert "OPERATOR" in doc
