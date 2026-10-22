"""Explicit LAN sidecar launcher; never enables a network listener at UI startup."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import queue
import threading
import time
import sys
import uuid
from pathlib import Path
from .broker import read_endpoint
from .instance_lock import InstanceLock
from .mobile_network import host_secret, atomic_json, local_ipv4


def broker_update(endpoint):
    if endpoint is None:
        return {'type': 'broker_update', 'available': False}
    return {'type': 'broker_update', 'available': True,
            'broker': f'http://127.0.0.1:{endpoint.server_port}',
            'bearer': endpoint.secret, 'runtime_id': endpoint.runtime_id}


def supervise_broker(process, state, initial, instance_id=None):
    previous = broker_update(initial)
    while process.poll() is None:
        time.sleep(1)
        if instance_id and stop_requested(state,instance_id):break
        current = broker_update(read_endpoint(state))
        if current != previous:
            process.stdin.write(json.dumps(current) + '\n')
            process.stdin.flush()
            previous = current


def stop_requested(state,instance_id):
    path=Path(state)/'mobile-stop.json'
    try:
        if path.is_symlink() or path.stat().st_size>1024:return False
        return json.loads(path.read_text(encoding='utf-8'))=={'instance_id':instance_id}
    except (OSError,ValueError):return False


def discard_output(output):
    for _ in output:
        pass

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--bind',default='auto');parser.add_argument('--port',type=int,default=5197)
    parser.add_argument('--node',type=Path)
    args=parser.parse_args(argv)
    if args.bind != 'auto' and not local_ipv4(args.bind):raise ValueError('private LAN IPv4 or auto required')
    if not 1 <= args.port <= 65535:raise ValueError('valid LAN listener port required')
    state=args.state.resolve(strict=True);broker=read_endpoint(state)
    if broker is None:raise RuntimeError('authorized Canvas broker not available')
    environment={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP','PATH'}}
    if getattr(sys,'frozen',False):
        from scripts.commander.stage_mobile import validate_mobile_runtime
        runtime=Path(sys.executable).resolve().parent/'sentra-mobile'
        validate_mobile_runtime(runtime)
        command=[str(runtime/'node.exe'),str(runtime/'gateway.mjs')]
    else:
        if args.node is None:raise ValueError('Explicit development Node executable required')
        root=Path(__file__).resolve().parents[1]/'integrations'/'orca-mobile'/'transport'
        tsx=root/'node_modules'/'tsx'/'dist'/'cli.mjs'
        if not tsx.is_file():raise RuntimeError('install transport dependencies first')
        command=[str(args.node.resolve(strict=True)),str(tsx),str(root/'src'/'gateway.ts')]
    lease=InstanceLock(state/'mobile-host.lock')
    process=None
    descriptor=state/'mobile-host.json'
    instance_id=uuid.uuid4().hex
    try:
        config={'bind':args.bind,'port':args.port,**broker_update(broker),'secret_key':host_secret(state),'supervised':True}
        process=subprocess.Popen(command,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8',env=environment,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        process.stdin.write(json.dumps(config)+'\n');process.stdin.flush()
        startup=queue.Queue(maxsize=1)
        threading.Thread(target=lambda:startup.put(process.stdout.readline(8192)),daemon=True).start()
        try:line=startup.get(timeout=10)
        except queue.Empty:raise RuntimeError('mobile gateway startup timed out')
        ready=json.loads(line)
        if not ready.get('ready'):raise RuntimeError('mobile gateway unavailable')
        atomic_json(descriptor,{'endpoint':ready['endpoint'],'public_key':ready['public_key'],
            'pid':ready['pid'],'launcher_pid':process.pid,'protocol_version':1,'bind':ready['bind'],
            'instance_id':instance_id})
        threading.Thread(target=discard_output,args=(process.stdout,),daemon=True).start()
        print('SENTRA Mobile LAN ready; pair and approve in the desktop workspace.',flush=True)
        supervise_broker(process,state,broker,instance_id)
    finally:
        if process is not None:
            try:process.stdin.close()
            except (OSError,ValueError):pass
            if process.poll() is None:
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
        descriptor.unlink(missing_ok=True)
        if stop_requested(state,instance_id):(state/'mobile-stop.json').unlink(missing_ok=True)
        lease.close()



def start_installed_host(state,bind='auto'):
    from .process_lifetime import launch_independent
    if bind!='auto' and not local_ipv4(bind,loopback=False):raise ValueError('Select a private LAN/VPN interface')
    if not getattr(sys,'frozen',False):raise RuntimeError('Use the packaged Canvas to activate the installed mobile gateway')
    from scripts.commander.stage_mobile import validate_mobile_runtime
    validate_mobile_runtime(Path(sys.executable).resolve().parent/'sentra-mobile')
    state=Path(state).resolve();guard=InstanceLock(state/'mobile-start.lock')
    try:
        if host_status_ready(state):return {'started':False,'already_running':True}
        try:owner=InstanceLock(state/'mobile-host.lock')
        except RuntimeError:raise RuntimeError('Mobile gateway still owns this state; inspect its connection before restarting') from None
        else:owner.close()
        launch_independent([sys.executable,'--mobile-host','--state',str(state),'--bind',bind],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if host_status_ready(state):return {'started':True}
            time.sleep(.1)
        raise RuntimeError('Mobile gateway readiness unconfirmed; no duplicate launch was attempted')
    finally:guard.close()

def host_status_ready(state):
    from .mobile_network import host_status
    return host_status(state).get('available') is True


def stop_installed_host(state):
    """Owner-requested listener shutdown, bound to this launcher generation.

    No PID signaling, credential revocation or termination of Dot resources.
    The supervised child closes its sockets when its private stdin reaches EOF.
    """
    state=Path(state).resolve();guard=InstanceLock(state/'mobile-start.lock')
    try:
        descriptor=state/'mobile-host.json'
        if not descriptor.exists():return {'stopped':False,'already_stopped':True}
        if descriptor.is_symlink() or descriptor.stat().st_size>16384:raise ValueError('Invalid mobile launcher descriptor')
        instance=json.loads(descriptor.read_text(encoding='utf-8')).get('instance_id')
        if not isinstance(instance,str) or len(instance)!=32 or any(c not in '0123456789abcdef' for c in instance):
            raise RuntimeError('This mobile host predates graceful shutdown; update it while idle')
        atomic_json(state/'mobile-stop.json',{'instance_id':instance})
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            try:owner=InstanceLock(state/'mobile-host.lock')
            except RuntimeError:time.sleep(.1);continue
            else:
                owner.close()
                if descriptor.exists():raise RuntimeError('Mobile shutdown receipt not confirmed')
                return {'stopped':True,'pairings_preserved':True}
        raise RuntimeError('Mobile shutdown remains unconfirmed; no process was signaled')
    finally:guard.close()


if __name__=='__main__':main()
