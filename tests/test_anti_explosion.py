import pytest
from orchestrator.models import Task
from orchestrator.anti_explosion import (
    AntiExplosionGuard,
    AntiExplosionConfig,
    AntiExplosionError,
)


def test_anti_explosion_budget_limit():
    guard = AntiExplosionGuard(AntiExplosionConfig(global_task_budget=3, enable_deduplication=False))
    t1 = Task(id="T-1", run_id="r", objective="Task 1")
    t2 = Task(id="T-2", run_id="r", objective="Task 2")
    t3 = Task(id="T-3", run_id="r", objective="Task 3")
    t4 = Task(id="T-4", run_id="r", objective="Task 4")

    guard.register_task(t1)
    guard.register_task(t2)
    guard.register_task(t3)

    with pytest.raises(AntiExplosionError, match="Global task budget exceeded"):
        guard.register_task(t4)


def test_anti_explosion_depth_limit():
    guard = AntiExplosionGuard(AntiExplosionConfig(max_depth=2))
    t_ok = Task(id="T-1", run_id="r", objective="Task depth 2", depth=2)
    t_exceeded = Task(id="T-2", run_id="r", objective="Task depth 3", depth=3)

    guard.register_task(t_ok)
    with pytest.raises(AntiExplosionError, match="depth limit exceeded"):
        guard.register_task(t_exceeded)


def test_anti_explosion_branching_limit():
    guard = AntiExplosionGuard(AntiExplosionConfig(branching_factor_limit=2, enable_deduplication=False))
    p = "parent-1"
    c1 = Task(id="C-1", run_id="r", objective="Child 1")
    c2 = Task(id="C-2", run_id="r", objective="Child 2")
    c3 = Task(id="C-3", run_id="r", objective="Child 3")

    guard.register_task(c1, parent_task_id=p)
    guard.register_task(c2, parent_task_id=p)

    with pytest.raises(AntiExplosionError, match="Branching factor limit reached"):
        guard.register_task(c3, parent_task_id=p)


def test_anti_explosion_deduplication():
    guard = AntiExplosionGuard(AntiExplosionConfig(enable_deduplication=True))
    t1 = Task(id="T-1", run_id="r", objective="Implement User Authentication with JWT")
    t2 = Task(id="T-2", run_id="r", objective="implement user authentication with jwt!")

    guard.register_task(t1)
    with pytest.raises(AntiExplosionError, match="Duplicate task rejected"):
        guard.register_task(t2)
