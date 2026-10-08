"""Actual broker death must kill its owned Windows task and ConPTY descendants."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from sentra_canvas.service import Canvas

pytestmark=pytest.mark.skipif(os.name!="nt",reason="real Windows kernel Job Objects")


def wait(check,timeout=20):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        value=check()
        if value:return value
        time.sleep(.05)
    raise AssertionError("owned broker crash condition did not complete")


def test_real_broker_crash_kills_descendants_and_recovers_only_queued_work(tmp_path):
    child=tmp_path/"child.py"
    child.write_text('''import json,os,sys,time,subprocess
from pathlib import Path
args=sys.argv
kind='conpty' if args[1]=='conpty' else 'task'
root=Path(args[2] if kind=='conpty' else args[args.index('--workspace')+1])
if kind=='task':
 from sentra_core.conversations import ConversationStore
 state=args[args.index('--state-dir')+1];sid=args[args.index('--session-id')+1]
 s=ConversationStore(state);s.open(root,session_id=sid)
 t,_=s.begin_turn(sid,'owned task crash fixture');s.start_tool(sid,t,'W','started_effect.txt|one effect')
 (root/'started_effect.txt').write_text('one effect')
grandchild=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
(root/(kind+'.json')).write_text(json.dumps([os.getpid(),grandchild.pid]))
time.sleep(60)
''',encoding="utf-8")
    parent=tmp_path/"broker_crash.py"
    parent.write_text('''import json,os,sys,time
from pathlib import Path
from sentra_canvas.service import Canvas
root=Path(sys.argv[1]);child=Path(sys.argv[2])
app=Canvas(root,max_task_workers=1)
ws=app.create_workspace('owned_crash')['id'];work=Path(app.store.workspace(ws)['path'])
coordinator=app.create_agent(ws,'coordinator','sentra/model');worker=app.create_agent(ws,'worker','sentra/model')
team=app.create_team(ws,'team',coordinator['id'],[worker['id']])
app._cli_command=lambda args:[sys.executable,'-B',str(child),*args]
running=app.delegate(ws,team['id'],worker['id'],'owned hold','running','sentra-cli',True)
app._start(ws,'owned_tty','cmd',[sys.executable,'-B',str(child),'conpty',str(work)])
queued=app.delegate(ws,team['id'],worker['id'],'[[W|queued_recovery.txt|REAL_QUEUED_RECOVERY]]','queued','sentra-cli',True)
end=time.monotonic()+20
while not all((work/(kind+'.json')).exists() for kind in ('task','conpty')):
 if time.monotonic()>end:raise TimeoutError('children did not start')
 time.sleep(.05)
(root/'ready.json').write_text(json.dumps({'ws':ws,'running':running['id'],'queued':queued['id'],
 'pids':json.loads((work/'task.json').read_text())+json.loads((work/'conpty.json').read_text()),'workspace':str(work)}))
while not (root/'crash_gate').exists():time.sleep(.05)
os._exit(17)
''',encoding="utf-8")
    env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[2])
    process=subprocess.Popen([sys.executable,"-B",str(parent),str(tmp_path),str(child)],
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handles=[];restored=None
    try:
        wait(lambda:(tmp_path/"ready.json").exists())
        info=json.loads((tmp_path/"ready.json").read_text())
        for pid in info["pids"]:
            handle=kernel.OpenProcess(0x00100000,False,pid)
            assert handle and kernel.WaitForSingleObject(handle,0)==258
            handles.append(handle)
        (tmp_path/"crash_gate").touch()
        output,_=process.communicate(timeout=10)
        assert process.returncode==17,output.decode(errors="replace")[:1000]
        assert all(kernel.WaitForSingleObject(handle,5000)==0 for handle in handles)
        restored=Canvas(tmp_path,max_task_workers=1)
        assert restored.store.resource("tasks",info["running"],info["ws"])["status"]=="uncertain"
        path=Path(info["workspace"])/"queued_recovery.txt"
        wait(path.is_file)
        assert path.read_text()=="REAL_QUEUED_RECOVERY"
        wait(lambda:restored.store.resource("tasks",info["queued"],info["ws"])["status"]=="succeeded")
        assert Path(info["workspace"],"started_effect.txt").read_text()=="one effect"
        assert all(t["status"]=="interrupted" for t in restored.store.list_resources("terminals",info["ws"]))
    finally:
        (tmp_path/"crash_gate").touch()
        if process.poll() is None:
            try:process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        if restored:restored.shutdown()
        for handle in handles:kernel.CloseHandle(handle)
