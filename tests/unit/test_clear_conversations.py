"""Testes para exclusão e limpeza de chats (flag --clear, transport, protocolo e pool)."""
import asyncio
import json
from pathlib import Path
import pytest

from native_bridge.protocol import ChatJob
from orchestrator.conversation_pool import FixedConversationRouter, clear_run_conversations


class DummyTransport:
    def __init__(self, succeed=True):
        self.succeed = succeed
        self.calls = []

    async def delete_chat(self, target: str, timeout_s: int = 30):
        self.calls.append(target)
        if self.succeed:
            return {"status": "COMPLETED", "result": json.dumps({"deleted": True, "target": target})}
        return {"status": "FAILED", "error": "mock_delete_error"}


def test_protocol_delete_chat_validation():
    # Valido com conversation_url
    job1 = ChatJob(task_id="T-DEL-1", conversation_url="https://chatgpt.com/c/abc-123", kind="DELETE_CHAT")
    job1.validate()
    assert job1.kind == "DELETE_CHAT"

    # Valido com prompt (conversation_id)
    job2 = ChatJob(task_id="T-DEL-2", prompt="abc-123", kind="DELETE_CHAT")
    job2.validate()

    # Invalido sem url nem prompt
    job3 = ChatJob(task_id="T-DEL-3", prompt="", conversation_url=None, kind="DELETE_CHAT")
    with pytest.raises(ValueError, match="required for DELETE_CHAT"):
        job3.validate()


@pytest.mark.asyncio
async def test_clear_conversations_with_transport(tmp_path):
    # Prepara um arquivo conversations.json com seats ativos
    conv_file = tmp_path / FixedConversationRouter.FILENAME
    conv_file.write_text(json.dumps({
        "schema_version": 2,
        "run_id": "RUN-TEST-CLEAR",
        "last_dispatch_at": 1000.0,
        "seats": {
            "RUN-TEST-CLEAR:master": {
                "provider": "extension",
                "state": "CONFIRMED",
                "url": "https://chatgpt.com/c/conv-master-123",
                "conversation_id": "conv-master-123",
            },
            "RUN-TEST-CLEAR:executor": {
                "provider": "extension",
                "state": "CONFIRMED",
                "url": "https://chatgpt.com/c/conv-exec-456",
                "conversation_id": "conv-exec-456",
            },
            "RUN-TEST-CLEAR:validator.logic": {
                "provider": "mock",
                "state": "NOT_SENT",
            }
        }
    }), encoding="utf-8")

    transport = DummyTransport(succeed=True)
    report = await clear_run_conversations(tmp_path, "RUN-TEST-CLEAR", transport=transport)

    assert len(report["cleared"]) == 3
    # Dois remotos chamaram o transport
    assert transport.calls == ["conv-master-123", "conv-exec-456"]

    # Verifica se o arquivo em disco foi atualizado
    updated_data = json.loads(conv_file.read_text(encoding="utf-8"))
    assert updated_data["seats"]["RUN-TEST-CLEAR:master"]["state"] == "CLEARED"
    assert updated_data["seats"]["RUN-TEST-CLEAR:executor"]["state"] == "CLEARED"
    assert updated_data["seats"]["RUN-TEST-CLEAR:validator.logic"]["state"] == "CLEARED"


@pytest.mark.asyncio
async def test_clear_conversations_transport_failure(tmp_path):
    conv_file = tmp_path / FixedConversationRouter.FILENAME
    conv_file.write_text(json.dumps({
        "schema_version": 2,
        "run_id": "RUN-FAIL",
        "last_dispatch_at": 1000.0,
        "seats": {
            "RUN-FAIL:executor": {
                "provider": "extension",
                "state": "CONFIRMED",
                "url": "https://chatgpt.com/c/conv-fail-789",
                "conversation_id": "conv-fail-789",
            }
        }
    }), encoding="utf-8")

    transport = DummyTransport(succeed=False)
    report = await clear_run_conversations(tmp_path, "RUN-FAIL", transport=transport)
    assert len(report["failed"]) == 1
    assert "mock_delete_error" in report["failed"][0]["error"]


@pytest.mark.asyncio
async def test_relay_delete_chat_roundtrip():
    from browser.extension_transport import ExtensionTransport, _get, _post
    from native_bridge.relay import RelayServer

    server = RelayServer(port=0).start()
    base = f"http://127.0.0.1:{server.server.server_port}"
    transport = ExtensionTransport(base, token=server.token)

    async def worker():
        for _ in range(200):
            response = await asyncio.to_thread(_get, base + "/jobs/poll?worker=TEST-DEL-WORKER", 5, server.token)
            job = response.get("job")
            if job:
                assert job["kind"] == "DELETE_CHAT"
                payload = {"job_id": job["job_id"], "worker": "TEST-DEL-WORKER", "lease_token": job["lease_token"]}
                await asyncio.to_thread(_post, base + "/jobs/lease", payload, 5, server.token)
                await asyncio.to_thread(_post, base + "/jobs/result", {
                    **payload,
                    "task_id": job["task_id"],
                    "status": "COMPLETED",
                    "result": json.dumps({"deleted": True, "conversation_id": "conv-del-123"}),
                    "conversation_url": job.get("conversation_url"),
                }, 5, server.token)
                return job["job_id"]
            await asyncio.sleep(0.01)
        raise AssertionError("worker never received DELETE_CHAT job")

    try:
        work = asyncio.create_task(worker())
        response = await transport.delete_chat("https://chatgpt.com/c/conv-del-123", timeout_s=10)
        jid = await work
        assert response["job_id"] == jid
        assert response["status"] == "COMPLETED"
        result_json = json.loads(response["result"])
        assert result_json["deleted"] is True
    finally:
        server.stop()
