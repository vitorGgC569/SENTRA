from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import subprocess
from pathlib import Path

import pytest
from mcp import Client

from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import MCPConfig
from sentra_mcp.server import SentraMCPServer
from sentra_mcp.services.oma import OmaService
from sentra_mcp.services.repository import RepositoryService


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _fixture_repo(tmp_path: Path) -> MCPConfig:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "sentra@example.invalid")
    _git(tmp_path, "config", "user.name", "SENTRA Tests")
    (tmp_path / "sample.py").write_text(
        "def hello():\n    return 'world'\n",
        encoding="utf-8",
        newline="\n",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text(
        "from sample import hello\n\ndef test_hello():\n    assert hello() == 'world'\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")
    return MCPConfig(
        allowed_roots=(tmp_path,),
        audit_log=tmp_path / ".sentra" / "audit.jsonl",
        max_read_bytes=2 * 1024 * 1024,
    )


def test_repository_adapter_uses_gateway_and_registered_tests(tmp_path: Path) -> None:
    config = _fixture_repo(tmp_path)
    service = RepositoryService(config, AuditLogger(config.audit_log))

    async def probe() -> None:
        read = await service.read("sample.py", 1, 20)
        assert "def hello" in read["result"]

        search = await service.search("return 'world'", ".")
        assert "sample.py" in search["result"]

        tree = await service.tree(".", 2)
        assert "sample.py" in tree["result"]

        status = await service.status()
        assert status["result"] == "CLEAN"

        (tmp_path / "sample.py").write_text(
            "def hello():\n    return 'changed'\n",
            encoding="utf-8",
            newline="\n",
        )
        diff = await service.diff("sample.py")
        assert "changed" in diff["result"]

        # Restore the committed behavior before exercising registered pytest.
        _git(tmp_path, "checkout", "--", "sample.py")
        test = await service.test("tests/test_sample.py")
        assert test["passed"] is True
        assert "PASS exit=0" in test["result"].splitlines()[0]

        with pytest.raises(PermissionError):
            await service.read("../outside.txt")

        with pytest.raises(ValueError):
            await service.search("x|y", ".")

    asyncio.run(probe())

    audit = config.audit_log.read_text(encoding="utf-8")
    assert "repository.test" in audit


def test_oma_run_observability_is_confined_and_redacted(tmp_path: Path) -> None:
    config = _fixture_repo(tmp_path)
    audit = AuditLogger(config.audit_log)
    service = OmaService(config, audit)
    run_dir = tmp_path / "runs" / "demo-run"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"status": "RUNNING", "objective": "demo", "token": "secret-value"}),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "A", "password": "hidden"}) + "\n"
        + json.dumps({"event_type": "B"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "handoff.json").write_text(
        json.dumps({"status": "CANDIDATE_READY", "promoted": False, "token": "secret-value"}),
        encoding="utf-8",
    )

    status = service.run_status("demo-run")
    assert status["status"]["token"] == "[REDACTED]"

    events = service.read_events("demo-run", 0, 1)
    assert events["returned"] == 1
    assert events["more"] is True
    assert events["events"][0]["password"] == "[REDACTED]"

    handoff = service.read_handoff("demo-run")
    assert handoff["handoff"]["status"] == "CANDIDATE_READY"
    assert handoff["handoff"]["promoted"] is False

    runs = service.list_runs(10)
    assert any(item["run_id"] == "demo-run" for item in runs["runs"])

    with pytest.raises(ValueError):
        service.run_status("../escape")
    with pytest.raises(ValueError):
        service.read_handoff(".oma")
    with pytest.raises(PermissionError):
        service._safe_file("demo-run", "../../.oma/secret")

    queue_root = tmp_path / ".oma" / "master-queue"
    result = service.queue_status()
    assert result["queue"]["state"] == "ABSENT"
    assert not queue_root.exists()


def test_mcp_sentra_tools_are_observational_and_no_promotion_surface(tmp_path: Path) -> None:
    config = replace(_fixture_repo(tmp_path), tool_surfaces=("all",))

    async def probe() -> None:
        runtime = SentraMCPServer(config)
        async with Client(runtime.mcp) as client:
            result = await client.list_tools()
            names = {tool.name for tool in result.tools}
            expected = {
                "sentra_repo_workspaces",
                "sentra_repo_read",
                "sentra_repo_search",
                "sentra_repo_tree",
                "sentra_repo_symbol",
                "sentra_repo_status",
                "sentra_repo_diff",
                "sentra_repo_test",
                "sentra_oma_health",
                "sentra_oma_runs",
                "sentra_oma_status",
                "sentra_oma_events",
                "sentra_oma_handoff",
                "sentra_oma_queue_status",
                "sentra_oma_reconcile_status",
            }
            assert expected <= names
            assert "sentra_apply_candidate" in names  # sandbox-only candidate application
            assert not any("promote" in name for name in names)
            assert not ({"sentra_apply", "sentra_apply_to_workspace", "sentra_promote_candidate"} & names)

            health = await client.call_tool("sentra_oma_health", {})
            assert health.is_error is False
            assert health.structured_content["data"]["automatic_promotion"] is False

    asyncio.run(probe())


def test_repository_adapter_can_select_multiple_allowlisted_workspaces(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    for root, marker in ((first, "first"), (second, "second")):
        _git(root, "init")
        _git(root, "config", "user.email", "sentra@example.invalid")
        _git(root, "config", "user.name", "SENTRA Tests")
        (root / "marker.txt").write_text(marker + "\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", "baseline")

    config = MCPConfig(
        allowed_roots=(first, second),
        audit_log=tmp_path / "audit.jsonl",
    )
    service = RepositoryService(config, AuditLogger(config.audit_log))

    async def probe() -> None:
        workspaces = service.list_workspaces()["workspaces"]
        assert [item["id"] for item in workspaces] == ["root:0", "root:1"]
        assert workspaces[0]["default"] is True
        assert workspaces[1]["git_repo"] is True

        default_read = await service.read("marker.txt", 1, 5)
        assert "first" in default_read["result"]
        assert default_read["workspace"] == "root:0"
        assert default_read["workspace_id"] == "config:0"

        second_read = await service.read("marker.txt", 1, 5, "root:1")
        assert "second" in second_read["result"]
        assert second_read["workspace"] == "root:1"
        assert second_read["workspace_id"] == "config:1"
        assert Path(second_read["workspace_path"]) == second.resolve()

        by_path = await service.status(str(second.resolve()))
        assert by_path["workspace"] == "root:1"
        assert by_path["workspace_id"] == "config:1"
        assert by_path["result"] == "CLEAN"

        with pytest.raises(PermissionError):
            await service.status(str(tmp_path / "not-allowlisted"))

    asyncio.run(probe())


def test_mcp_repo_tools_expose_optional_workspace_selector(tmp_path: Path) -> None:
    config = _fixture_repo(tmp_path)

    async def probe() -> None:
        runtime = SentraMCPServer(config)
        async with Client(runtime.mcp) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert "sentra_repo_workspaces" in tools
            status_schema = tools["sentra_repo_status"].input_schema
            assert "workspace" in status_schema["properties"]
            assert "workspace" not in status_schema.get("required", [])

            listed = await client.call_tool("sentra_repo_workspaces", {})
            workspaces = listed.structured_content["data"]["workspaces"]
            assert workspaces[0]["id"] == "root:0"
            assert Path(workspaces[0]["path"]) == tmp_path.resolve()

    asyncio.run(probe())


def test_repository_build_pass_parser_accepts_targetless_spacing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _fixture_repo(tmp_path)
    service = RepositoryService(config, AuditLogger(config.audit_log))

    async def fake_execute(*args, **kwargs):
        return (
            "BUILD  PASS exit=0\ncollected tests",
            {"id": "root:0", "workspace_id": "config:0", "alias": "sentra"},
            tmp_path,
        )

    monkeypatch.setattr(service, "_execute", fake_execute)

    async def probe() -> None:
        result = await service.run_registered("BUILD")
        assert result["passed"] is True
        assert result["result"].splitlines()[0] == "BUILD  PASS exit=0"

    asyncio.run(probe())
