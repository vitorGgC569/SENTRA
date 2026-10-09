"""ACP 26 real stdio E2E trials + durable local replay prevention.

Uses Python fixture from test_sentra_interop_e2e, never external ACP agents.
"""
import asyncio
import hashlib
import json
import sys

import pytest

from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision
from sentra_interop import InteropGate
from sentra_interop.acp_local import ACPLocalLifecycle, ACPLocalLedger, ACPReplayBlocked

from test_sentra_interop_e2e import AGENT_SOURCE


def make_gate():
    machine=Machine("acp-s3-machine","agent","tester",tuple(
        Capability(c,c) for c in ("acp:launch","acp:session","acp:prompt","acp:cancel")))
    def policy(req):
        if req.capability_id=="acp:launch":
            return PolicyDecision(True,"pinned",{
                "executable_paths":[sys.executable],
                "cwd_roots":[req.arguments["cwd"]],
                "argv_sha256":hashlib.sha256(json.dumps(
                    req.arguments["args"],ensure_ascii=False,separators=(",",":")).encode()).hexdigest(),
            })
        return PolicyDecision(True,"local test grant",{
            "principal_ids":["tester"], "work_item_ids":["work-A"]})
    return InteropGate(machine,policy)


def op(i,cap,args):
    return OperationRequest("acp-s3-"+i,"tester","acp-s3-machine",cap,"work-A",
                            "acp-s3-k-"+i,args)


@pytest.mark.parametrize("round_id", range(26))
def test_acp_26_real_stdio_local_lifecycle_cancel_restart_reconcile(tmp_path,round_id):
    async def case():
        name=str(round_id)
        script=tmp_path / "local_acp_agent.py"
        script.write_text(AGENT_SOURCE,encoding="utf-8")
        mode=("roundtrip","cancel","timeout")[round_id % 3]
        trace=tmp_path / "agent-trace.jsonl"
        forbidden=tmp_path / "agent-forbidden.txt"
        argv=("-u",str(script),mode,str(trace),str(forbidden))
        launch=op("launch-"+name,"acp:launch",
                  {"executable":sys.executable,"args":list(argv),"cwd":str(tmp_path)})
        session=op("session-"+name,"acp:session",{"cwd":str(tmp_path)})
        work=op("prompt-"+name,"acp:prompt",{"session_id":"fixture-session","text":"hello"})
        db=str(tmp_path/"acp_receipts.sqlite")
        lifecycle=ACPLocalLifecycle(make_gate(),workspace=str(tmp_path),ledger_path=db)
        first_process=None
        try:
            opened=await lifecycle.start(executable=sys.executable,argv=argv,cwd=str(tmp_path),
                                         launch_request=launch,session_request=session)
            assert opened.operation.state=="SUCCEEDED"
            first_process=lifecycle.transport.process
            assert first_process.pid is not None
            waiting=asyncio.create_task(lifecycle.prompt(work,"hello",
                                                         timeout=.12 if mode=="timeout" else 3))
            streamed=[await anext(lifecycle.updates(timeout=3)),
                      await anext(lifecycle.updates(timeout=3))]
            assert streamed[0]["sessionUpdate"]=="agent_message_chunk"
            assert streamed[1]["sessionUpdate"]=="tool_call"
            assert not forbidden.exists()
            if mode=="cancel":
                cancellation=op("cancel-"+name,"acp:cancel",{"session_id":"fixture-session"})
                uncertain=await lifecycle.cancel(cancellation)
                assert uncertain.state=="UNCERTAIN"
                assert lifecycle.reconcile(cancellation.operation_id).state=="UNCERTAIN"
            result=await asyncio.wait_for(waiting,4)
            expected={"roundtrip":"SUCCEEDED","cancel":"CANCELLED","timeout":"UNCERTAIN"}[mode]
            assert result.operation.state==expected
            assert lifecycle.reconcile(work.operation_id).state==expected
            if mode=="roundtrip":
                logs=[json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
                refusals=[x for x in logs if "error_code" in x]
                assert {row["request_id"] for row in refusals}=={900,901,902,903}
                assert all(row["error_code"]==-32601 for row in refusals)
            assert not forbidden.exists()
        finally:
            await lifecycle.close()
            await lifecycle.close()
        assert first_process is not None and first_process.returncode is not None

        # New supervisor/object/SQLite connection after local process restart
        # must reconcile old execution without ever resending the old intent.
        restarted=ACPLocalLifecycle(make_gate(),workspace=str(tmp_path),ledger_path=db)
        assert restarted.reconcile(work.operation_id).state==expected
        with pytest.raises(ACPReplayBlocked):
            await restarted.prompt(work,"hello") if restarted.adapter else restarted.ledger.reserve(work,"prompt")
        assert restarted.reconcile(launch.operation_id).state=="SUCCEEDED"

        # Record a simulated crash after reservation, before a remote receipt.
        interrupted=op("interrupted-"+name,"acp:prompt",{"session_id":"fixture-session","text":"unsafe-retry"})
        restarted.ledger.reserve(interrupted,"prompt")
        after_crash=ACPLocalLifecycle(make_gate(),workspace=str(tmp_path),ledger_path=db)
        assert after_crash.reconcile(interrupted.operation_id).state=="UNCERTAIN"
        with pytest.raises(ACPReplayBlocked):
            after_crash.ledger.reserve(interrupted,"prompt")
        # Safe fresh op may relaunch after explicit admission; old op is never retried.
        second_trace=tmp_path/"second-trace.jsonl"
        second_argv=("-u",str(script),"roundtrip",str(second_trace),str(forbidden))
        later_launch=op("later-launch-"+name,"acp:launch",
                        {"executable":sys.executable,"args":list(second_argv),"cwd":str(tmp_path)})
        later_open=op("later-open-"+name,"acp:session",{"cwd":str(tmp_path)})
        try:
            later=await after_crash.start(executable=sys.executable,argv=second_argv,
                                          cwd=str(tmp_path),launch_request=later_launch,
                                          session_request=later_open)
            assert later.operation.state=="SUCCEEDED"
            second_proc=after_crash.transport.process
            assert second_proc.pid is not None
            newer=op("later-prompt-"+name,"acp:prompt",
                     {"session_id":"fixture-session","text":"fresh-after-restart"})
            confirmed=await after_crash.prompt(newer,"fresh-after-restart",timeout=3)
            assert confirmed.operation.state=="SUCCEEDED"
            assert after_crash.reconcile(newer.operation_id).state=="SUCCEEDED"
        finally:
            await after_crash.close()
        assert second_proc.returncode is not None and not forbidden.exists()
    asyncio.run(case())
