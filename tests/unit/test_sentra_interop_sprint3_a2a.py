"""Loopback HTTP A2A local E2E; real TCP, secret never printed or persisted."""
import asyncio
import secrets
import socket

import pytest
from sentra_runtime.contracts import Capability, Machine, PolicyDecision
from sentra_interop import InteropGate, InteropRequestMapper, AgentIdentity
from sentra_interop.a2a_loopback import A2ALoopbackServer, A2ALoopbackClient


def test_a2a_local_http_full_task_lifecycle_and_negative_cases(tmp_path):
    async def check():
        live = True
        owner = "test-principal"
        workspace = "work-A"
        who = AgentIdentity(owner, "fixture-peer", "test-domain")
        machine = Machine("a2a-machine", "agent", owner, tuple(
            Capability(x, x) for x in ("a2a:ingest", "a2a:read", "a2a:cancel")))
        def authorize(request):
            return PolicyDecision(
                live and request.work_item_id == workspace and request.principal_id == owner,
                "current local grant",
                {"principal_ids": [owner], "work_item_ids": [workspace]},
            )
        gate = InteropGate(machine, authorize)
        mapper = InteropRequestMapper(
            "a2a-machine", owner, workspace, str(tmp_path),
            frozenset(("a2a:ingest", "a2a:read", "a2a:cancel")))
        key = secrets.token_urlsafe(32)
        srv = await A2ALoopbackServer(gate, mapper, who, token=key).start()
        client = A2ALoopbackClient(port=srv.port, token=key)
        other = A2ALoopbackClient(port=srv.port, token="invalid"*6)
        try:
            assert srv._server.sockets[0].getsockname()[0] == "127.0.0.1"
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    assert probe.connect_ex(("127.0.0.2", srv.port)) != 0
            except OSError:
                pass
            status, card = await client.request("GET", "/.well-known/agent-card.json")
            assert status == 200 and card["id"] == who.agent_id
            assert card["trustDomain"] == who.trust_domain
            assert await other.request("GET", "/.well-known/agent-card.json") == (
                401, {"error": "unauthorized"})

            def event(n, state, *, task="task-1", work=workspace, artifact=None,
                      seq=None, op=None):
                stream = ({"artifactUpdate": {
                    "taskId": task, "contextId": work,
                    "artifact": {"artifactId": "artifact-1",
                                 "parts": [{"text": "document"}]},
                    "lastChunk": True}}
                    if artifact else {"statusUpdate": {
                        "taskId": task, "contextId": work,
                        "status": {"state": "TASK_STATE_" + state.upper()}}})
                return {"operation_id": op or f"op-{n}", "idempotency_key": f"key-{n}",
                        "event_id": f"event-{n}", "sequence": n if seq is None else seq,
                        "payload": stream}
            first = event(0, "submitted")
            ok, submitted = await client.request("POST", "/v1/events", first)
            assert ok == 200 and submitted["taskState"] == "submitted"
            assert (await client.request("POST", "/v1/events", first))[1]["duplicate"] is True
            assert (await client.request("GET", "/v1/tasks/task-1"))[1]["state"] == "submitted"

            bad, response = await client.request(
                "POST", "/v1/events", event(1, "working", work="work-B"))
            assert bad == 400 and response["error"] == "invalid_request"
            assert (await client.request("GET", "/v1/tasks/task-1"))[1]["state"] == "submitted"
            bad, _ = await client.request("POST", "/v1/events", event(88, "working", seq=0))
            assert bad == 403
            ok, _ = await client.request("POST", "/v1/events", event(1, "working"))
            assert ok == 200
            ok, _ = await client.request("POST", "/v1/events", event(2, "working", artifact=True))
            assert ok == 200
            assert (await client.request("GET", "/v1/tasks/task-1"))[1]["state"] == "working"
            code, stored = await client.request("GET", "/v1/tasks/task-1/artifacts")
            assert code == 200
            assert stored["artifacts"] == [
                {"artifactId": "artifact-1", "parts": [{"text": "document"}], "final": True}]
            assert (await other.request("GET", "/v1/tasks/task-1/artifacts"))[0] == 401

            # A revocation after the socket opens cannot turn into success.
            live = False
            bad, _ = await client.request("POST", "/v1/events", event(3, "completed"))
            assert bad == 403
            assert (await client.request("GET", "/v1/tasks/task-1"))[0] == 403
            live = True
            ok, canceled = await client.request(
                "POST", "/v1/tasks/task-1:cancel",
                {"operation_id":"cancel-1","idempotency_key":"cancel-key-1","task_id":"task-1"})
            assert ok == 200 and canceled["state"] == "CANCELLED"
            idem_code, idem = await client.request(
                "POST", "/v1/tasks/task-1:cancel",
                {"operation_id":"cancel-1","idempotency_key":"cancel-key-1","task_id":"task-1"})
            assert idem_code == 200 and idem["duplicate"] is True
            assert (await client.request("GET", "/v1/tasks/task-1"))[1]["state"] == "canceled"
            denied, _ = await client.request("POST", "/v1/events", event(3,"completed"))
            assert denied == 403
            denied, _ = await client.request(
                "POST", "/v1/tasks/task-1:cancel",
                {"operation_id":"cancel-2","idempotency_key":"cancel-key-2","task_id":"task-1"})
            assert denied == 403
            assert (await client.request("GET", "/v1/tasks/foreign-task"))[0] == 404
        finally:
            await srv.close()
        with pytest.raises((ConnectionRefusedError, OSError)):
            await client.request("GET", "/.well-known/agent-card.json")
    asyncio.run(check())
