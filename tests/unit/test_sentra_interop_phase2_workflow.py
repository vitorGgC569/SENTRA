"""Two independent subprocess worker fixtures with concurrent SQLite checkpoints."""
import asyncio
import json
import sys
import time
import pytest

from sentra_runtime.contracts import Capability,Machine,OperationRequest,PolicyDecision
from sentra_interop.gate import InteropGate
from sentra_interop.workflow_bridge import SubagentWorkflowBridge,WorkflowReplayDenied

WORKER=r"""
import json,sys,time
worker=sys.argv[1]
delay=float(sys.argv[2])
start=time.monotonic()
time.sleep(delay)
print(json.dumps({'worker':worker,'result':'ok','start':start,'end':time.monotonic()}),flush=True)
"""


def prepare(tmp_path,auth):
    machine=Machine("wf-machine","agent","alice",(Capability("workflow:step","step"),))
    database=str(tmp_path/"checkpoints.sqlite")
    def bridge():
        return SubagentWorkflowBridge(InteropGate(machine,auth),database=database,
                                      workspace_root=str(tmp_path),workflow_id="wf-A",
                                      work_item_id="work-A",principal_id="alice")
    def op(i,step,work="work-A"):
        return OperationRequest(i,"alice","wf-machine","workflow:step",work,"key-"+i,
                                {"workflow_id":"wf-A","step_id":step,"checkpoint_version":1})
    return bridge,op


def test_two_concurrent_worker_processes_restart_checkpoint_cas(tmp_path):
    async def case():
        def policy(req):
            return PolicyDecision(True,"verified",{
                "principal_ids":["alice"],"work_item_ids":["work-A"]})
        bridge,op=prepare(tmp_path,policy)
        a,b=bridge(),bridge()
        fixture=tmp_path/"worker_fixture.py"
        fixture.write_text(WORKER,encoding="utf-8")
        intervals=[]
        async def worker(label):
            proc=await asyncio.create_subprocess_exec(sys.executable,"-u",str(fixture),
                                                      label,"0.25",cwd=str(tmp_path),env={},
                                                      stdin=asyncio.subprocess.DEVNULL,
                                                      stdout=asyncio.subprocess.PIPE,
                                                      stderr=asyncio.subprocess.DEVNULL)
            try:
                data=await asyncio.wait_for(proc.stdout.readline(),3)
                record=json.loads(data)
                intervals.append((record["start"],record["end"]))
                await asyncio.wait_for(proc.wait(),2)
                assert proc.returncode==0
                return {"worker":record["worker"],"result":record["result"]}
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
        results=await asyncio.gather(
            a.run_step(op("op-1","fetch"),step_id="fetch",
                       effect=lambda:worker("worker-one")),
            b.run_step(op("op-2","analyze"),step_id="analyze",
                       effect=lambda:worker("worker-two")),
        )
        assert [r.operation.state for r in results]==["SUCCEEDED","SUCCEEDED"]
        assert len(intervals)==2
        assert max(x[0] for x in intervals) < min(x[1] for x in intervals)
        restarted=bridge()
        checkpoint=restarted.checkpoint()
        assert checkpoint["schema_version"]==1 and checkpoint["revision"]==4
        assert {s["state"] for s in checkpoint["steps"]}=={"SUCCEEDED"}
        assert all(s["revision"]==1 and len(s["result_sha256"])==64
                   for s in checkpoint["steps"])
        assert restarted.reconcile("fetch").state=="SUCCEEDED"
        called=False
        async def should_not_run():
            nonlocal called
            called=True
            return {"worker":"fake","result":"x"}
        with pytest.raises(WorkflowReplayDenied):
            await restarted.run_step(op("op-1","fetch"),step_id="fetch",
                                     effect=should_not_run)
        assert called is False
    asyncio.run(case())


def test_workflow_concurrent_same_step_dedupe_and_grant_revocation(tmp_path):
    async def case():
        allowed=True
        starts=0
        entered=asyncio.Event()
        release=asyncio.Event()
        def policy(req):
            return PolicyDecision(allowed and req.work_item_id=="work-A","policy")
        bridge,op=prepare(tmp_path,policy)
        a,b=bridge(),bridge()
        async def blocked():
            nonlocal starts
            starts+=1
            entered.set()
            await release.wait()
            return {"worker":"local","result":"may-have-executed"}
        first=asyncio.create_task(a.run_step(op("same","same"),step_id="same",
                                                  effect=blocked))
        await entered.wait()
        async def never():
            raise AssertionError("duplicate worker dispatched")
        with pytest.raises(WorkflowReplayDenied):
            await b.run_step(op("same","same"),step_id="same",effect=never)
        assert starts==1
        allowed=False
        release.set()
        result=await first
        assert result.operation.state=="UNCERTAIN"
        reloaded=bridge()
        assert reloaded.reconcile("same").state=="UNCERTAIN"
        # Revoked operation is denied before replay inspection; once grant
        # returns, durable checkpoint still prevents re-execution.
        assert (await reloaded.run_step(op("same","same"),step_id="same",
                                        effect=never)).operation.state=="FAILED"
        allowed=True
        with pytest.raises(WorkflowReplayDenied):
            await reloaded.run_step(op("same","same"),step_id="same",effect=never)
        allowed=False
        # Distinct operation in a foreign work item never reaches a worker.
        denied=await reloaded.run_step(op("foreign","foreign","work-B"),
                                       step_id="foreign",effect=never)
        assert denied.operation.state=="FAILED"
        assert len(reloaded.checkpoint()["steps"])==1
    asyncio.run(case())


def test_workflow_timeout_unknown_after_restart_and_schema_binding(tmp_path):
    async def case():
        bridge,op=prepare(tmp_path,lambda _: PolicyDecision(True,"test"))
        a=bridge()
        dispatched=0
        async def long_work():
            nonlocal dispatched
            dispatched+=1
            await asyncio.sleep(.25)
            return {"worker":"fixture","result":"late"}
        item=op("timeout","slow")
        result=await a.run_step(item,step_id="slow",effect=long_work,timeout=.025)
        assert result.operation.state=="UNCERTAIN"
        assert dispatched==1
        new_instance=bridge()
        assert new_instance.reconcile("slow").state=="UNCERTAIN"
        with pytest.raises(WorkflowReplayDenied):
            await new_instance.run_step(item,step_id="slow",effect=long_work)
        assert dispatched==1
        pending=op("pending","interrupted")
        new_instance._reserve(pending,"interrupted")
        on_restart=bridge()
        assert on_restart.reconcile("interrupted").state=="UNCERTAIN"
        with pytest.raises(WorkflowReplayDenied):
            await on_restart.run_step(pending,step_id="interrupted",effect=long_work)
        assert on_restart.checkpoint()["revision"]==4
        with pytest.raises(ValueError):
            SubagentWorkflowBridge(a.gate,database=str(tmp_path/"checkpoints.sqlite"),
                                   workspace_root=str(tmp_path),workflow_id="wf-A",
                                   work_item_id="other-work",principal_id="alice")
    asyncio.run(case())
