"""Owned runsc CLI worker; no caller-provided shell/code and bounded pipe drain."""
import json
import sys
import time
import subprocess
import threading
from pathlib import Path
from .rpa import digest


def main():
    try:
        config=json.loads(sys.stdin.readline(65537));binary=Path(config['binary'])
        if not binary.is_absolute() or digest(binary)!=config['binary_sha256']:raise RuntimeError('runsc pin mismatch')
        print(json.dumps({'event':'checkpoint','phase':'runsc'}),flush=True)
        if sys.stdin.readline().strip()!='CONTINUE':raise RuntimeError('checkpoint refused')
        process=subprocess.Popen([str(binary),*config['argv']],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            cwd='/',env={'PATH':'/usr/bin:/bin','LANG':'C'})
        buffers=[bytearray(),bytearray()];truncated=[False,False];threads=[]
        def drain(stream,index):
            for data in iter(lambda:stream.read(16384),b''):
                remaining=65536-len(buffers[index]);buffers[index].extend(data[:remaining])
                if len(data)>remaining:truncated[index]=True
            stream.close()
        for i,stream in enumerate((process.stdout,process.stderr)):
            thread=threading.Thread(target=drain,args=(stream,i),daemon=True);thread.start();threads.append(thread)
        process.wait(timeout=config['timeout'])
        for thread in threads:thread.join(timeout=1)
        if any(t.is_alive() for t in threads):raise RuntimeError('runsc streams incomplete')
        if process.returncode!=0:
            print(json.dumps({'event':'result','ok':False,'code':'runsc_native_nonzero','uncertain':True,
                'evidence':{'exit_code':process.returncode,'stderr':buffers[1].decode('utf-8',errors='replace'),'stderr_truncated':truncated[1]}}),flush=True);return
        print(json.dumps({'event':'result','ok':True,'evidence':{'exit_code':process.returncode,
            'stdout':buffers[0].decode('utf-8',errors='replace'),'stderr':buffers[1].decode('utf-8',errors='replace'),
            'stdout_truncated':truncated[0],'stderr_truncated':truncated[1]}}),flush=True)
    except Exception:
        print(json.dumps({'event':'result','ok':False,'code':'runsc_worker_error','uncertain':True}),flush=True)


if __name__=='__main__':main()
