"""Disposable Windows installed-daemon soak; never attaches to user terminals."""
from pathlib import Path
import argparse,base64,concurrent.futures,hashlib,json,os,subprocess,sys,time,traceback
ROOT=Path(os.environ.get('SENTRA_SOAK_SOURCE_ROOT') or Path(__file__).resolve().parents[2]).resolve()
if not (ROOT/'sentra_canvas/pty_client.py').is_file():raise ValueError('Soak broker source tree unavailable')
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from sentra_canvas.pty_client import PtyDaemonClient,DaemonPTY
from sentra_canvas.service import Canvas

def run(binary,state,seconds,*,source_daemon=False,correlated_inputs=False):
 state=state.resolve()
 if state.exists():raise ValueError('Choose a new, empty validation directory')
 state.mkdir(parents=True);report={'state':'running','installed_binary':None if source_daemon else str(binary),'daemon_kind':'source' if source_daemon else 'frozen','seconds_requested':seconds,'synthetic_workloads':True,'user_state_used':False}
 report['broker_source_root']=str(ROOT)
 report['broker_source_inputs']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('sentra_canvas/service.py','sentra_canvas/pty_client.py','sentra_canvas/pty_history.py','sentra_canvas/pty_daemon.py','sentra_canvas/terminal_snapshots.py','sentra_canvas/terminal_input_receipts.py','sentra_canvas/shell_requests.py','sentra_canvas/pty_input_effects.py')}
 report['correlated_input_receipts']=correlated_inputs
 output=state/'report.json'
 def save():output.write_text(json.dumps(report,indent=2),encoding='utf-8')
 save();process=None;app=None;client=None;terms=[];start=time.monotonic();stage='startup';last_save=0
 diagnostic_log=(state/'daemon-diagnostics.log').open('x',encoding='utf-8')
 def daemon():
  env={**os.environ,'PYINSTALLER_RESET_ENVIRONMENT':'1','SENTRA_PTY_DAEMON':'1'}
  argv=[str(binary),'--pty-daemon',str(state/'canvas/pty-host')]
  if source_daemon:
   argv=[sys.executable,'-c',"import faulthandler,sys;faulthandler.enable();faulthandler.dump_traceback_later(120,repeat=True);from sentra_canvas.pty_daemon import serve;serve(sys.argv[1])",str(state/'canvas/pty-host')]
  proc=subprocess.Popen(argv,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=diagnostic_log,stderr=diagnostic_log,creationflags=subprocess.CREATE_NO_WINDOW)
  deadline=time.monotonic()+30
  while time.monotonic()<deadline:
   try:return proc,PtyDaemonClient(state/'canvas/pty-host')
   except (OSError,ValueError,KeyError,RuntimeError):
    if proc.poll() is not None:raise RuntimeError('Owned daemon exited; inspect daemon-diagnostics.log')
    time.sleep(.1)
  proc.terminate();proc.wait(10);raise TimeoutError('Frozen daemon startup')
 try:
  os.environ['SENTRA_PTY_DAEMON']='1';process,client=daemon()
  health=client.call('self_test');assert health['functional'] is True
  root=state/'project';root.mkdir();app=Canvas(root,principal='soak-owner',state_dir=state/'canvas')
  ws=app.create_workspace('Soak')['id'];work=Path(app.store.workspace(ws)['path'])
  duration=seconds+120
  for i in range(3):
   stage='create_terminal_'+str(i)
   code="from pathlib import Path;import time,threading,sys;Path('started-%d').open('a').write('once');threading.Thread(target=lambda:[Path('input-%d').open('a').write(x) for x in sys.stdin],daemon=True).start();end=time.monotonic()+%d;n=0\nwhile time.monotonic()<end:\n print('\\x1b[2K\\rTAG%d '+str(n)+' 🦊 界 \\x1b[32mRUN\\x1b[0m',flush=True);n+=1;time.sleep(.05)"%(i,i,duration,i)
   t=app._start(ws,'Soak_'+str(i),'cmd',[sys.executable,'-u','-c',code]);terms.append(t)
  pids={t['id']:app._sessions[t['id']].pty.pid for t in terms};runtime=client.runtime_id;cursors={t['id']:0 for t in terms};checkpoint_cursors={};checkpoint_sequences={};reads=0;bytes_read=0;restarts=0;last_restart=0;checkpoint_reads=0
  assert client.call('health')['capabilities']['ansi_tui_snapshots'] is True,'Packaged snapshot runtime unavailable'
  pending=[]
  for i,t in enumerate(terms):
   pty=app._sessions[t['id']].pty;fields=pty.fields(data=base64.b64encode(('input-once-'+str(i)+'\r').encode()).decode())
   if correlated_inputs:
    assert pty.client.capabilities.get('correlated_input_receipts')==1
    target=app._sessions[t['id']].input_instance_id;key='soak-owner-input-'+str(i);data='input-once-'+str(i)+'\r'
    payload={'terminal_id':t['id'],'data':data,'input_target':target}
    fp=hashlib.sha256(json.dumps(['terminal_input',payload],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    original_call=pty.client.call
    def lost_response(method,fields=None,key=None):
     result=original_call(method,fields,key)
     if method=='write_correlated':raise TimeoutError('injected after exact daemon delivery commit')
     return result
    if i==0:pty.client.call=lost_response
    try:
     value=app.terminal_input(ws,t['id'],data,request_key=key,input_target=target)
     assert i!=0 and value['status']=='delivered'
    except TimeoutError:
     if i!=0:raise
     report['physical_reply_loss_injected']=True
    finally:pty.client.call=original_call
    pending.append((t['id'],key,data,target,fp))
   else:
    # Deliberate duplicate identity is handled by the daemon's existing receipt.
    client.call('write',fields,'soak-input-'+str(i));client.call('write',fields,'soak-input-'+str(i))
  with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
   end=time.monotonic()+seconds
   while time.monotonic()<end:
    stage='reconnect_health'
    connected=PtyDaemonClient(state/'canvas/pty-host');assert connected.runtime_id==runtime
    stage='concurrent_output'
    futures=[pool.submit(connected.call,'output',{'workspace_id':ws,'terminal_id':t['id'],'cursor':cursors[t['id']]}) for t in terms]
    for i,(t,future) in enumerate(zip(terms,futures)):
     v=future.result(timeout=10);text=v['text'];assert v.get('process_live') is True,'Workload exited before acceptance completed';assert v['cursor']>=cursors[t['id']];assert all(('TAG'+str(j)+' ') not in text for j in range(3) if j!=i)
     cursors[t['id']]=v['cursor'];reads+=1;bytes_read+=len(text.encode())
    elapsed=time.monotonic()-start
    if elapsed-last_restart>max(15,seconds/3):
     stage='broker_reopen'
     app.shutdown();app=Canvas(root,principal='soak-owner',state_dir=state/'canvas');assert app._pty_client.runtime_id==runtime
     assert {t['id']:app._sessions[t['id']].pty.pid for t in terms}==pids;restarts+=1;last_restart=elapsed
     if pending:
      from sentra_canvas.terminal_input_receipts import acknowledge
      for index,(ident,key,data,target,fp) in enumerate(pending):
       assert app._sessions[ident].input_instance_id!=target
       observed=app.terminal_input_status(ws,ident,key,fp)
       assert observed['resolved'] and not observed['task_completion_verified']
       if index==0:assert observed['journal_state']=='observed_input'
       assert acknowledge(app,ws,ident,key,fp)['acknowledged']
       assert not app.terminal_output(ws,ident)['input_pending']
       assert app.terminal_input(ws,ident,data,request_key=key,input_target=target)['status']=='delivered'
      report['receipt_observations']=len(pending);report['pending_confirmations_recovered']=True;pending=[]
     report.update(reads=reads,broker_reopens=restarts,elapsed_seconds=round(elapsed,1));save()
    if elapsed-last_save>10:
     stage='checkpoint_observation'
     for t in terms:
      frame=connected.call('checkpoint',{'workspace_id':ws,'terminal_id':t['id']})
      assert frame.get('available') is True,frame
      assert frame['restoration_creates_process'] is False
      packet=frame['checkpoint'];previous=checkpoint_cursors.get(t['id'],-1)
      assert packet['cursor']>previous,'Checkpoint stopped advancing during continuous output'
      assert packet['sequence']>checkpoint_sequences.get(t['id'],-1),'Checkpoint sequence stopped advancing'
      checkpoint_cursors[t['id']]=packet['cursor'];checkpoint_sequences[t['id']]=packet['sequence']
      checkpoint_reads+=1
     assert connected.call('health')['history']['persistence_error'] is None
     report.update(reads=reads,bytes_read=bytes_read,broker_reopens=restarts,checkpoint_reads=checkpoint_reads,checkpoint_cursors=checkpoint_cursors,checkpoint_sequences=checkpoint_sequences,checkpoint_progress_checked=True,elapsed_seconds=round(elapsed,1),stage=stage);save();last_save=elapsed
    time.sleep(.2)
  for i,t in enumerate(terms):
   stage='verify_and_close_'+str(i)
   assert (work/('started-'+str(i))).read_text()=='once';assert (work/('input-'+str(i))).read_text().splitlines()==['input-once-'+str(i)]
   app.terminal_close(ws,t['id'])
  report.update(state='passed',reads=reads,bytes_read=bytes_read,broker_reopens=restarts,checkpoint_reads=checkpoint_reads,concurrent_terminals=3,same_worker_pids=True,duplicate_input_physical_count=1,elapsed_seconds=round(time.monotonic()-start,1),daemon_functional=True)
 except BaseException as exc:
  report.update(state='failed',stage=stage,elapsed_seconds=round(time.monotonic()-start,1),error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc());raise
 finally:
  if app:app.shutdown()
  if client:
   try:
    for row in client.call('inventory'):
     if row['exit_code'] is None:DaemonPTY(client,row['workspace_id'],row['terminal_id'],pid=row['pid'],runtime_id=row['runtime_id']).close()
    client.call('drain');client.call('stop_when_idle')
   except Exception:pass
  if process:
   try:process.wait(12)
   except subprocess.TimeoutExpired:report['forced_owned_daemon_termination']=True;process.terminate();process.wait(10)
  diagnostic_log.close()
  report['owned_daemon_closed']=process is not None and process.poll() is not None;save()
 return report
if __name__=='__main__':
 p=argparse.ArgumentParser(__doc__);mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--binary',type=Path);mode.add_argument('--source-daemon',action='store_true');p.add_argument('--state',type=Path,required=True);p.add_argument('--seconds',type=int,default=300);p.add_argument('--correlated-inputs',action='store_true');a=p.parse_args()
 if os.name!='nt' or not 30<=a.seconds<=3600:p.error('Windows and a duration from 30 to 3600 seconds are required')
 run(a.binary.resolve(strict=True) if a.binary else None,a.state,a.seconds,source_daemon=a.source_daemon,correlated_inputs=a.correlated_inputs)
