"""Bounded owned subprocess transport for trusted provider helpers, not a shell API."""
from __future__ import annotations
import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path
from .rpa import ExecutorFailure,effect_checkpoint,digest,_WindowsJob


class OwnedProviderRunner:
    def invoke(self,executable,argv,*,input_document,timeout_seconds=30,max_result_bytes=2*1024*1024,
               executable_sha256=None,environment=None,checkpoint=None):
        path=Path(executable)
        if not path.is_absolute() or not path.is_file():raise ExecutorFailure('configured_provider_executable_missing')
        if executable_sha256 is not None and digest(path)!=executable_sha256:raise ExecutorFailure('provider_executable_pin_mismatch')
        if not 0<timeout_seconds<=300 or not 1024<=max_result_bytes<=32*1024*1024:raise ValueError('invalid_provider_limits')
        def check():
            effect_checkpoint()
            if checkpoint is not None:checkpoint()
        check();job=_WindowsJob() if os.name=='nt' else None;process=None
        events=queue.Queue(maxsize=32);overflow=threading.Event()
        try:
            process=subprocess.Popen([str(path),*argv],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env=environment,
                creationflags=0x08000000 if os.name=='nt' else 0,start_new_session=os.name!='nt')
            if job:job.assign(process._handle)
            def reader():
                total=0
                try:
                    while True:
                        line=process.stdout.readline(max_result_bytes+1)
                        if not line:break
                        total+=len(line.encode('utf-8'))
                        if len(line)>max_result_bytes or total>max_result_bytes*2 or not line.endswith('\n'):
                            overflow.set();break
                        try:events.put_nowait(json.loads(line))
                        except (ValueError,queue.Full):overflow.set();break
                finally:
                    try:events.put_nowait({'event':'eof'})
                    except queue.Full:pass
            threading.Thread(target=reader,daemon=True,name='sentra-provider-result').start()
            process.stdin.write(json.dumps(input_document,allow_nan=False)+'\n');process.stdin.flush()
            deadline=time.monotonic()+timeout_seconds
            while time.monotonic()<deadline:
                check()
                if overflow.is_set():raise ExecutorFailure('provider_output_limit',uncertain=True)
                try:message=events.get(timeout=min(.2,max(.001,deadline-time.monotonic())))
                except queue.Empty:continue
                if not isinstance(message,dict):raise ExecutorFailure('provider_result_invalid',uncertain=True)
                if message.get('event')=='checkpoint':
                    check();process.stdin.write('CONTINUE\n');process.stdin.flush()
                elif message.get('event')=='result':
                    if message.get('ok') is not True:raise ExecutorFailure(message.get('code','provider_failed'),
                        uncertain=bool(message.get('uncertain')),evidence=message.get('evidence',{}))
                    process.wait(timeout=max(.001,deadline-time.monotonic()))
                    if process.returncode!=0 or not isinstance(message.get('evidence'),dict):raise ExecutorFailure('provider_exit_invalid',uncertain=True)
                    return message['evidence']
                elif message.get('event')=='eof':raise ExecutorFailure('provider_exited_without_result',uncertain=True)
                else:raise ExecutorFailure('provider_message_invalid',uncertain=True)
            raise ExecutorFailure('provider_deadline_exceeded',uncertain=True)
        finally:
            # Teardown is confined to this new process tree, not a PID allowlist
            # presented as an OS sandbox. Remote operations may remain uncertain.
            if job:job.close()
            elif process is not None and process.returncode is None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            if process is not None:
                if process.poll() is None:process.kill()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:pass
                for stream in (process.stdin,process.stdout):
                    if stream:stream.close()


def declaration(executor,bindings,description):
    from sentra_runtime.contracts import Machine,Capability
    from .discovery import MachineDeclaration
    return MachineDeclaration(Machine(executor.machine_id,executor.kind,executor.owner_principal_id,
        tuple(Capability(b.capability_id,description,'high') for b in bindings)),executor)
