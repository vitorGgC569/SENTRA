from __future__ import annotations

import asyncio
import hashlib
import sys
import time
from pathlib import Path

import pytest

from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import MCPConfig
from sentra_mcp.errors import SentraSemanticError, error_envelope
from sentra_mcp.server import SentraMCPServer
from sentra_mcp.services.browser import BrowserControlService
from sentra_mcp.services.capabilities import server_build_identity
from sentra_mcp.services.durable import (
    DurableRunService,
    DurableStateConflict,
    StaleFenceError,
)
from sentra_mcp.services.filesystem import FilesystemService
from sentra_mcp.services.process import ProcessService


def _config(tmp_path: Path, **changes) -> MCPConfig:
    values = {
        "allowed_roots": (tmp_path,),
        "audit_log": tmp_path / ".sentra" / "audit.jsonl",
        "remote_store_path": tmp_path / ".sentra" / "remote.sqlite3",
        "state_root": tmp_path / ".sentra",
        "process_mode": "unrestricted",
    }
    values.update(changes)
    return MCPConfig(**values)


def test_durable_operation_idempotency_wait_and_resume(tmp_path: Path) -> None:
    service = DurableRunService(tmp_path / ".sentra")
    try:
        run = service.create_run(
            "owner-a",
            workspace="sentra",
            idempotency_key="run-key",
        )
        replay = service.create_run(
            "owner-a",
            workspace="sentra",
            idempotency_key="run-key",
        )
        assert replay["run_id"] == run["run_id"]
        assert replay["idempotent_replay"] is True

        op = service.create_operation(
            run["run_id"],
            "owner-a",
            kind="build",
            idempotency_key="build-once",
        )
        service.update_operation(
            op["operation_id"],
            "owner-a",
            state="STARTING",
            progress={"stage": "STARTING"},
        )
        service.update_operation(
            op["operation_id"],
            "owner-a",
            state="RUNNING",
            progress={"stage": "RUNNING"},
        )
        op_replay = service.create_operation(
            run["run_id"],
            "owner-a",
            kind="build",
            idempotency_key="build-once",
        )
        assert op_replay["operation_id"] == op["operation_id"]
        assert op_replay["idempotent_replay"] is True

        waited = service.wait_operation(
            op["operation_id"], "owner-a", timeout_s=0.05, poll_s=0.01
        )
        assert waited["wait_timed_out"] is True
        assert waited["state"] == "RUNNING"

        resumed = service.resume(run["run_id"], "owner-a")
        assert resumed["resume"]["safe_to_continue"] is True
        assert resumed["operations"][0]["operation_id"] == op["operation_id"]
        assert Path(resumed["resume"]["events_path"]).is_file()
        assert Path(resumed["resume"]["state_path"]).is_file()
    finally:
        service.close()


def test_fencing_is_idempotent_for_holder_and_rejects_steal(tmp_path: Path) -> None:
    service = DurableRunService(tmp_path / ".sentra")
    try:
        run = service.create_run("owner-a")
        op1 = service.create_operation(
            run["run_id"], "owner-a", kind="writer", idempotency_key="writer-1"
        )
        op2 = service.create_operation(
            run["run_id"], "owner-a", kind="writer", idempotency_key="writer-2"
        )
        first = service.acquire_lease(
            run["run_id"],
            "owner-a",
            "workspace-write",
            operation_id=op1["operation_id"],
            ttl_s=60,
        )
        replay = service.acquire_lease(
            run["run_id"],
            "owner-a",
            "workspace-write",
            operation_id=op1["operation_id"],
            ttl_s=60,
        )
        assert replay["fencing_token"] == first["fencing_token"]
        assert replay["idempotent_replay"] is True

        with pytest.raises(DurableStateConflict):
            service.acquire_lease(
                run["run_id"],
                "owner-a",
                "workspace-write",
                operation_id=op2["operation_id"],
                ttl_s=60,
            )
        service.release_lease(
            "workspace-write", "owner-a", first["fencing_token"]
        )
        with pytest.raises(StaleFenceError):
            service.renew_lease(
                "workspace-write", "owner-a", first["fencing_token"], ttl_s=60
            )
    finally:
        service.close()


