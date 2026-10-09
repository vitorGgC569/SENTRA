"""Real loopback TCP E2E for Activepieces-like connector; not SaaS."""
from __future__ import annotations
import asyncio
import secrets
from sentra_interop.activepieces_loopback import ActivepiecesActionClient, ActivepiecesLoopbackServer
from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision
from sentra_interop.gate import InteropGate


def test_activepieces_real_http_policy_dedupe_malformed_timeout_revocation(tmp_path):
    async def main():
        allow = True
        invocations = []
        slow_started = asyncio.Event()
        release_slow = asyncio.Event()
        machine = Machine("pieces-machine", "agent", "owner", (
            Capability("activepieces:echo","echo"), Capability("activepieces:slow","slow"),
            Capability("activepieces:malformed","malformed"),
        ))
        def policy(req):
            return PolicyDecision(allow and req.principal_id == "owner" and
                                  req.work_item_id == "work-1", "work grant", {
                                      "principal_ids":["owner"], "work_item_ids":["work-1"]})
        async def echo(args):
            invocations.append(("echo",args["value"]))
            return {"value":args["value"]+"-handled"}
        async def slow(args):
            invocations.append(("slow",args["value"]))
            slow_started.set()
            await release_slow.wait()
            return {"value":"late"}
        async def malformed(args):
            invocations.append(("malformed",args["value"]))
            return {"not_expected":"bad"}
        server = await ActivepiecesLoopbackServer(
            InteropGate(machine,policy), principal_id="owner",workspace_id="work-1",
            token=(token:=secrets.token_urlsafe(32)), handlers={
                "echo":echo, "slow":slow, "malformed":malformed},
            allowlist={k:frozenset({"value"}) for k in ("echo","slow","malformed")}).start()
        client = ActivepiecesActionClient(InteropGate(machine,policy),server_port=server.port,
                                          token=token,allowed_actions={
            k:frozenset({"value"}) for k in ("echo","slow","malformed")})
        def req(i, action, args, *, work="work-1"):
            return OperationRequest(i,"owner","pieces-machine","activepieces:"+action,
                                    work,i,{"action":action,"arguments":args})
        try:
            assert server._server.sockets[0].getsockname()[0]=="127.0.0.1"
            first=req("op-1","echo",{"value":"hello"})
            accepted=await client.call(first,action="echo",arguments={"value":"hello"})
            assert accepted.operation.state=="SUCCEEDED"
            assert accepted.payload=={"value":"hello-handled"}
            duplicate=await client.call(first,action="echo",arguments={"value":"hello"})
            assert duplicate.duplicate and duplicate.operation.state=="SUCCEEDED"
            assert server.counts["echo"]==1

            bad=req("op-2","echo",{"extra":"denied"})
            assert (await client.call(bad,action="echo",arguments={"extra":"denied"})).operation.state=="FAILED"
            scoped=req("op-3","echo",{"value":"denied"},work="work-2")
            assert (await client.call(scoped,action="echo",arguments={"value":"denied"})).operation.state=="FAILED"
            assert server.counts["echo"]==1

            corrupt=req("op-4","malformed",{"value":"bad"})
            invalid=await client.call(corrupt,action="malformed",arguments={"value":"bad"})
            assert invalid.operation.state=="UNCERTAIN"
            again=await client.call(corrupt,action="malformed",arguments={"value":"bad"})
            assert again.duplicate and again.operation.state=="UNCERTAIN"
            assert server.counts["malformed"]==1

            late=req("op-5","slow",{"value":"slow"})
            call = asyncio.create_task(client.call(
                late,action="slow",arguments={"value":"slow"},timeout=.18))
            try:
                # Timeout must occur AFTER the remote handler started, even
                # when Windows is loaded and socket dispatch is delayed.
                await asyncio.wait_for(slow_started.wait(), 2)
                uncertain=await asyncio.wait_for(call,2)
                assert uncertain.operation.state=="UNCERTAIN"
            finally:
                release_slow.set()
            await asyncio.sleep(.03)
            assert (await client.call(late,action="slow",
                                      arguments={"value":"slow"})).duplicate
            assert server.counts["slow"]==1

            # Auth failure: separate client uses same local host, never a SaaS endpoint.
            wrong=ActivepiecesActionClient(InteropGate(machine,policy),server_port=server.port,
                                            token="wrong"*9,allowed_actions={
                                                "echo":frozenset({"value"})})
            denied=await wrong.call(req("wrong","echo",{"value":"x"}),
                                    action="echo",arguments={"value":"x"})
            assert denied.operation.state=="UNCERTAIN"
            assert server.counts["echo"]==1
            allow=False
            revoke=await client.call(req("op-6","echo",{"value":"revoked"}),
                                     action="echo",arguments={"value":"revoked"})
            assert revoke.operation.state=="FAILED"
            assert server.counts["echo"]==1
            assert invocations==[("echo","hello"),("malformed","bad"),("slow","slow")]
        finally:
            await server.close()
        # After close no implicit fallback to another endpoint.
        allow=True
        failed=await client.call(req("op-7","echo",{"value":"stop"}),
                                 action="echo",arguments={"value":"stop"},timeout=.4)
        assert failed.operation.state=="UNCERTAIN"
    asyncio.run(main())
