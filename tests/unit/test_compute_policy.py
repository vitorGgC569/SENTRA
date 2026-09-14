"""Compute policy: start with 5, escalate only with cause, bounded."""
import pytest

from orchestrator.compute_policy import (
    ComputePolicy, from_config, parse_roles)
from orchestrator.models import Task, TaskPriority, ValidatorRole


def test_from_config_none_keeps_legacy_behavior():
    assert from_config(None) is None


def test_from_config_user_shape_five_agents():
    p = from_config({
        "initial_agents": 5,
        "initial_roles": ["logic", "requirements", "adversarial"],
        "escalation": {
            "disagreement": {"add_agents": 3},
            "low_confidence": {"add_agents": 5},
            "critical_task": {"add_agents": 10},
        },
        "max_agents": 500,
    })
    assert [r.value for r in p.initial_roles] == [
        "validator.logic", "validator.requirements", "validator.adversarial"]
    assert p.agent_count(p.initial_roles) == 5
    assert p.disagreement_add == [ValidatorRole.EDGE_CASES, ValidatorRole.SECURITY,
                                  ValidatorRole.PERFORMANCE]


def test_initial_agents_must_match_roles_plus_two():
    with pytest.raises(ValueError, match="initial_agents"):
        from_config({"initial_agents": 6, "initial_roles": ["logic"]})


def test_unknown_role_fails_closed():
    with pytest.raises(ValueError, match="unknown validator role"):
        from_config({"initial_roles": ["telepathy"]})


def test_initial_roles_cannot_exceed_cap():
    with pytest.raises(ValueError, match="exceed max_agents"):
        from_config({"max_agents": 5, "initial_roles": ["logic", "requirements", "adversarial", "security"]})


@pytest.mark.parametrize("config", [
    {"initial_roles": "logic"}, {"max_agents": True},
    {"escalation": {"disagreement": {"add_agents": True}}},
])
def test_policy_rejects_wrong_types(config):
    with pytest.raises(ValueError):
        from_config(config)


def test_expand_disagreement_adds_standby_once_and_caps():
    p = ComputePolicy(max_agents=8)  # 8 agentes no máximo
    active = list(p.initial_roles)
    grown = p.expand(active, p.disagreement_add)
    assert len(grown) == 6  # 3 + 3 standby (cap: 8 agentes = 6 validators)
    grown2 = p.expand(grown, p.disagreement_add)
    assert grown2 == grown  # idempotente, sem duplicatas


def test_initial_for_task_adds_critical_roles_only_when_critical():
    p = ComputePolicy()
    plain = Task(id="T-1", run_id="r", objective="x")
    assert p.initial_for_task(plain) == p.initial_roles
    crit = Task(id="T-2", run_id="r", objective="x", risk="CRITICAL")
    got = p.initial_for_task(crit)
    assert ValidatorRole.SECURITY in got and len(got) > len(p.initial_roles)
    hp = Task(id="T-3", run_id="r", objective="x", priority=TaskPriority.CRITICAL)
    assert len(p.initial_for_task(hp)) > len(p.initial_roles)


def test_expand_pure_no_side_effects():
    p = ComputePolicy()
    active = list(p.initial_roles)
    snap = list(active)
    p.expand(active, p.disagreement_add)
    assert active == snap


def _engine_with_policy(tmp_path, policy):
    import git
    from orchestrator.agents.router import ModelRouter
    from orchestrator.engine import OMAEngine
    from orchestrator.providers.mock_provider import MockProvider
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    try:
        git.Repo.init(ws)
    except Exception:
        pass
    router = ModelRouter(providers={"primary": MockProvider(model_name="m")},
                         primary_provider_name="primary", fallback_provider_name=None)
    return OMAEngine(run_id="pol", objective="o", workspace_path=ws, router=router,
                     compute_policy=policy)


def test_engine_expands_on_disputed_and_low_confidence(tmp_path):
    from orchestrator.models import Task, ValidationReport
    policy = from_config({"initial_roles": ["logic", "requirements", "adversarial"],
                          "max_agents": 500})
    eng = _engine_with_policy(tmp_path, policy)
    task = Task(id="T-1", run_id="pol", objective="x")
    assert [r.value for r in eng.compute_policy.initial_for_task(task)] == [
        "validator.logic", "validator.requirements", "validator.adversarial"]
    eng._task_roles["T-1"] = list(policy.initial_roles)
    disputed = [ValidationReport(validator_role="validator.logic", status="DISPUTED"),
                ValidationReport(validator_role="validator.requirements", status="APPROVED")]
    grown = eng._expand_validators(task, disputed, "anything")
    assert len(grown) == 6  # +edge/security/performance
    eng._task_roles["T-1"] = list(policy.initial_roles)
    grown2 = eng._expand_validators(task, [], "Confidence below threshold: 0.10 < 0.75")
    assert len(grown2) == 6
    eng._task_roles["T-1"] = list(policy.initial_roles)
    same = eng._expand_validators(task, [], "Insufficient approvals: 0/2 approvals.")
    assert same == policy.initial_roles  # sem causa, sem expansão


def test_engine_options_plumbs_compute_policy(tmp_path):
    from orchestrator.configuration import engine_options
    opts = engine_options({"oma": {"compute_policy": {
        "initial_agents": 5, "initial_roles": ["logic", "requirements", "adversarial"],
        "escalation": {"disagreement": {"add_agents": 3}},
        "max_agents": 500}, "fixed_conversations": True, "inter_call_delay_s": 30}})
    assert opts["fixed_conversations"] is True
    assert opts["inter_call_delay_s"] == 30.0
    assert opts["compute_policy"].agent_count(opts["compute_policy"].initial_roles) == 5