def test_reconcile_marks_stale_dead_process_uncertain(tmp_path: Path) -> None:
    clock = [1000.0]
    service = DurableRunService(tmp_path / ".sentra", clock=lambda: clock[0])
    try:
        run = service.create_run("owner-a")
        op = service.create_operation(
            run["run_id"], "owner-a", kind="process.start", idempotency_key="proc"
        )
        service.update_operation(op["operation_id"], "owner-a", state="STARTING")
        service.update_operation(op["operation_id"], "owner-a", state="RUNNING")
        service.attach_resource(
            run["run_id"],
            "owner-a",
            resource_type="process",
            resource_id="process-dead-test",
            operation_id=op["operation_id"],
            state="RUNNING",
            metadata={"pid": 2147483000},
        )
        clock[0] += 300
        result = service.reconcile(
            run["run_id"], "owner-a", stale_after_s=30
        )
        assert result["auto_replay"] is False
        assert result["actions"][0]["action"] == "MARK_UNCERTAIN"
        status = service.operation_status(op["operation_id"], "owner-a")
        assert status["state"] == "UNCERTAIN"
        assert result["run"]["state"] == "RECOVERING"
        assert result["run"]["resources"][0]["state"] == "EXITED"
    finally:
        service.close()


def test_artifact_binary_roundtrip_and_uniform_filesystem_lists(tmp_path: Path) -> None:
    config = _config(tmp_path)
    durable = DurableRunService(config.state_root)
    filesystem = FilesystemService(config, AuditLogger(config.audit_log))
    payload = b"\x89PNG\r\n\x1a\nSENTRA-BINARY\x00\xff"
    target = tmp_path / "evidence.png"
    target.write_bytes(payload)
    try:
        run = durable.create_run("owner-a")
        artifact = durable.register_artifact(
            run["run_id"], "owner-a", target, mime_type="image/png"
        )
        assert artifact["sha256"] == hashlib.sha256(payload).hexdigest()
        capability = artifact["artifact_id"].removeprefix("artifact-")
        assert len(capability) == 32
        int(capability, 16)
        assert capability != artifact["sha256"][:32]

        second = durable.register_artifact(
            run["run_id"], "owner-a", target, mime_type="image/png"
        )
        assert second["artifact_id"] != artifact["artifact_id"]
        assert second["sha256"] == artifact["sha256"]

        assert durable.read_artifact(
            artifact["artifact_id"], max_bytes=1024
        ) == payload

        listed = filesystem.list_directory(".", owner="owner-a")
        assert listed["items"] == listed["entries"]
        assert listed["page"]["total"] == len(listed["entries"])
        multi = filesystem.read_multiple_files(
            ["evidence.png"], owner="owner-a"
        )
        assert multi["items"] == multi["results"]
        assert multi["page"]["total"] == 1
    finally:
        durable.close()


def test_process_idempotency_readiness_and_tree(tmp_path: Path) -> None:
    config = _config(tmp_path)
    durable = DurableRunService(config.state_root)
    service = ProcessService(
        config,
        AuditLogger(config.audit_log),
        durable=durable,
    )
    command = [
        sys.executable,
        "-u",
        "-c",
        "import time; print('SENTRA_PRODUCT_READY', flush=True); time.sleep(20)",
    ]
    try:
        started = service.start_process(
            command,
            "owner-a",
            mode="unrestricted",
            idempotency_key="same-process",
            readiness_probe={
                "stdout_contains": "SENTRA_PRODUCT_READY",
                "timeout_s": 5,
            },
        )
        replay = service.start_process(
            command,
            "owner-a",
            mode="unrestricted",
            idempotency_key="same-process",
            readiness_probe={
                "stdout_contains": "SENTRA_PRODUCT_READY",
                "timeout_s": 5,
            },
        )
        assert replay["session_id"] == started["session_id"]
        assert replay["idempotent_replay"] is True

        deadline = time.time() + 8
        status = None
        while time.time() < deadline:
            status = durable.operation_status(
                str(started["operation_id"]), "owner-a"
            )
            if status["readiness"] == "PRODUCT_READY":
                break
            time.sleep(0.1)
        assert status is not None
        assert status["state"] == "RUNNING"
        assert status["readiness"] == "PRODUCT_READY"
        assert status["progress"]["stage"] == "READY"

        tree = service.process_tree(
            "owner-a", run_id=str(started["run_id"])
        )
        assert tree["page"]["total"] == 1
        assert tree["items"][0]["pid"] == started["pid"]
        assert tree["items"][0]["operation_id"] == started["operation_id"]
        assert tree["items"][0]["process_state"] == "RUNNING"

        service.terminate_session(str(started["session_id"]), "owner-a")
    finally:
        service.shutdown()
        durable.close()


