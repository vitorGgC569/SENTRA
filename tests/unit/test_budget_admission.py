import copy

import pytest

from orchestrator.budgets import BudgetExceeded, TokenBudget
from orchestrator.models import TokenUsage


def test_concurrent_reservations_and_task_caps():
    budget = TokenBudget(100,100)
    budget.register_task("T",70)
    a = budget.reserve("executor","T",20,20)
    with pytest.raises(BudgetExceeded, match="task"):
        budget.reserve("validator.logic","T",20,20)
    b = budget.reserve("executor","U",30,30)
    with pytest.raises(BudgetExceeded, match="secondary"):
        budget.reserve("executor","V",1,1)
    budget.settle(a,TokenUsage(input_tokens=10,output_tokens=10,accounting="provider"))
    budget.settle(b,uncertain=True)
    assert budget.used["secondary"] == 80
    assert budget.accounting == {"provider":20,"estimated":0,"uncertain":60}


def test_estimate_input_tokens_uses_token_scale_not_bytes():
    from orchestrator.budgets import estimate_input_tokens
    # 400 chars ASCII ~= 100 tokens (convenção len//4 do projeto), não 400+.
    got = estimate_input_tokens([{"content": "x" * 400}])
    assert got <= 150
    assert got >= 130
    assert estimate_input_tokens([]) >= 1


def test_restart_charges_uncertain_once_and_cannot_raise_limits():
    saved = []
    save = lambda state: saved.append(copy.deepcopy(state))
    budget = TokenBudget(100,100,save=save)
    budget.reserve("executor","T",20,30)
    resumed = TokenBudget(500,500,save=save,state=saved[-1])
    assert resumed.used["secondary"] == 50
    assert resumed.limits["secondary"] == 100
    again = TokenBudget(100,100,state=saved[-1])
    assert again.used["secondary"] == 50 and not again.reservations
