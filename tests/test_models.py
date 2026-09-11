from orchestrator.models import (
    Candidate,
    CandidatePackage,
    Finding,
    Evidence,
    Severity,
    Task,
    TaskPriority,
    TaskStatus,
    TokenUsage,
    ValidationReport,
)


def test_task_serialization():
    task = Task(
        id="T-10",
        run_id="run-123",
        objective="Implement feature",
        description="Detailed description",
        dependencies=["T-01"],
        priority=TaskPriority.HIGH,
        risk="MEDIUM",
    )
    d = task.to_dict()
    assert d["priority"] == "HIGH"
    assert d["dependencies"] == ["T-01"]

    restored = Task.from_dict(d)
    assert restored.id == task.id
    assert restored.priority == TaskPriority.HIGH


def test_candidate_serialization():
    cand = Candidate(
        candidate_id="cand_1",
        task_id="T-10",
        version=1,
        summary="Initial patch",
        patch="--- a/file.py\n+++ b/file.py\n",
        validation_commands=["pytest tests/"],
    )
    d = cand.to_dict()
    restored = Candidate.from_dict(d)
    assert restored.candidate_id == "cand_1"
    assert restored.patch == cand.patch


def test_validation_report_critical_findings():
    f1 = Finding(description="Minor typo", severity=Severity.MINOR)
    f2 = Finding(description="SQL injection vulnerability", severity=Severity.CRITICAL)
    report = ValidationReport(
        validator_role="validator.security",
        findings=[f1, f2],
        status="REJECTED",
    )
    assert report.has_critical_findings() is True


def test_token_usage_aggregation():
    t1 = TokenUsage(input_tokens=100, output_tokens=50, model="m1", estimated_cost=0.01)
    t2 = TokenUsage(input_tokens=200, output_tokens=100, model="m1", estimated_cost=0.02)
    tot = t1.add(t2)
    assert tot.input_tokens == 300
    assert tot.output_tokens == 150
    assert round(tot.estimated_cost, 4) == 0.03