def test_server_build_identity_changes_with_dirty_source_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SENTRA_BUILD_ID", raising=False)
    package = tmp_path / "sentra_mcp"
    package.mkdir()
    source = package / "probe.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    server_build_identity.cache_clear()
    first = server_build_identity(tmp_path)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    server_build_identity.cache_clear()
    second = server_build_identity(tmp_path)
    assert first["source"] == "source-tree"
    assert first["source_hash"] != second["source_hash"]
    assert first["build_id"] != second["build_id"]


def test_capability_contract_schema_and_surface_budget(tmp_path: Path) -> None:
    runtime = SentraMCPServer(_config(tmp_path))
    try:
        manifest = asyncio.run(runtime.capabilities.manifest())
        assert manifest["contract"]["tool_count"] < 75
        assert len(manifest["contract"]["schema_hash"]) == 64
        assert manifest["capabilities"]["durable_operation"] is True
        assert manifest["fallback_policy"]["silent_invasive_fallbacks"] is False

        mismatch = asyncio.run(runtime.capabilities.negotiate(
            client_schema_hash="0" * 64
        ))
        assert mismatch["compatible"] is False
        assert mismatch["reasons"][0]["code"] == "SCHEMA_MISMATCH"

        tools = {
            tool.name: tool for tool in runtime.mcp._tool_manager.list_tools()
        }
        assert {"sentra_run", "sentra_operation", "sentra_artifact"} <= set(tools)
        assert "idempotency_key" in tools["sentra_start_process"].parameters["properties"]
        assert "readiness_probe" in tools["sentra_start_process"].parameters["properties"]
        assert "allow_invasive_fallback" in tools["sentra_browser_open"].parameters["properties"]
        assert "session_token" in tools["sentra_run"].parameters["properties"]
    finally:
        runtime.processes.shutdown()
        runtime.search.close()
        runtime.remote_store.close()
        runtime.durable.close()


def test_browser_capability_manifest_rejects_stale_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    browser = BrowserControlService(config, AuditLogger(config.audit_log))

    async def fake_health():
        return {"ok": True, "pool": {"active": True}, "workers_online": ["TAB-1"]}

    async def fake_inventory():
        return [{
            "worker": "TAB-1",
            "worker_state": "STALE",
            "usable": False,
            "error_code": "PLUGIN_STALE",
            "error": "PLUGIN_STALE: service-worker build",
            "plugin_identity": {"verified": False},
        }]

    monkeypatch.setattr(browser, "_edge_health", fake_health)
    monkeypatch.setattr(browser, "_edge_worker_inventory", fake_inventory)
    result = asyncio.run(browser.capability_manifest())
    assert result["available"] is False
    assert result["compatibility_error"] == "PLUGIN_STALE"
    assert result["capabilities"]["silent_invasive_fallback"] is False


def test_semantic_error_preserves_structured_redacted_details() -> None:
    envelope = error_envelope(SentraSemanticError(
        "PLUGIN_STALE",
        "loaded build is stale",
        category="compatibility",
        retryable=True,
        operation_id="op-1",
        details={
            "identity": {"version": "1.0", "token": "super-secret-value"},
            "worker": "TAB-1",
        },
    ))
    assert envelope.ok is False
    assert envelope.error is not None
    assert envelope.error.code == "PLUGIN_STALE"
    assert envelope.error.category == "compatibility"
    assert envelope.error.retryable is True
    assert envelope.error.operation_id == "op-1"
    assert isinstance(envelope.error.details, dict)
    assert envelope.error.details["identity"]["token"] == "[REDACTED]"


def test_agent_chat_are_logically_distinct_and_chat_can_rebind(tmp_path: Path) -> None:
    service = DurableRunService(tmp_path / ".sentra")
    try:
        run = service.create_run("owner-a", run_id="run-agent-chat")
        agent = service.assign_agent(
            run["run_id"],
            "owner-a",
            role="builder",
            task_id="task-17",
            agent_id="agent-builder",
        )
        chat = service.bind_chat(
            run["run_id"],
            "owner-a",
            agent_id=agent["agent_id"],
            chat_id="chat-builder",
            provider="chatgpt",
            conversation_id="old-conversation",
            conversation_url="https://chatgpt.com/c/old-conversation",
            project_id="project-1",
            project_url="https://chatgpt.com/g/g-p-project-1/project",
        )
        assert chat["title"] == "[SENTRA] run-agent-chat - builder"
        rebound = service.rebind_chat(
            chat["chat_id"],
            "owner-a",
            conversation_id="new-conversation",
            conversation_url="https://chatgpt.com/c/new-conversation",
            provider="chatgpt",
            reason="stale physical chat",
        )
        snapshot = service.run_status(run["run_id"], "owner-a")
        assert rebound["chat_id"] == "chat-builder"
        assert rebound["agent_id"] == "agent-builder"
        assert snapshot["agents"][0]["task_id"] == "task-17"
        assert snapshot["agents"][0]["chat_id"] == "chat-builder"
        assert snapshot["chats"][0]["conversation_id"] == "new-conversation"
        events = service.events(run["run_id"], "owner-a", limit=100)["items"]
        event_types = [item["type"] for item in events]
        assert "AGENT_ASSIGNED" in event_types
        assert "CHAT_BOUND" in event_types
        assert "CHAT_REBOUND" in event_types
    finally:
        service.close()


