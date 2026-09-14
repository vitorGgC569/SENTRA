"""Frozen pilot contract. Tests production compute_policy/models in isolation."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orchestrator.compute_policy import from_config
from orchestrator.models import Task, ValidatorRole


@pytest.mark.parametrize("value", [5.0, True, False, "5"])
def test_initial_agents_requires_actual_integer(value):
    with pytest.raises(ValueError):
        from_config({"initial_agents": value})


@pytest.mark.parametrize("value", [False, 0, 0.0, "", [], ["invalid"]])
def test_present_escalation_must_be_mapping_or_none(value):
    with pytest.raises(ValueError):
        from_config({"escalation": value})


@pytest.mark.parametrize("value", [True, 1.0, "1", -1])
def test_explicit_role_count_requires_actual_nonnegative_integer(value):
    with pytest.raises(ValueError):
        from_config({"escalation": {"disagreement": {
            "add_roles": ["security"], "add_agents": value}}})


def test_omitted_policy_retains_legacy_behavior():
    assert from_config(None) is None


@pytest.mark.parametrize("escalation", [None, {}])
def test_default_and_none_escalation_remain_valid(escalation):
    policy = from_config({"initial_agents": 5, "escalation": escalation})
    assert policy.agent_count(policy.initial_roles) == 5
    assert len(policy.disagreement_add) == 3


def test_valid_explicit_role_count_and_six_agent_cap():
    policy = from_config({"initial_agents": 5, "max_agents": 6,
        "escalation": {"disagreement": {"add_roles": ["security"], "add_agents": 1}}})
    grown = policy.expand(policy.initial_roles, policy.disagreement_add)
    assert policy.agent_count(grown) == 6
    assert grown[-1] == ValidatorRole.SECURITY
    assert policy.expand(grown, policy.disagreement_add) == grown


def test_large_add_agents_is_still_a_bound_on_existing_standby_roles():
    policy = from_config({"escalation": {"disagreement": {"add_agents": 10}}})
    assert len(policy.disagreement_add) == 3


def test_zero_add_agents_remains_valid():
    policy = from_config({"escalation": {"disagreement": {"add_agents": 0}}})
    assert policy.disagreement_add == []


def test_initial_roles_cannot_exceed_max_agents():
    with pytest.raises(ValueError):
        from_config({"max_agents": 5, "initial_roles": ["logic", "requirements", "adversarial", "security"]})


def test_role_aliases_and_critical_escalation_are_preserved():
    policy = from_config({"max_agents": 6, "escalation": {"critical_task": {"add_roles": ["edge"]}}})
    task = Task(id="T", run_id="R", objective="critical", risk="CRITICAL")
    assert policy.agent_count(policy.initial_for_task(task)) == 6
    assert ValidatorRole.EDGE_CASES in policy.initial_for_task(task)


def test_input_configuration_is_not_mutated():
    config = {"initial_agents": 5, "initial_roles": ["logic", "logic", "requirements", "adversarial"],
              "escalation": {"disagreement": {"add_agents": 2}}, "max_agents": 6}
    before = copy.deepcopy(config)
    from_config(config)
    assert config == before
