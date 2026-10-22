"""Disposable Windows installed-daemon soak; never attaches to user terminals."""
from pathlib import Path
import argparse,base64,concurrent.futures,json,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from sentra_canvas.pty_client import PtyDaemonClient,DaemonPTY
from sentra_canvas.service import Canvas

def run(binary,state,seconds):
 state=state.resolve()
 if state.exists():raise ValueError('Choose a new, empty validation directory')
 state.mkdir(parents=True);report={'state':'running','installed_binary':str(binary),'seconds_requested':seconds,'synthetic_workloads':True,'user_state_used':False}
 output=state/'report.json'
 def save():output.write_text(json.dumps(report,indent=2),encoding='utf-8')
 save();process=None;app=None;client=None;terms=[];start=time.monotonic()
 def daemon():
  env={**os.environ,'PYINSTALLER_RESET_ENVIRONMENT':'1','SENTRA_PTY_DAEMON':'1'}
  proc=subprocess.Popen([str(binary),'--pty-daemon',str(state/'canvas/pty-host')],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
  deadline=time.monotonic()+30
  while time.monotonic()<deadline:
   try:return proc,PtyDaemonClient(state/'canvas/pty-host')
   except (OSError,ValueError,KeyError,RuntimeError):
    if proc.poll() is not None:raise RuntimeError('Owned frozen daemon exited')
    time.sleep(.1)
  proc.terminate();proc.wait(10);raise TimeoutError('Frozen daemon startup')
 try:
  os.environ['SENTRA_PTY_DAEMON']='1';process,client=daemon()
  health=client.call('self_test');assert health['functional'] is True
  root=state/'project';root.mkdir();app=Canvas(root,principal='soak-owner',state_dir=state/'canvas')
  ws=app.create_workspace('Soak')['id'];work=Path(app.store.workspace(ws)['path'])
  duration=seconds+120
  for i in range(3):
   code="from pathlib import Path;import time,threading,sys;Path('started-%d').open('a').write('once');threading.Thread(target=lambda:[Path('input-%d').open('a').write(x) for x in sys.stdin],daemon=True).start();end=time.monotonic()+%d;n=0\nwhile time.monotonic()<end:\n print('\\x1b[2K\\rTAG%d '+str(n)+' 🦊 界 \\x1b[32mRUN\\x1b[0m',flush=True);n+=1;time.sleep(.05)"%(i,i,duration,i)
   t=app._start(ws,'Soak_'+str(i),'cmd',[sys.executable,'-u','-c',code]);terms.append(t)
  pids={t['id']:app._sessions[t['id']].pty.pid for t in terms};runtime=client.runtime_id;cursors={t['id']:0 for t in terms};reads=0;bytes_read=0;restarts=0;last_restart=0
  for i,t in enumerate(terms):
   pty=app._sessions[t['id']].pty;fields=pty.fields(data=base64.b64encode(('input-once-'+str(i)+'\r').encode()).decode())
   # Deliberate duplicate request identity is handled by the daemon's existing receipt.
   client.call('write',fields,'soak-input-'+str(i));client.call('write',fields,'soak-input-'+str(i))
  with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
   end=time.monotonic()+seconds
   while time.monotonic()<end:
    connected=PtyDaemonClient(state/'canvas/pty-host');assert connected.runtime_id==runtime
    futures=[pool.submit(connected.call,'output',{'workspace_id':ws,'terminal_id':t['id'],'cursor':cursors[t['id']]}) for t in terms]
    for i,(t,future) in enumerate(zip(terms,futures)):
     v=future.result(timeout=10);text=v['text'];assert v['cursor']>=cursors[t['id']];assert all(('TAG'+str(j)+' ') not in text for j in range(3) if j!=i)
     cursors[t['id']]=v['cursor'];reads+=1;bytes_read+=len(text.encode())
    elapsed=time.monotonic()-start
    if elapsed-last_restart>max(15,seconds/3):
     app.shutdown();app=Canvas(root,principal='soak-owner',state_dir=state/'canvas');assert app._pty_client.runtime_id==runtime
     assert {t['id']:app._sessions[t['id']].pty.pid for t in terms}==pids;restarts+=1;last_restart=elapsed
     report.update(reads=reads,broker_reopens=restarts,elapsed_seconds=round(elapsed,1));save()
    time.sleep(.2)
  for i,t in enumerate(terms):
   assert (work/('started-'+str(i))).read_text()=='once';assert (work/('input-'+str(i))).read_text().splitlines()==['input-once-'+str(i)]
   app.terminal_close(ws,t['id'])
  report.update(state='passed',reads=reads,bytes_read=bytes_read,broker_reopens=restarts,concurrent_terminals=3,same_worker_pids=True,duplicate_input_physical_count=1,elapsed_seconds=round(time.monotonic()-start,1),daemon_functional=True)
 except BaseException as exc:
  report.update(state='failed',error=type(exc).__name__+': '+str(exc));raise
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
   except subprocess.TimeoutExpired:process.terminate();process.wait(10)
  report['owned_daemon_closed']=True;save()
 return report
if __name__=='__main__':
 p=argparse.ArgumentParser(__doc__);p.add_argument('--binary',type=Path,required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--seconds',type=int,default=300);a=p.parse_args()
 if os.name!='nt' or not 30<=a.seconds<=3600:p.error('Windows and a duration from 30 to 3600 seconds are required')
 run(a.binary.resolve(strict=True),a.state,a.seconds)