def test_capabilities_used_and_reconciliation_use_multiple_liveness_signals(
    tmp_path: Path,
) -> None:
    clock = [1000.0]
    service = DurableRunService(tmp_path / ".sentra", clock=lambda: clock[0])
    artifact_path = tmp_path / "progress.txt"
    artifact_path.write_text("progress", encoding="utf-8")
    try:
        run = service.create_run("owner-a", run_id="run-signals")
        service.record_capabilities_used(
            run["run_id"], "owner-a", ["browser.chat", "filesystem.write"]
        )
        agent = service.assign_agent(
            run["run_id"], "owner-a", role="reviewer", agent_id="agent-review"
        )
        chat = service.bind_chat(
            run["run_id"], "owner-a", agent_id=agent["agent_id"],
            chat_id="chat-review", provider="chatgpt"
        )
        op = service.create_operation(
            run["run_id"], "owner-a", kind="review",
            idempotency_key="review-once"
        )
        service.update_operation(
            op["operation_id"], "owner-a", state="STARTING",
            progress={"agent_id": agent["agent_id"], "chat_id": chat["chat_id"]}
        )
        service.update_operation(
            op["operation_id"], "owner-a", state="RUNNING"
        )
        service.register_artifact(
            run["run_id"], "owner-a", artifact_path,
            operation_id=op["operation_id"]
        )
        clock[0] += 130
        service.update_agent(agent["agent_id"], "owner-a", metadata={"tick": 1})
        service.update_chat(chat["chat_id"], "owner-a", metadata={"tick": 1})
        result = service.reconcile(
            run["run_id"], "owner-a", stale_after_s=120
        )
        assert result["actions"][0]["action"] == "NO_ACTION"
        assert {"fresh_agent", "fresh_chat"} <= set(result["actions"][0]["evidence"])
        snapshot = service.run_status(run["run_id"], "owner-a")
        assert snapshot["capabilities_used"] == ["browser.chat", "filesystem.write"]
        assert snapshot["operations"][0]["state"] == "RUNNING"
    finally:
        service.close()


def test_reconcile_marks_linked_agent_chat_stalled_without_evidence(tmp_path: Path) -> None:
    clock = [1000.0]
    service = DurableRunService(tmp_path / ".sentra", clock=lambda: clock[0])
    try:
        run = service.create_run("owner-a", run_id="run-stall")
        agent = service.assign_agent(
            run["run_id"], "owner-a", role="supervisor", agent_id="agent-supervisor"
        )
        chat = service.bind_chat(
            run["run_id"], "owner-a", agent_id=agent["agent_id"],
            chat_id="chat-supervisor", provider="chatgpt"
        )
        op = service.create_operation(
            run["run_id"], "owner-a", kind="tool-call", idempotency_key="tool-1"
        )
        service.update_operation(
            op["operation_id"], "owner-a", state="STARTING",
            progress={"agent_id": agent["agent_id"], "chat_id": chat["chat_id"]}
        )
        service.update_operation(op["operation_id"], "owner-a", state="RUNNING")
        clock[0] += 300
        result = service.reconcile(run["run_id"], "owner-a", stale_after_s=30)
        snapshot = result["run"]
        assert snapshot["state"] == "RECOVERING"
        assert snapshot["operations"][0]["state"] == "UNCERTAIN"
        assert snapshot["agents"][0]["state"] == "SUSPECTED_STALL"
        assert snapshot["chats"][0]["state"] == "DISCONNECTED"
        assert any(
            item.get("action") == "SOFT_RECOVERY_REQUIRED"
            for item in result["actions"]
        )
        assert result["auto_replay"] is False
    finally:
        service.close()
