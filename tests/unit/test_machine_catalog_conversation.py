import asyncio
from types import SimpleNamespace
from sentra_runtime.machine_host import MachineHost


def test_shell_catalog_filters_other_conversations_before_policy_and_exposes_vm_scope():
    calls=[]
    rows=[dict(work_item_id='w-'+cid,run_id='run',assignee_agent_id='agent',objective='VM',
        required_capabilities=['vm:observe'],metadata=dict(workspace_id='workspace',machine_id='vm',conversation_id=cid))
        for cid in ('own','other')]
    host=object.__new__(MachineHost);host.owner='owner'
    host._call=lambda coroutine,**kwargs:asyncio.run(coroutine)
    host.control=SimpleNamespace(list_work_items=lambda *a,**k:{'items':rows},
        durable=SimpleNamespace(run_status=lambda *a,**k:{'state':'RUNNING'}))
    host._inventory={'vm':dict(machine_id='vm',workspace_id='workspace',agent_id='agent',
        kind='virtualbox_vm',capabilities=['vm:observe'])}
    host._factories={'vm':SimpleNamespace(policy=lambda request:calls.append(request.work_item_id) or SimpleNamespace(allowed=True))}
    result=host.task_catalog(workspace_id='workspace',agent_ids={'agent'},conversation_id='own')
    assert calls==['w-own']
    assert [row['conversation_id'] for row in result]==['own']
    calls.clear()
    assert len(host.task_catalog(workspace_id='workspace',agent_ids={'agent'}))==2
    assert calls==['w-own','w-other']
