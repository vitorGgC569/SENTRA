"""Owned one-request UIA worker; also installable INSIDE an interactive guest."""
import json
import sys
import os
import threading
import time
from pathlib import Path
from .uia_semantic import UIAProbeEngine
from .rpa import ExecutorFailure


def main():
    def checkpoint():
        print(json.dumps({'event':'checkpoint','phase':'uia'}),flush=True)
        if sys.stdin.readline().strip()!='CONTINUE':raise ExecutorFailure('uia_parent_checkpoint_not_authorized')
    try:
        document=json.loads(sys.stdin.readline(2*1024*1024))
        result=UIAProbeEngine().perform(document['profile'],document['arguments'],checkpoint)
        print(json.dumps({'event':'result','ok':True,'evidence':result},allow_nan=False),flush=True)
    except Exception as exc:
        print(json.dumps({'event':'result','ok':False,'code':exc.code if isinstance(exc,ExecutorFailure) else 'uia_provider_error',
                          'uncertain':isinstance(exc,ExecutorFailure) and exc.uncertain}),flush=True)


def file_main(root):
    """Task Scheduler InteractiveToken mode INSIDE guest; no network protocol.

    Files are a protected local IPC spool for the host's PowerShell Direct
    session. Every physical step awaits a fresh parent ACK. No generic code API.
    """
    directory=Path(root).resolve(strict=True)
    request=directory/'pending.json';response=directory/'response.jsonl';ack=directory/'ack.json'
    document=json.loads(request.read_text(encoding='utf-8-sig'));job=document['job_id'];deadline=document['deadline_unix']
    if not isinstance(job,str) or len(job)!=32 or time.time()>=deadline or deadline-time.time()>300:
        with response.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'event':'result','ok':False,'code':'guest_clock_skew_or_expired_job','job_id':job})+'\n')
        return
    def watchdog():
        while time.time()<deadline:time.sleep(.1)
        os._exit(94)
    threading.Thread(target=watchdog,daemon=True).start()
    counter=0
    def emit(value):
        value['job_id']=job
        with response.open('a',encoding='utf-8') as stream:stream.write(json.dumps(value,allow_nan=False)+'\n');stream.flush()
    def checkpoint():
        nonlocal counter;counter+=1
        emit({'event':'checkpoint','phase':'uia','sequence':counter})
        limit=min(deadline,time.time()+5)
        while time.time()<limit:
            try:
                value=json.loads(ack.read_text(encoding='utf-8-sig'))
                if value.get('job_id')==job and value.get('sequence')==counter and time.time()<value.get('expires_unix',0):return
            except (FileNotFoundError,ValueError):pass
            time.sleep(.05)
        raise ExecutorFailure('guest_parent_checkpoint_expired')
    try:
        value=UIAProbeEngine().perform(document['profile'],document['arguments'],checkpoint)
        emit({'event':'result','ok':True,'evidence':value})
    except Exception as exc:
        emit({'event':'result','ok':False,'code':exc.code if isinstance(exc,ExecutorFailure) else 'guest_uia_provider_error',
              'uncertain':isinstance(exc,ExecutorFailure) and exc.uncertain})


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--request-dir':file_main(sys.argv[2])
    elif len(sys.argv)==1:main()
    else:raise SystemExit('configured UIA worker arguments required')
