from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentra_mcp.services.authorization import AuthorizationService
from sentra_mcp.services.governance import GovernanceService
from sentra_mcp.services.plugin_host import PluginWorkerHost


class FakeProcesses:
    def __init__(self) -> None:
        self.stdout = bytearray()
        self.running = True
        self.started = []
        self.terminated = []

    def start_process(self, command, owner, **kwargs):
        self.started.append((command, owner, kwargs))
        return {
            "session_id": "proc-1",
            "run_id": kwargs.get("run_id") or "run-plugin",
            "operation_id": "op-plugin",
        }

    def interact_with_process(self, session_id: str, owner: str, stdin: str):
        request = json.loads(stdin.strip())
        method = request["method"]
        if method == "sentra.handshake":
            result = {
                "protocol_version": 1,
                "name": "demo",
                "version": "1.0.0",
                "capabilities": ["read", "write"],
                "methods": [
                    {"name": "read_status", "capability": "read"},
                    {"name": "mutate", "capability": "write"},
                ],
            }
        elif method == "read_status":
            result = {"status": "ok", "value": request["params"].get("value")}
        elif method == "mutate":
            result = {"mutated": True}
        else:
            result = {"unknown": method}
        response = json.dumps(
            {"jsonrpc": "2.0", "id": request["id"], "result": result},
            separators=(",", ":"),
        ) + "\n"
        self.stdout.extend(response.encode("utf-8"))
        return {"session_id": session_id, "running": self.running}

    def read_process_output(self, session_id: str, owner: str, offset=0, length=65536):
        chunk = bytes(self.stdout[offset : offset + length])
        return {
            "session_id": session_id,
            "stdout": chunk.decode("utf-8"),
            "stderr": "",
            "stdout_bytes": len(self.stdout),
            "running": self.running,
        }

    def terminate_session(self, session_id: str, owner: str):
        self.running = False
        self.terminated.append((session_id, owner))
        return {"session_id": session_id, "running": False}


def test_plugin_worker_handshake_narrows_capabilities_and_requires_policy(tmp_path: Path) -> None:
    state = tmp_path / ".sentra"
    governance = GovernanceService(state)
    authorization = AuthorizationService(state)
    processes = FakeProcesses()
    host = PluginWorkerHost(
        state,
        processes=processes,
        governance=governance,
        authorization=authorization,
    )
    owner = "owner-a"
    plugin = governance.register_plugin(
        owner,
        manifest={
            "name": "demo",
            "version": "1.0.0",
            "capabilities": ["read", "write"],
            "worker": {"command": ["python", "worker.py"]},
        },
        verified_methods=[],
        narrowed_capabilities=["read"],
    )

    started = host.start(
        owner,
        plugin_id=plugin["plugin_id"],
        workspace="project",
        run_id="run-plugin",
        narrowed_capabilities=["read"],
    )
    worker = started["worker"]
    verified = started["plugin"]
    assert worker["state"] == "READY"
    assert set(worker["methods"]) == {"read_status", "mutate"}
    assert verified["effective_capabilities"] == ["read"]

    with pytest.raises(PermissionError, match="authorization denied"):
        host.call(
            worker["plugin_worker_id"], owner,
            method="read_status", params={"value": 7},
        )

    authorization.grant(
        owner,
        principal_type="plugin",
        principal_id=plugin["plugin_id"],
        capability="plugin.read",
    )
    result = host.call(
        worker["plugin_worker_id"], owner,
        method="read_status", params={"value": 7},
    )
    assert result == {"status": "ok", "value": 7}

    with pytest.raises(PermissionError, match="not effective"):
        host.call(
            worker["plugin_worker_id"], owner,
            method="mutate", params={},
        )

    stopped = host.stop(worker["plugin_worker_id"], owner)
    assert stopped["state"] == "STOPPED"
    assert processes.terminated == [("proc-1", owner)]


def test_plugin_worker_command_must_match_registered_manifest(tmp_path: Path) -> None:
    state = tmp_path / ".sentra"
    governance = GovernanceService(state)
    authorization = AuthorizationService(state)
    processes = FakeProcesses()
    host = PluginWorkerHost(
        state,
        processes=processes,
        governance=governance,
        authorization=authorization,
    )
    plugin = governance.register_plugin(
        "owner",
        manifest={
            "name": "demo",
            "version": "1.0.0",
            "capabilities": ["read"],
            "worker": {"command": ["worker"]},
        },
    )

    with pytest.raises(PermissionError, match="registered manifest"):
        host.start(
            "owner",
            plugin_id=plugin["plugin_id"],
            command=["different-worker"],
        )
    assert processes.started == []


def test_plugin_live_handshake_must_match_manifest_identity(tmp_path: Path) -> None:
    state = tmp_path / ".sentra"
    governance = GovernanceService(state)
    authorization = AuthorizationService(state)

    class WrongNameProcesses(FakeProcesses):
        def interact_with_process(self, session_id: str, owner: str, stdin: str):
            request = json.loads(stdin.strip())
            response = json.dumps({
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "protocol_version": 1,
                    "name": "other",
                    "version": "1.0.0",
                    "capabilities": ["read"],
                    "methods": [{"name": "read_status", "capability": "read"}],
                },
            }) + "\n"
            self.stdout.extend(response.encode("utf-8"))
            return {"session_id": session_id, "running": True}

    processes = WrongNameProcesses()
    host = PluginWorkerHost(
        state,
        processes=processes,
        governance=governance,
        authorization=authorization,
    )
    plugin = governance.register_plugin(
        "owner",
        manifest={
            "name": "demo",
            "version": "1.0.0",
            "capabilities": ["read"],
            "worker": {"command": ["worker"]},
        },
    )
    with pytest.raises(Exception, match="name mismatch"):
        host.start("owner", plugin_id=plugin["plugin_id"])
    assert processes.terminated == [("proc-1", "owner")]
