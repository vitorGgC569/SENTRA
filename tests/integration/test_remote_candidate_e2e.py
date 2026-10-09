from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

from orchestrator.agents.router import ModelRouter
from orchestrator.providers.base import AgentResponse
from orchestrator.providers.mock_provider import MockProvider
from sentra_mcp.services import candidate as candidate_mod
from sentra_remote.agent import AgentConfig, AgentRuntime
from sentra_remote.gateway import RemoteGatewayService
from sentra_remote.relay import RemoteRelayServer
from sentra_remote.store import RemoteStore


async def _wait_online(store: RemoteStore, user: str, device_id: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if store.get_device(user, device_id)["status"] == "ONLINE":
            return
        await asyncio.sleep(0.05)
    raise AssertionError("remote candidate agent never became ONLINE")


def _mock_router():
    def handler(request):
        return AgentResponse(
            content=(
                "BEGIN_RESULT\n"
                "STATUS: COMPLETE\n"
                "SUMMARY: remote candidate\n"
                "PATCH:\n"
                "```diff\n"
                "--- a/app.py\n"
                "+++ b/app.py\n"
                "@@ -1 +1 @@\n"
                "-VALUE = 1\n"
                "+VALUE = 2\n"
                "```\n"
                "VALIDATION_COMMANDS:\n"
                "- [[TEST|all]]\n"
                "END_RESULT"
            ),
            success=True,
            model="mock",
        )
    provider = MockProvider(custom_handler=handler, model_name="mock")
    return ModelRouter(
        {"primary": provider, "master": provider},
        primary_provider_name="primary",
        fallback_provider_name="master",
    )


def test_remote_agent_candidate_only_roundtrip(tmp_path: Path, monkeypatch) -> None:
    router = _mock_router()
    monkeypatch.setattr(candidate_mod, "build_router", lambda *a, **k: router)

    async def close(_router):
        return None

    monkeypatch.setattr(candidate_mod, "close_router", close)

    store = RemoteStore(
        tmp_path / "cloud.sqlite3",
        online_window_s=10,
        lease_window_s=5,
    )
    relay = RemoteRelayServer(store, port=0)
    relay_thread = threading.Thread(target=relay.serve_forever, daemon=True)
    relay_thread.start()
    port = relay.server.server_port
    try:
        pairing = store.create_pairing(
            "user-candidate",
            "Candidate PC",
            "windows",
            ["sentra_*"],
        )
        paired = store.pair_device(pairing["pairing_code"])
        root = tmp_path / "device-root"
        root.mkdir()
        original = "VALUE = 1\n"
        (root / "app.py").write_text(original, encoding="utf-8")

        runtime = AgentRuntime(
            AgentConfig(
                relay_url=f"http://127.0.0.1:{port}",
                device_id=paired["device_id"],
                device_token=paired["device_token"],
                name="Candidate PC",
                allowed_roots=[str(root)],
                audit_log=str(tmp_path / "agent-audit.jsonl"),
                process_mode="workspace",
            ),
            tmp_path / "agent.json",
        )
        gateway = RemoteGatewayService(store, poll_interval_s=0.02)

        async def run_cycle() -> None:
            agent_task = asyncio.create_task(runtime.run())
            try:
                await _wait_online(store, "user-candidate", paired["device_id"])
                result = await asyncio.to_thread(
                    gateway.invoke,
                    "user-candidate",
                    paired["device_id"],
                    "sentra_oma_candidate_generate",
                    {
                        "workspace": "sentra",
                        "task": {
                            "id": "T-remote",
                            "run_id": "run-central",
                            "objective": "change value",
                            "target_files": ["app.py"],
                        },
                        "context_summary": "candidate-only integration test",
                    },
                    timeout_s=20,
                    wait_s=20,
                    idempotency_key="candidate-e2e-1",
                )
                assert result["state"] == "COMPLETED"
                envelope = result["result"]
                assert envelope["ok"] is True
                data = envelope["data"]
                assert data["status"] == "CANDIDATE_READY"
                assert data["source_unchanged"] is True
                assert data["candidate"]["task_id"] == "T-remote"
                assert "VALUE = 2" in data["candidate"]["patch"]
                assert (root / "app.py").read_text(encoding="utf-8") == original

                replay = await asyncio.to_thread(
                    gateway.invoke,
                    "user-candidate",
                    paired["device_id"],
                    "sentra_oma_candidate_generate",
                    {
                        "workspace": "sentra",
                        "task": {
                            "id": "T-remote",
                            "run_id": "run-central",
                            "objective": "change value",
                            "target_files": ["app.py"],
                        },
                        "context_summary": "candidate-only integration test",
                    },
                    timeout_s=20,
                    wait_s=20,
                    idempotency_key="candidate-e2e-1",
                )
                assert replay["job_id"] == result["job_id"]
                assert replay.get("idempotent_replay") is True
            finally:
                runtime.stop_event.set()
                await asyncio.wait_for(agent_task, timeout=10)

        asyncio.run(run_cycle())
    finally:
        relay.stop()
        relay_thread.join(timeout=5)
        store.close()
