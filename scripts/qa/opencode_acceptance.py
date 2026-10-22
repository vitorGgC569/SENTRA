"""Opt-in real OpenCode model turn through central SENTRA admission."""
from pathlib import Path
import argparse,hashlib,json,sys,uuid,time,concurrent.futures,threading
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.machine_host import MachineHost
from sentra_interop.interactions import ProtocolInteractionService

def main():
 p=argparse.ArgumentParser(__doc__);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
 report={'state':'running','provider':'opencode-1.19.3','real_model':True,'automatic_effect_retry':False};path=out/'report.json';host=None;control=None
 report_lock=threading.RLock()
 def save():
  with report_lock:path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 def evidence(value):
  result=value.get('evidence',{});return result.get('payload',result)
 try:
  binary=ROOT/'integrations/opencode/node_modules/opencode-windows-x64/bin/opencode.exe';wrapper=ROOT/'integrations/opencode/acp_host.py';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
  control=ControlPlaneService.from_store(out/'central');owner='acp-qa-owner';agent='acp-qa-worker';workspace=out/'project';workspace.mkdir();run=control.durable.create_run(owner,workspace=str(workspace));control.ensure_agent(run['run_id'],owner,agent_id=agent,role='worker');host=MachineHost(control,owner=owner)
  machine=host.configure_interop(workspace_id='project',workspace_root=str(workspace),agent_id=agent,kind='acp',provider_config={'enabled':True,'provider_id':'opencode-1.19.3','host_process_consent':True,'executable':sys.executable,'executable_sha256':sha(Path(sys.executable)),'args':[str(wrapper),'--binary',str(binary),'--state',str(out/'provider')],'argument_file_pins':{str(wrapper):sha(wrapper),str(binary):sha(binary)},'supported_versions':[1],'dialect':'opencode'})
  caps=['acp:'+s for s in ('launch','session','state','load','config','prompt','events','cancel','transport_close')];item=control.create_work_item(run['run_id'],owner,objective='Real pinned ACP generation and permission acceptance',assignee_agent_id=agent,required_capabilities=caps,metadata={'workspace_id':'project','machine_id':machine['machine_id']});control.start_work_item_execution(item['work_item_id'],owner,run_id=run['run_id'],agent_id=agent)
  for cap in caps:control.authorization.grant(owner,principal_type='agent',principal_id=agent,capability=cap,scope_type='work_item',scope_id=item['work_item_id'])
  def dispatch(cap,**args):
   key=uuid.uuid4().hex
   value=host.dispatch(workspace_id='project',work_item_id=item['work_item_id'],machine_id=machine['machine_id'],capability_id='acp:'+cap,operation_id=key,idempotency_key=key,arguments={'local_id':'qa-session',**args});report.setdefault('operations',[]).append({'kind':cap,'state':value['state'],'operation_id':key});save();return value
  assert dispatch('launch')['state']=='SUCCEEDED';opened=dispatch('session');assert opened['state']=='SUCCEEDED';report['session_id']=evidence(opened)['session_id']
  session=next(iter(host._factories[machine['machine_id']]._sessions.values()))
  original_answer=session.transport._answer_server
  async def observe_reverse(packet):
   report.setdefault('reverse_methods',[]).append(packet.get('method'));save()
   return await original_answer(packet)
  session.transport._answer_server=observe_reverse
  original_collect=session.collect_one
  async def observe_update(request,timeout):
   try:return await original_collect(request,timeout)
   except TimeoutError:raise
   except Exception as exc:
    report['projection_diagnostic']=type(exc).__name__+': '+str(exc)[:200];save();raise
  session.collect_one=observe_update
  state=evidence(dispatch('state'));options=state['config_options'];(out/'model-options.json').write_text(json.dumps(options,indent=2),encoding='utf-8')
  model=next(o for o in options if o.get('category')=='model')
  def values(xs):
   for x in xs:
    if 'options' in x:yield from values(x['options'])
    elif 'value' in x:yield x['value']
  available=list(values(model['options']));chosen=next((v for v in available if v=='opencode/big-pickle'),None) or next((v for v in available if 'free' in v and 'opencode/' in v),None);assert chosen,'No advertised free model'
  report['model']=chosen;assert dispatch('config',config_id=model['id'],value=chosen)['state']=='SUCCEEDED'
  value=dispatch('prompt',message='Reply with exactly SENTRA_ACP_REAL_OK. Do not use any tools.');assert value['state']=='SUCCEEDED',value;assert evidence(value).get('completion_confirmed') is True
  report['generation_confirmed']=True
  events=evidence(dispatch('events'));(out/'events.json').write_text(json.dumps(events,indent=2),encoding='utf-8')
  text=''.join(row['event']['update'].get('content',{}).get('text','') for row in events['items'] if row['event']['update'].get('sessionUpdate')=='agent_message_chunk')
  assert text=='SENTRA_ACP_REAL_OK',text
  interactions=ProtocolInteractionService(control,owner=owner);target=workspace/'approved.txt'
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   cancelled_file=workspace/'cancelled.txt'
   cancelling=pool.submit(dispatch,'prompt',message='Create '+str(cancelled_file)+' containing CANCELLED using your write tool now. Do not ask a question in chat: the tool permission prompt is handled by SENTRA. Do not use shell commands or touch any other file.')
   deadline=time.monotonic()+60
   while not cancelling.done() and time.monotonic()<deadline:
    if interactions.pending(workspace_id='project'):break
    time.sleep(.2)
   assert interactions.pending(workspace_id='project'),'No pending permission to interrupt'
   cancel=dispatch('cancel');assert cancel['state']=='UNCERTAIN',cancel
   stopped=cancelling.result(timeout=30);assert stopped['state']=='CANCELLED',stopped
   assert not cancelled_file.exists();report['cancel_confirmed_by_provider']=True
   writing=pool.submit(dispatch,'prompt',message='Use your file write tool to create exactly '+str(target)+' with the exact text SENTRA_APPROVED_ONCE followed by a newline. Do not run shell commands or touch any other file. Request permission for this single write.')
   deadline=time.monotonic()+110;answered=False
   while not writing.done() and time.monotonic()<deadline:
    for question in interactions.pending(workspace_id='project'):
     tool=question['question'].get('toolCall',{});raw=tool.get('rawInput') or {};locations=tool.get('locations') or []
     paths=[raw[k] for k in ('filePath','file_path','path') if isinstance(raw.get(k),str)]+[loc.get('path') for loc in locations if isinstance(loc,dict) and isinstance(loc.get('path'),str)]
     allowed=bool(paths) and all(Path(value).resolve()==target for value in paths)
     kind='allow_once' if allowed else 'reject_once'
     option=next((o for o in question['question'].get('options',[]) if o.get('kind')==kind),None)
     answer={'outcome':{'outcome':'selected','optionId':option['optionId']}} if option else {'outcome':{'outcome':'cancelled'}}
     interactions.reply(workspace_id='project',interaction_id=question['interaction_id'],answer=answer,request_key=uuid.uuid4().hex)
     answered=answered or allowed
     report.setdefault('permissions',[]).append({'method':question['method'],'allowed':allowed,'paths_match_test_file':allowed});save()
    time.sleep(.15)
   value=writing.result(timeout=15);assert value['state']=='SUCCEEDED',value
   assert answered and target.read_text().strip()=='SENTRA_APPROVED_ONCE','Permission/write evidence missing'
   report['one_shot_permission_verified']=True
  assert dispatch('transport_close')['state']=='SUCCEEDED';assert dispatch('launch')['state']=='SUCCEEDED';assert dispatch('load')['state']=='SUCCEEDED';assert evidence(dispatch('state'))['session_id']==report['session_id']
  with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
   lost_file=workspace/'unconfirmed.txt'
   losing=pool.submit(dispatch,'prompt',message='Create '+str(lost_file)+' containing UNCONFIRMED using your write tool now. Do not ask a question in chat: the tool permission prompt is handled by SENTRA. Do not use shell commands or touch any other file.')
   deadline=time.monotonic()+60
   while not losing.done() and time.monotonic()<deadline:
    if interactions.pending(workspace_id='project'):break
    time.sleep(.2)
   assert interactions.pending(workspace_id='project'),'No active request to disconnect'
   dispatch('transport_close');lost=losing.result(timeout=30)
   assert not lost_file.exists()
   assert lost['state'] in {'UNCERTAIN','FAILED'},lost
   report['transport_loss_state']=lost['state'];report['transport_loss_automatically_replayed']=False

  report.update(state='passed',same_session_loaded=True,scope='Real generation, one-shot permission/write, cancellation, explicit same-session load and transport loss')
 except Exception as exc:
  report.update(state='failed',error=type(exc).__name__+': '+str(exc)[:1500])
  if 'session' in locals():report['transport_diagnostic']=str(session.transport._dead)[:200]
 finally:
  if host:host.close()
  if control:control.durable.close()
  report['owned_processes_closed']=True;save();print(json.dumps(report),flush=True)
 return 0 if report['state']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
