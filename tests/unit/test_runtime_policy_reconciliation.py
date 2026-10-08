"""Runtime readiness must prove policy; a real owned MCP reconciles Full changes."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import socket
from pathlib import Path

import pytest
from mcp import Client

from sentra_remote import local_runtime as runtime_module
from sentra_remote.local_runtime import LocalRuntime
from sentra_remote.product import ProductPaths, ProductSettings, mcp_policy_status


def free_port():
    with socket.socket() as bound:
        bound.bind(("127.0.0.1", 0))
        return bound.getsockname()[1]


def test_full_rejects_developer_and_unknown_registration_policy():
    settings = ProductSettings(profile="Full")
    assert mcp_policy_status(settings, {})["reason"] == "runtime_policy_unverified"
    old = {"policy": {"enabled_surfaces": ["core", "developer", "browser"],
                      "process_mode": "workspace", "tool_allowlist": []}}
    assert mcp_policy_status(settings, old)["reason"] == "runtime_policy_mismatch"
    old["policy"]["enabled_surfaces"] += ["oma", "remote", "admin"]
    assert mcp_policy_status(settings, old)["ok"]
    old["policy"]["tool_allowlist"] = ["sentra_health"]
    assert not mcp_policy_status(settings, old)["ok"]


def test_policy_mismatch_does_not_stop_a_foreign_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    runtime = LocalRuntime(ProductPaths(tmp_path / "install", tmp_path / "state"), ProductSettings(profile="Full"))
    monkeypatch.setattr(runtime_module, "tcp_open", lambda *_: True)
    monkeypatch.setattr(runtime_module, "json_get", lambda *_: {
        "ok": True, "service": "sentra-mcp", "instance_id": "foreign-instance",
    })
    def forbidden(*_):
        pytest.fail("a foreign process must never be stopped for policy reconciliation")
    monkeypatch.setattr(runtime, "stop", forbidden)
    assert runtime.start_mcp()["reason"] == "port_in_use_by_different_instance"


def test_owned_real_mcp_restarts_with_full_policy_and_exposes_all_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("SENTRA_MCP_TOOL_ALLOWLIST", raising=False)
    port, relay_port = free_port(), free_port()
    while relay_port == port:
        relay_port = free_port()
    repo = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "project"
    workspace.mkdir()
    settings = ProductSettings(profile="Developer", allowed_roots=[str(workspace)],
                               mcp_port=port, relay_port=relay_port)
    runtime = LocalRuntime(ProductPaths(repo, tmp_path / "state"), settings)
    async def names():
        async with Client(f"http://127.0.0.1:{port}/mcp") as client:
            return {tool.name for tool in (await client.list_tools()).tools}
    try:
        first = runtime.start_mcp()
        assert runtime._wait_mcp_ready(20) is not None
        developer = asyncio.run(names())
        runtime.settings = replace(settings, profile="Full", access_scope="computer")
        assert runtime._mcp_health() is None  # A healthy Developer process is not Full readiness.
        second = runtime.start_mcp()
        assert first["pid"] != second["pid"]
        health = runtime._wait_mcp_ready(20)
        assert health is not None and mcp_policy_status(runtime.settings, health)["ok"]
        full = asyncio.run(names())
        assert full > developer
        assert {"sentra_oma_health", "sentra_list_devices", "sentra_health"} <= full
        reused = runtime.start_mcp()
        assert reused["already_running"]
    finally:
        runtime.stop_all()
