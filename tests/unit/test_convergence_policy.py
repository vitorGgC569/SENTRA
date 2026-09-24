from __future__ import annotations

from orchestrator.budgets import TokenBudget
from orchestrator.convergence import ConvergencePolicy


def _eval(policy: ConvergencePolicy, **overrides):
    args = {
        "objective_satisfied": False,
        "dispatched": 1,
        "pending_work": True,
        "ready_work": False,
        "in_flight": False,
        "no_progress_rounds": 0,
        "marginal_gain": None,
        "budget_exhausted": False,
        "speculative_only": False,
        "requires_human": False,
    }
    args.update(overrides)
    return policy.evaluate(**args)


def test_objective_satisfied_stops_even_without_pending_work() -> None:
    policy = ConvergencePolicy(max_rounds=20, no_progress_limit=3)
    decision = _eval(
        policy,
        objective_satisfied=True,
        pending_work=False,
        ready_work=False,
    )
    assert decision.stop is True
    assert decision.code == "OBJECTIVE_SATISFIED"


def test_no_progress_and_dispatch_limits_are_runtime_decisions() -> None:
    policy = ConvergencePolicy(max_rounds=5, no_progress_limit=2)
    no_progress = _eval(policy, no_progress_rounds=2)
    assert no_progress.stop is True
    assert no_progress.code == "NO_PROGRESS"

    dispatch = _eval(policy, dispatched=5, no_progress_rounds=0)
    assert dispatch.stop is True
    assert dispatch.code == "DISPATCH_LIMIT"


def test_convergence_never_stops_siblings_in_flight() -> None:
    policy = ConvergencePolicy(
        max_rounds=1,
        no_progress_limit=1,
        min_marginal_gain=0.5,
        low_gain_patience=1,
        speculative_limit=1,
    )
    decision = _eval(
        policy,
        dispatched=10,
        no_progress_rounds=10,
        marginal_gain=0.0,
        budget_exhausted=True,
        speculative_only=True,
        requires_human=True,
        in_flight=True,
    )
    assert decision.stop is False
    assert decision.code == "CONTINUE"


def test_budget_and_human_boundaries_stop_when_quiescent() -> None:
    budget = ConvergencePolicy(max_rounds=20, no_progress_limit=3)
    d1 = _eval(budget, budget_exhausted=True)
    assert d1.stop is True and d1.code == "BUDGET_EXHAUSTED"

    human = ConvergencePolicy(max_rounds=20, no_progress_limit=3)
    d2 = _eval(human, requires_human=True)
    assert d2.stop is True and d2.code == "HUMAN_DECISION_REQUIRED"


def test_marginal_gain_is_opt_in_and_requires_patience() -> None:
    default = ConvergencePolicy(max_rounds=20, no_progress_limit=5)
    assert _eval(default, marginal_gain=0.0).stop is False

    policy = ConvergencePolicy(
        max_rounds=20,
        no_progress_limit=5,
        min_marginal_gain=0.10,
        low_gain_patience=2,
    )
    assert _eval(policy, marginal_gain=0.05).stop is False
    stopped = _eval(policy, marginal_gain=0.01)
    assert stopped.stop is True
    assert stopped.code == "MARGINAL_GAIN_BELOW_THRESHOLD"

    recovered = ConvergencePolicy(
        max_rounds=20,
        no_progress_limit=5,
        min_marginal_gain=0.10,
        low_gain_patience=2,
    )
    assert _eval(recovered, marginal_gain=0.01).stop is False
    assert _eval(recovered, marginal_gain=0.5).stop is False
    assert recovered.low_gain_rounds == 0


def test_speculative_only_is_opt_in() -> None:
    default = ConvergencePolicy(max_rounds=20, no_progress_limit=5)
    assert _eval(default, speculative_only=True).stop is False

    policy = ConvergencePolicy(
        max_rounds=20,
        no_progress_limit=5,
        speculative_limit=2,
    )
    assert _eval(policy, speculative_only=True).stop is False
    stopped = _eval(policy, speculative_only=True)
    assert stopped.stop is True
    assert stopped.code == "SPECULATIVE_ONLY"


def test_token_budget_remaining_accounts_for_reservations() -> None:
    budget = TokenBudget(master=100, secondary=200)
    budget.register_task("T", 100)
    reservation = budget.reserve("executor", "T", input_bound=20, output_limit=30)
    assert budget.remaining("secondary") == 150
    assert budget.remaining(task_id="T") == 50
    assert budget.exhausted("secondary") is False

    budget.settle(reservation, usage=None, uncertain=True)
    assert budget.remaining("secondary") == 150
    assert budget.remaining(task_id="T") == 50
