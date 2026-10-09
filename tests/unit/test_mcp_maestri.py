from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sentra_mcp.config import MCPConfig
from sentra_mcp.services.maestri import MaestriService, _MaestriRuntime


def _runtime(tmp_path: Path) -> _MaestriRuntime:
    return _MaestriRuntime(
        cli="maestri.exe",
        pipe=r"\\.\pipe\maestri-test",
        workspace_id="ws-1",
        workspace_name="SENTRA",
        workspace_path=str(tmp_path),
        terminal_id="manager-1",
        terminal_name="SENTRA",
        terminal_status="running",
    )


def _snapshot(tmp_path: Path) -> dict:
    return {
        "workspace": {
            "id": "ws-1",
            "name": "SENTRA",
            "working_directory": str(tmp_path),
        },
        "terminals": [
            {
                "id": "manager-1",
                "name": "SENTRA",
                "agent_type": "custom",
                "command": r".\sentra-cli.cmd",
                "status": "running",
                "is_manager": True,
                "working_directory": str(tmp_path),
            },
            {
                "id": "worker-1",
                "name": "Worker",
                "agent_type": "custom",
                "command": r".\sentra-cli.cmd",
                "status": "running",
                "is_manager": False,
                "working_directory": str(tmp_path),
            },
        ],
        "terminal_count": 2,
    }


def test_select_workspace_prefers_active_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / ".maestri"
    workspaces = state / "workspaces"
    for wid, name in (("ws-old", "Old"), ("ws-active", "SENTRA")):
        root = workspaces / wid
        root.mkdir(parents=True)
        (root / "workspace.json").write_text(
            json.dumps({
                "payload": {
                    "id": wid,
                    "name": name,
                    "workingDirectory": str(tmp_path),
                    "nodes": [],
                    "lastOpenedAt": (
                        "2026-10-01T10:00:00Z"
                        if wid == "ws-old"
                        else "2026-10-01T11:00:00Z"
                    ),
                }
            }),
            encoding="utf-8",
        )
    state.mkdir(exist_ok=True)
    (state / "app-state.json").write_text(
        json.dumps({"payload": {"activeWorkspaceId": "ws-active"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        MaestriService,
        "_state_root",
        classmethod(lambda cls: state),
    )

    _path, payload = MaestriService._select_workspace(None)

    assert payload["id"] == "ws-active"
    assert payload["name"] == "SENTRA"


def test_recruit_is_idempotent_for_existing_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MaestriService(MCPConfig())
    runtime = _runtime(tmp_path)
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(service, "_discover", lambda workspace: runtime)
    monkeypatch.setattr(
        service,
        "_snapshot",
        lambda workspace, runtime=None: snapshot,
    )
    runner = MagicMock()
    monkeypatch.setattr(service, "_run", runner)

    result = service.execute(
        "recruit",
        owner="session:test",
        workspace="SENTRA",
        name="Worker",
    )

    assert result["recruited"] is False
    assert result["idempotent_replay"] is True
    runner.assert_not_called()


def test_send_submits_prompt_with_enter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MaestriService(MCPConfig())
    runtime = _runtime(tmp_path)
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(service, "_discover", lambda workspace: runtime)
    monkeypatch.setattr(
        service,
        "_snapshot",
        lambda workspace, runtime=None: snapshot,
    )
    runner = MagicMock(
        return_value={
            "ok": True,
            "exit_code": 0,
            "stdout": "Sent.",
            "stderr": "",
        }
    )
    monkeypatch.setattr(service, "_run", runner)

    result = service.execute(
        "send",
        owner="session:test",
        workspace="SENTRA",
        name="Worker",
        prompt="hello\nworld",
    )

    assert result["submitted"] is True
    assert runner.call_count == 2
    first = runner.call_args_list[0].args[1]
    second = runner.call_args_list[1].args[1]
    assert first == ["ask", "Worker", "--raw", r"hello\nworld"]
    assert second == ["ask", "Worker", "--raw", r"\n"]


def test_dismiss_manager_requires_explicit_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MaestriService(MCPConfig())
    runtime = _runtime(tmp_path)
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(service, "_discover", lambda workspace: runtime)
    monkeypatch.setattr(
        service,
        "_snapshot",
        lambda workspace, runtime=None: snapshot,
    )

    with pytest.raises(PermissionError, match="manager"):
        service.execute(
            "dismiss",
            owner="session:test",
            workspace="SENTRA",
            name="SENTRA",
            confirm=True,
        )
