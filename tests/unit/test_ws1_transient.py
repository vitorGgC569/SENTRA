"""WS1 unit coverage: transient classification and operator configuration."""
import pytest

from orchestrator.engine import classify_error, is_transient_error


@pytest.mark.parametrize("msg", [
    "STALE_CONVERSATION: conversation did not change after new_chat",
    "[TIMEOUT] provider exceeded deadline",
    "provider timed out after 30s",
    "DELIVERY_EXPIRED: execution uncertain; not automatically resent",
    "DELIVERY_UNCERTAIN: ambiguous browser state",
    "SUBMISSION_UNCERTAIN: send unconfirmed",
    "[CONVERSATION_BLOCKED] seat requires reconciliation",
    "IN_FLIGHT intent already persisted",
    "LEASE_LOST during relay poll",
    "LEASE_EXPIRED before ack",
    "TAB_STALE after navigation",
])
def test_transient_markers_classified_transient(msg):
    assert is_transient_error(msg) is True
    assert classify_error(msg) == "TRANSIENT"


@pytest.mark.parametrize("msg", [
    "[CONTEXT_BUDGET] prompt exceeds 20000 characters; no text was sent",
    "PATCH_SYNTAX: hunk counts do not match",
    "Below release threshold: min critic score 8.00 < 9.50",
    "Master rejected: needs more work",
    "STALE_BASE: replan against updated integration workspace",
    "BUDGET_EXCEEDED: task token admission budget exhausted",
    "planner provider failed",
    # Bare "uncertain" prose is NOT a retry marker: real uncertain-delivery
    # outcomes carry retry_safe=False in metadata, meaning the operator
    # reconciles instead of the engine auto-resending. Only the explicit
    # DELIVERY_UNCERTAIN / SUBMISSION_UNCERTAIN markers retry.
    "UNCERTAIN delivery, retry_safe False",
    "QUALITY: verdict uncertain, needs repair",
    "",
])
def test_permanent_errors_stay_permanent(msg):
    assert is_transient_error(msg) is False
    assert classify_error(msg) == "PERMANENT"


def test_engine_options_transient_defaults_and_validation():
    from orchestrator.configuration import engine_options
    opts = engine_options({"oma": {}})
    assert opts["transient_max_retries"] == 3
    assert opts["transient_backoff_base_s"] == 30.0
    opts = engine_options({"oma": {"transient_max_retries": 0, "transient_backoff_base_s": 0}})
    assert opts["transient_max_retries"] == 0
    with pytest.raises(ValueError, match="transient_max_retries"):
        engine_options({"oma": {"transient_max_retries": 11}})
    with pytest.raises(ValueError, match="transient_backoff_base_s"):
        engine_options({"oma": {"transient_backoff_base_s": 601}})


@pytest.mark.asyncio
async def test_queue_task_error_map_reports_per_task():
    from orchestrator.models import Task
    from orchestrator.queue import PriorityTaskQueue
    q = PriorityTaskQueue()
    await q.add_task(Task(id="A", run_id="r", objective="a", max_retries=0))
    await q.add_task(Task(id="B", run_id="r", objective="b"))
    a = await q.pop_ready_task()
    assert await q.mark_failed(a.id, "boom permanent", retryable=True) is False
    errors = q.task_error_map()
    assert errors["A"] == "boom permanent"
    assert "B" not in errors
    assert q.escalated_count == 0


def test_bare_uncertain_word_is_not_transient():
    """Regression: generic 'uncertain' wording (e.g. a quality verdict) must
    take the repair path, not burn transient retries. Only the explicit
    DELIVERY_UNCERTAIN / SUBMISSION_UNCERTAIN markers retry."""
    from orchestrator.engine import classify_error
    assert classify_error("QUALITY: verdict uncertain, needs repair") == "PERMANENT"
    assert classify_error("[MODEL_ERROR] DELIVERY_UNCERTAIN: state unknown") == "TRANSIENT"
    assert classify_error("[MODEL_ERROR] SUBMISSION_UNCERTAIN: not confirmed") == "TRANSIENT"


def test_plan_initial_tasks_runs_contract_check_and_memory_brief():
    """Wiring: contract-less plans pass through; memory brief is fail-open."""
    from orchestrator.engine import OMAEngine
    from orchestrator.milestones import validate_contracts
    from orchestrator.models import Task
    assert validate_contracts([]) == []
    assert validate_contracts([Task(id="A", run_id="r", objective="a")]) == []
    eng = OMAEngine.__new__(OMAEngine)
    eng.workspace_path = __import__("pathlib").Path(".")
    eng.objective = "test objective"
    assert eng._program_memory_brief() == ""
