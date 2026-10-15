"""Actual HTTP/SQLite/transport roundtrip with a scripted worker (NOT a live Edge test)."""
import asyncio

from browser.extension_transport import ExtensionTransport, _get, _post
from native_bridge.relay import RelayServer


async def test_transport_pairs_submits_correlates_receives_and_acks():
    server = RelayServer(port=0).start()
    base = f"http://127.0.0.1:{server.server.server_port}"
    transport = ExtensionTransport(base, token=server.token)
    async def worker():
        for _ in range(200):
            response = await asyncio.to_thread(_get, base+"/jobs/poll?worker=TAB-TEST-WORKER",5,server.token)
            job = response["job"]
            if job:
                payload = {"job_id":job["job_id"],"worker":"TAB-TEST-WORKER","lease_token":job["lease_token"]}
                await asyncio.to_thread(_post,base+"/jobs/lease",payload,5,server.token)
                await asyncio.to_thread(_post,base+"/jobs/result",{
                    **payload,"task_id":job["task_id"],"status":"COMPLETED","result":"scripted worker reply",
                    "conversation_url":"https://chatgpt.com/c/scripted-test"},5,server.token)
                return job["job_id"]
            await asyncio.sleep(.01)
        raise AssertionError("transport never submitted a job")
    try:
        # Pair/register the real worker identity before submission. The transport
        # intentionally fails fast when no extension worker has ever connected.
        await asyncio.to_thread(
            _get,
            base + "/jobs/poll?worker=TAB-TEST-WORKER",
            5,
            server.token,
        )
        work = asyncio.create_task(worker())
        response = await transport.submit_chat("T-HTTP","integration test",timeout_s=10)
        jid = await work
        assert response["job_id"] == jid and response["task_id"] == "T-HTTP"
        assert response["result"] == "scripted worker reply"
        assert server.state.db.execute("SELECT ack FROM jobs WHERE id=?",(jid,)).fetchone()[0] == 1
        assert server.state.result(jid)["result"] == response["result"]
    finally:
        server.stop()
