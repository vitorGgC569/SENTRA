"""Actual central admission, SQLite Grants and Git; no forged effect context."""
from pathlib import Path
import pytest
from test_shell_dot_features import shell,dot
from test_orca_worktree_manager import git


def test_worktree_machine_uses_existing_grants_and_replays_one_git_effect(shell):
    app,_server,scope,call=shell
    actor=dot(call,'Coder');conversation=call('conversation_create',dot_id=actor['dot_id'])
    root=Path(app.store.workspace(scope['project_id'])['path'])
    git(root,'init');git(root,'config','user.name','SENTRA Test');git(root,'config','user.email','test@localhost')
    (root/'base.txt').write_text('base');git(root,'add','base.txt');git(root,'commit','-m','base')
    base=git(root,'rev-parse','HEAD')
    machine=app.center_configure_machine(scope['project_id'],actor['agent_id'],'git-worktrees',provider_config={'dot_id':actor['dot_id']})
    assert machine['grant_created'] is False and machine['publication_supported'] is True and machine['publication_requires_review'] is True
    runtime=app._runtime();host=app._machine_service();control=runtime.control
    item=control.create_work_item(runtime.run(scope['project_id'])['run_id'],runtime.owner,
        objective='Create one isolated programming workspace',assignee_agent_id=actor['agent_id'],
        required_capabilities=['git:worktree','git:worktree.inspect'],
        metadata={**scope,'workspace_id':scope['project_id'],'machine_id':machine['machine_id'],'conversation_id':conversation['conversation_id']})
    control.start_work_item_execution(item['work_item_id'],runtime.owner,run_id=item['run_id'],agent_id=actor['agent_id'])
    def dispatch(cap,args,ident):
        return host.dispatch(workspace_id=scope['project_id'],work_item_id=item['work_item_id'],
            machine_id=machine['machine_id'],capability_id=cap,operation_id=ident,idempotency_key=ident,arguments=args)
    args={'dot_id':actor['dot_id'],'base_commit':base}
    with pytest.raises(PermissionError):dispatch('git:worktree',args,'git-denied')
    for capability in machine['capabilities']:
        control.authorization.grant(runtime.owner,principal_type='agent',principal_id=actor['agent_id'],
            capability=capability,scope_type='work_item',scope_id=item['work_item_id'])
    result=dispatch('git:worktree',args,'git-approved')
    assert result['state']=='SUCCEEDED',result
    record=result['evidence'];target=Path(record['path'])
    try:
        (target/'base.txt').write_text('worktree only')
        assert dispatch('git:worktree',args,'git-approved')['state']=='SUCCEEDED'
        assert (target/'base.txt').read_text()=='worktree only'
        assert (root/'base.txt').read_text()=='base'
        inspected=dispatch('git:worktree.inspect',{'worktree_id':record['worktree_id']},'git-inspect')
        assert inspected['state']=='SUCCEEDED' and inspected['evidence']['diff_stat']
        # Publication uses a separate reviewed capability and is never implicit.
        assert 'git:publish' in machine['capabilities'] and 'git:push' not in machine['capabilities']
    finally:git(root,'worktree','remove','--force',str(target))
