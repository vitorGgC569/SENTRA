"""Opt-in real OpenCode process; no prompt, API key or model account is used."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import pytest
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.machine_host import MachineHost


@pytest.mark.skipif(os.environ.get('SENTRA_TEST_OPENCODE')!='1',reason='explicit pinned OpenCode validation')
def test_real_opencode_acp_session_uses_central_grants(tmp_path,monkeypatch):
    from sentra_interop.acp import ACPStdioTransport
    observed=[];original_request=ACPStdioTransport.request
    async def inspect(self,method,params,timeout):
        try:
            result=await original_request(self,method,params,timeout)
            observed.append((method,result));return result
        except Exception as exc:
            observed.append((method,type(exc).__name__,str(exc)));raise
    monkeypatch.setattr(ACPStdioTransport,'request',inspect)
    integration=Path(__file__).resolve().parents[2]/'integrations'/'opencode'
    binary=integration/'node_modules'/'opencode-windows-x64'/'bin'/'opencode.exe'
    assert subprocess.check_output([str(binary),'--version'],text=True).strip()=='1.19.3'
    wrapper=integration/'acp_host.py'
    checksum=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    control=ControlPlaneService.from_store(tmp_path/'central');owner='opencode-test-owner';agent='opencode-test-agent'
    workspace=tmp_path/'workspace';workspace.mkdir()
    run=control.durable.create_run(owner,workspace=str(workspace))
    control.ensure_agent(run['run_id'],owner,agent_id=agent,role='worker')
    host=MachineHost(control,owner=owner)
    caps=['acp:launch','acp:session','acp:state','acp:load','acp:transport_close']
    try:
        machine=host.configure_interop(workspace_id='project',workspace_root=str(workspace),agent_id=agent,kind='acp',
            provider_config={'enabled':True,'provider_id':'opencode-1.19.3','host_process_consent':True,
                'executable':sys.executable,'executable_sha256':checksum(Path(sys.executable)),
                'args':[str(wrapper),'--binary',str(binary),'--state',str(tmp_path/'opencode-state')],
                'argument_file_pins':{str(wrapper):checksum(wrapper),str(binary):checksum(binary)},'supported_versions':[1],'dialect':'opencode'})
        item=control.create_work_item(run['run_id'],owner,objective='Validate pinned ACP without a model turn',
            assignee_agent_id=agent,required_capabilities=caps,
            metadata={'workspace_id':'project','machine_id':machine['machine_id']})
        control.start_work_item_execution(item['work_item_id'],owner,run_id=run['run_id'],agent_id=agent)
        for cap in caps:control.authorization.grant(owner,principal_type='agent',principal_id=agent,
            capability=cap,scope_type='work_item',scope_id=item['work_item_id'])
        def dispatch(cap,ident):return host.dispatch(workspace_id='project',work_item_id=item['work_item_id'],
            machine_id=machine['machine_id'],capability_id=cap,operation_id=ident,idempotency_key=ident,arguments={'local_id':'pinned-session'})
        assert dispatch('acp:launch','open-process')['state']=='SUCCEEDED'
        opened=dispatch('acp:session','new-session')
        assert opened['state']=='SUCCEEDED',(opened,observed)
        assert dispatch('acp:state','inspect-session')['state']=='SUCCEEDED'
        assert dispatch('acp:transport_close','close-process')['state']=='SUCCEEDED'
        assert dispatch('acp:launch','reopen-process')['state']=='SUCCEEDED'
        assert dispatch('acp:load','load-existing')['state']=='SUCCEEDED'
    finally:host.close();control.durable.close()
