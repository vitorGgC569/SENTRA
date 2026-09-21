from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from sentra_remote.agent import AgentConfig, AgentRuntime
from sentra_remote.gateway import RemoteGatewayService
from sentra_remote.relay import RemoteRelayServer
from sentra_remote.store import RemoteStore


async def _wait_online(store: RemoteStore, user: str, device_id: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if store.get_device(user, device_id)["status"] == "ONLINE":
            return
        await asyncio.sleep(0.05)
    raise AssertionError("remote agent never became ONLINE")


def test_cloud_relay_agent_local_mcp_roundtrip(tmp_path: Path) -> None:
    store = RemoteStore(tmp_path / "cloud.sqlite3", online_window_s=10, lease_window_s=5)
    relay = RemoteRelayServer(store, port=0)
    relay_thread = threading.Thread(target=relay.serve_forever, daemon=True)
    relay_thread.start()
    port = relay.server.server_port
    try:
        pairing = store.create_pairing(
            "user-e2e",
            "E2E PC",
            "windows",
            ["sentra_*", "system.shutdown_agent"],
        )
        paired = store.pair_device(pairing["pairing_code"])
        root = tmp_path / "device-root"
        root.mkdir()
        (root / "hello.txt").write_text("remote-ok\n", encoding="utf-8", newline="\n")

        config = AgentConfig(
            relay_url=f"http://127.0.0.1:{port}",
            device_id=paired["device_id"],
            device_token=paired["device_token"],
            name="E2E PC",
            allowed_roots=[str(root)],
            audit_log=str(tmp_path / "agent-audit.jsonl"),
        )
        runtime = AgentRuntime(config, tmp_path / "agent.json")
        gateway = RemoteGatewayService(store, poll_interval_s=0.02)

        async def run_cycle() -> None:
            agent_task = asyncio.create_task(runtime.run())
            try:
                await _wait_online(store, "user-e2e", paired["device_id"])

                read = await asyncio.to_thread(
                    gateway.invoke,
                    "user-e2e",
                    paired["device_id"],
                    "sentra_read_file",
                    {"path": "hello.txt"},
                    timeout_s=20,
                    wait_s=20,
                )
                assert read["state"] == "COMPLETED"
                assert read["result"]["ok"] is True
                assert read["result"]["data"]["content"] == "remote-ok\n"

                write = await asyncio.to_thread(
                    gateway.invoke,
                    "user-e2e",
                    paired["device_id"],
                    "sentra_write_file",
                    {"path": "created.txt", "content": "from-cloud\n"},
                    timeout_s=20,
                    wait_s=20,
                )
                assert write["state"] == "COMPLETED"
                assert (root / "created.txt").read_text(encoding="utf-8") == "from-cloud\n"

                started = await asyncio.to_thread(
                    gateway.invoke,
                    "user-e2e",
                    paired["device_id"],
                    "sentra_start_process",
                    {
                        "command": ["python", "-u", "-c", "print('remote-process-ok')"],
                        "owner": "cloud-e2e",
                        "timeout": 10.0,
                    },
                    timeout_s=20,
                    wait_s=20,
                )
                assert started["state"] == "COMPLETED"
                session_id = started["result"]["data"]["session_id"]

                latest = None
                for _ in range(100):
                    latest = await asyncio.to_thread(
                        gateway.invoke,
                        "user-e2e",
                        paired["device_id"],
                        "sentra_read_process_output",
                        {
                            "session_id": session_id,
                            "owner": "cloud-e2e",
                            "offset": 0,
                            "length": 4096,
                        },
                        timeout_s=20,
                        wait_s=20,
                    )
                    if "remote-process-ok" in latest["result"]["data"]["stdout"]:
                        break
                    await asyncio.sleep(0.03)
                assert latest is not None
                assert "remote-process-ok" in latest["result"]["data"]["stdout"]

                shut = await asyncio.to_thread(
                    gateway.shutdown_agent,
                    "user-e2e",
                    paired["device_id"],
                    timeout_s=20,
                )
                assert shut["state"] == "COMPLETED"
                await asyncio.wait_for(agent_task, timeout=10)
            finally:
                runtime.stop_event.set()
                if not agent_task.done():
                    await asyncio.wait_for(agent_task, timeout=10)

        asyncio.run(run_cycle())
    finally:
        relay.stop()
        relay_thread.join(timeout=5)
        store.close()
