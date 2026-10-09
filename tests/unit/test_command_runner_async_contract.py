from __future__ import annotations

import sys

import pytest

from repository.gateway import execution_deadline
from workspace.command_runner import CommandRunner


def test_gateway_deadlines_match_registered_execution_contract():
    assert execution_deadline("BUILD") is None
    assert execution_deadline("BENCH") is None
    assert execution_deadline("TEST") == 605
    assert execution_deadline("LINT") == 605
    assert execution_deadline("TYPECHECK") == 605
    assert execution_deadline("R") == 60


@pytest.mark.asyncio
async def test_command_runner_allows_explicit_no_deadline(tmp_path):
    runner = CommandRunner(tmp_path)
    result = await runner.run_argv(
        [sys.executable, "-c", "import time; time.sleep(0.05); print('ok')"],
        timeout=None,
    )
    assert result["passed"] is True
    assert "ok" in result["stdout"]


@pytest.mark.asyncio
async def test_command_runner_rejects_nonpositive_finite_timeout(tmp_path):
    runner = CommandRunner(tmp_path)
    with pytest.raises(ValueError, match="positive timeout or None"):
        await runner.run_argv([sys.executable, "-c", "print('x')"], timeout=0)


@pytest.mark.asyncio
async def test_registered_build_has_no_artificial_deadline(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from repository.registry import ExecutionCommand

    observed = {}

    class FakeRunner:
        async def run_command(self, command, timeout=120):
            observed["command"] = command
            observed["timeout"] = timeout
            return {
                "passed": True,
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
            }

    monkeypatch.setattr(
        "workspace.docker_runner.create_runner",
        lambda *args, **kwargs: FakeRunner(),
    )
    directive = SimpleNamespace(raw="[[BUILD]]", operation="BUILD", args=[])
    context = SimpleNamespace(
        session=SimpleNamespace(repository_root=tmp_path),
        gateway=SimpleNamespace(profiles=None, execution=None),
    )

    result = await ExecutionCommand().execute(directive, context)

    assert observed == {"command": "[[BUILD]]", "timeout": None}
    assert result.startswith("BUILD  PASS exit=0")


@pytest.mark.asyncio
async def test_registered_bench_has_no_artificial_deadline(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from repository.registry import ExecutionCommand

    observed = {}

    class FakeRunner:
        async def run_command(self, command, timeout=120):
            observed["command"] = command
            observed["timeout"] = timeout
            return {
                "passed": True,
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
            }

    monkeypatch.setattr(
        "workspace.docker_runner.create_runner",
        lambda *args, **kwargs: FakeRunner(),
    )
    directive = SimpleNamespace(raw="[[BENCH]]", operation="BENCH", args=[])
    context = SimpleNamespace(
        session=SimpleNamespace(repository_root=tmp_path),
        gateway=SimpleNamespace(profiles=None, execution=None),
    )

    result = await ExecutionCommand().execute(directive, context)

    assert observed == {"command": "[[BENCH]]", "timeout": None}
    assert result.startswith("BENCH  PASS exit=0")
