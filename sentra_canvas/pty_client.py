"""Host-only daemon connection. No automatic retries for physical effects."""
from __future__ import annotations
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from .terminal import TerminalError


class PtyDaemonClient:
    def __init__(self,state_dir):
        from sentra_remote.secrets import unprotect_secret
        self.state=Path(state_dir).resolve()
        record=json.loads((self.state/"pty-endpoint.json").read_text())
        if record.get("protocol_version")!=1 or record.get("state_dir")!=str(self.state) or type(record.get("port")) is not int or not 1<=record["port"]<=65535:
            raise TerminalError("PTY descriptor incompatible")
        self.port=record["port"];self.runtime_id=record["runtime_id"]
        self._token=unprotect_secret(record["protected_token"])
        if len(self._token)<32:raise TerminalError("PTY credential invalid")
        health=self.call("health")
        if health["runtime_id"]!=self.runtime_id or health["pid"]!=record["pid"]:
            raise TerminalError("PTY host identity changed")
        self.capabilities=health.get('capabilities',{})

    def call(self,method,fields=None,key=None):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        req=urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/pty",data=json.dumps({"method":method,"fields":fields or {},"key":key}).encode(),headers={"Authorization":"Bearer "+self._token,"Content-Type":"application/json"})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(req,timeout=8) as response:
            result=json.loads(response.read(256*1024))
        if not result.get("ok"):raise TerminalError("PTY effect unconfirmed")
        return result["value"]

    @classmethod
    def connect_or_start(cls,state_dir):
        from .instance_lock import InstanceLock
        state=Path(state_dir).resolve();state.mkdir(parents=True,exist_ok=True)
        lock=InstanceLock(state/"pty-start.lock")
        try:
            try:return cls(state)
            except (OSError,ValueError,KeyError,RuntimeError):pass
            # A failed observation does not prove the daemon stopped. Its OS
            # lease, unlike a stale descriptor/PID, proves runtime ownership.
            try:owner=InstanceLock(state/'pty-owner.lock')
            except RuntimeError:
                raise TerminalError('PTY daemon still owns this state but is unavailable; no replacement started') from None
            else:owner.close()
            if getattr(sys,"frozen",False):
                argv=[sys.executable,"--pty-daemon",str(state)]
            else:argv=[sys.executable,"-m","sentra_canvas.pty_daemon",str(state)]
            environment={k:v for k,v in os.environ.items() if not k.startswith('_PYI_') and k!='_MEIPASS2'}
            environment['PYINSTALLER_RESET_ENVIRONMENT']='1'
            flags=(subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0
            child=subprocess.Popen(argv,env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags,start_new_session=os.name!='nt')
            # A cold frozen application can take more than five seconds while
            # Windows scans its payload. Poll only the one launched owner;
            # waiting never repeats create/write effects or spawns a fallback.
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                try:return cls(state)
                except (OSError,ValueError,KeyError,RuntimeError):
                    if child.poll() is not None:raise TerminalError('PTY daemon exited during startup; no fallback spawn') from None
                    time.sleep(.1)
            raise TerminalError("PTY daemon did not become available; no fallback spawn")
        finally:lock.close()


class DaemonPTY:
    durable=True
    def __init__(self,client,workspace_id,terminal_id,*,pid,runtime_id):
        self.client=client;self.workspace_id=workspace_id;self.terminal_id=terminal_id
        self.pid=pid;self.runtime_id=runtime_id
        self._closed=False
    @classmethod
    def create(cls,client,ws,ident,argv,cwd,**options):
        value=client.call('create',{'workspace_id':ws,'terminal_id':ident,'argv':argv,'cwd':str(cwd),**options},'create:'+ident)
        return cls(client,ws,ident,pid=value['pid'],runtime_id=value['runtime_id'])
    def fields(self,**extra):return {'workspace_id':self.workspace_id,'terminal_id':self.terminal_id,**extra}
    def output(self,cursor=0):
        value=self.client.call('output',self.fields(cursor=cursor))
        if value['runtime_id']!=self.runtime_id:raise TerminalError('PTY runtime changed; inspect state')
        return value
    def poll(self):return self.output()['exit_code']
    def write(self,data):return self.client.call('write',self.fields(data=base64.b64encode(data).decode()),'write:'+uuid.uuid4().hex)
    def resize(self,cols,rows):return self.client.call('resize',self.fields(cols=cols,rows=rows))
    def close(self,**options):
        result=self.client.call('close',self.fields(exit_input=base64.b64encode(options.get('exit_input',b'exit\r')).decode()),'close:'+self.terminal_id)
        self._closed=True
        return result
