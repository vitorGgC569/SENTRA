from test_shell_dot_features import shell, dot


def test_reading_shell_does_not_refresh_heartbeat_or_resume_paused_agent(shell,monkeypatch):
    app,server,scope,call=shell
    actor=dot(call,'Paused owner')
    control=app._shell_runtime.control
    owner=app._shell_runtime.owner
    control.set_agent_paused(actor['run_id'],owner,agent_id=actor['agent_id'],paused=True)
    before=control.durable.agent_info(actor['agent_id'],owner)
    def no_heartbeat(*args,**kwargs):
        raise AssertionError('Home must not simulate an agent heartbeat')
    monkeypatch.setattr(control,'ensure_agent',no_heartbeat)
    home=call('home')
    assert any(item['dot_id']==actor['dot_id'] for item in home['dots'])
    after=control.durable.agent_info(actor['agent_id'],owner)
    assert after['desired_state']=='WAITING'
    assert after['heartbeat_at']==before['heartbeat_at']


def test_migration_reads_each_bound_dot_once_and_preserves_space(shell,monkeypatch):
    app,server,scope,call=shell
    actors=[dot(call,f'Member {index}') for index in range(12)]
    control=app._shell_runtime.control
    owner=app._shell_runtime.owner
    project=control.shell._project(owner,scope['project_id'])
    import sentra_mcp.services.shell_coordinator as module
    decode=module._decode
    observed=[]
    def count(raw):
        observed.append(raw)
        return decode(raw)
    monkeypatch.setattr(module,'_decode',count)
    assert control.shell._migrate(owner,project)==scope['space_id']
    assert len(observed) <= len(actors)*3  # regression: repeatedly scanning N bindings for each of N agents
    monkeypatch.setattr(module,'_decode',decode)
    result=call('dot_list')['items']
    assert {item['dot_id'] for item in result}=={item['dot_id'] for item in actors}
