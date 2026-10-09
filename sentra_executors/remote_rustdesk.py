"""Owned, peer-pinned native RustDesk launcher. Stock CLI is unsupported.

Uses the real RustDesk client/wire with source instrumentation from the adjacent
build helper. Local receipts/lease are SENTRA instrumentation, not a guessed
RustDesk RPC API. A verified peer does NOT prove desktop login/frame availability.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .identity_sessions import SessionExecutor,SessionScope,SessionJournal,declare_session_machine
from .rpa import ExecutorFailure,effect_checkpoint,AuthorizedPaths,digest,OwnedProcessHandle,_WindowsJob


@dataclass(frozen=True)
class RustDeskPeerBinding:
    capability_id:str
    peer_alias:str
    peer_id:str
    peer_key_sha256:str
    rendezvous_server:str
    rendezvous_public_key:str
    executable:str
    executable_sha256:str
    build_manifest:str
    runtime_root:str
    paths:AuthorizedPaths
    timeout_seconds:float=20
    lease_seconds:float=3
    actions:tuple[str,...]=('session.list','open','read','reattach','close','evidence.export')
    host_runtime_paths:AuthorizedPaths|None=None
    manifest_paths:AuthorizedPaths|None=None

    def __post_init__(self):
        if (not self.capability_id or not self.peer_alias or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{2,63}',self.peer_id) or
                not re.fullmatch('[0-9a-f]{64}',self.peer_key_sha256) or
                not re.fullmatch('[0-9a-f]{64}',self.executable_sha256) or not self.rendezvous_server or
                not self.rendezvous_public_key or not Path(self.executable).is_absolute() or
                not Path(self.build_manifest).is_absolute() or not Path(self.runtime_root).is_absolute() or
                not 5<=self.timeout_seconds<=60 or not .5<=self.lease_seconds<=5 or
                not set(self.actions)<={'session.list','open','read','reattach','close','evidence.export'}):
            raise ValueError('explicit_pinned_rustdesk_peer_and_native_build_required')
        if self.host_runtime_paths is not None and not isinstance(self.host_runtime_paths,AuthorizedPaths):
            raise ValueError('trusted_host_runtime_paths_required')
        if self.manifest_paths is not None and (not isinstance(self.manifest_paths,AuthorizedPaths) or self.manifest_paths.write_roots):
            raise ValueError('readonly_host_manifest_paths_required')

    @property
    def artifact_paths(self):
        """Legacy paths argument is ONLY export authority, never runtime authority."""
        return self.paths

    @property
    def build_paths(self):
        """Readonly manifest/bundle authority, never usable by artifact output."""
        return self.manifest_paths or self.host_runtime_paths or AuthorizedPaths(
            (str(Path(self.build_manifest).parent),str(Path(self.executable).parent)),())

    def resolve_artifact_output(self,value):
        target=self.artifact_paths.resolve(value,write=True)
        # Also deny overlap when Workspace is an ancestor of durable storage.
        # Separate policy objects alone don't protect nested runtime directories.
        protected=[Path(self.runtime_root).resolve()]
        if self.host_runtime_paths:protected.extend(Path(p) for p in self.host_runtime_paths.write_roots)
        if self.manifest_paths:protected.extend(Path(p) for p in self.manifest_paths.read_roots)
        if (any(target.is_relative_to(root) for root in protected) or
                target in {Path(self.build_manifest).resolve(),Path(self.executable).resolve()}):
            raise ValueError('rustdesk_output_overlaps_protected_host_paths')
        return target

    @property
    def runtime_paths(self):
        # Backwards-compatible standalone callers need not widen export roots.
        # These exact directories are trusted constructor configuration, never
        # request arguments. Host may supply a narrower ACL-backed path policy.
        return self.host_runtime_paths or AuthorizedPaths(
            (str(Path(self.build_manifest).parent),str(Path(self.executable).parent),self.runtime_root),
            (self.runtime_root,))

    @property
    def identity(self):
        return hashlib.sha256(json.dumps([self.capability_id,self.peer_id,self.peer_key_sha256,
            self.rendezvous_server,self.rendezvous_public_key,self.executable,self.executable_sha256,
            self.build_manifest,self.runtime_root,self.actions,self.lease_seconds],separators=(',',':')).encode()).hexdigest()


class RustDeskNativeBackend:
    def __init__(self,journal:SessionJournal):
        self.journal=journal;self.running={};self.lock=threading.RLock()

    def shutdown(self):
        with self.lock:
            for item in list(self.running.values()):self._terminate(item)
            self.running.clear()

    def _build(self,b):
        executable=Path(b.executable)
        if not executable.is_file():raise ExecutorFailure('rustdesk_native_client_missing')
        try:executable=b.build_paths.resolve(str(executable))
        except (ValueError,OSError) as exc:raise ExecutorFailure('rustdesk_host_build_asset_path_denied') from exc
        if digest(executable)!=b.executable_sha256:raise ExecutorFailure('rustdesk_native_executable_pin_mismatch')
        manifest_path=b.build_paths.resolve(b.build_manifest)
        if manifest_path.stat().st_size>65536:raise ExecutorFailure('rustdesk_native_manifest_limit')
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        if (manifest.get('extension')!='sentra-peer-gate-v1' or
                manifest.get('executable_sha256')!=b.executable_sha256 or
                manifest.get('stock_cli_supported') is not False or not manifest.get('source_revision')):
            raise ExecutorFailure('rustdesk_peer_pin_build_not_attested_by_host')
        files=manifest.get('bundle_sha256')
        if not isinstance(files,dict) or not files or len(files)>10000:
            raise ExecutorFailure('rustdesk_native_bundle_pins_required')
        # Windows launcher loads librustdesk.dll: pinning only the launcher
        # cannot prove which native identity gate will execute.
        if os.name=='nt' and 'librustdesk.dll' not in files:
            raise ExecutorFailure('rustdesk_native_library_pin_required')
        root=executable.parent.resolve(strict=True)
        for name,expected in files.items():
            if not isinstance(name,str) or not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):
                raise ExecutorFailure('rustdesk_native_bundle_manifest_invalid')
            relative=Path(name)
            if relative.is_absolute() or '..' in relative.parts:raise ExecutorFailure('rustdesk_native_bundle_path_denied')
            path=(root/relative).resolve(strict=True)
            try:path=b.build_paths.resolve(str(path))
            except (ValueError,OSError) as exc:raise ExecutorFailure('rustdesk_host_build_asset_path_denied') from exc
            if not path.is_relative_to(root) or not path.is_file() or digest(path)!=expected:
                raise ExecutorFailure('rustdesk_native_bundle_pin_mismatch',evidence={'file':name})
        return manifest

    def _lease(self,b,row,directory):
        effect_checkpoint()
        path=directory/'lease.json';tmp=directory/'lease.next'
        b.runtime_paths.resolve(str(path),write=True);b.runtime_paths.resolve(str(tmp),write=True)
        data={'session_id':row['id'],'scope_sha256':row['scope'],
              'expires_unix_ms':int((time.time()+b.lease_seconds)*1000)}
        tmp.write_text(json.dumps(data),encoding='utf-8');os.replace(tmp,path)

    def _receipt(self,b,row,process,directory):
        path=directory/'receipt.json'
        if not path.is_file():return {'state':'STARTING','peer_authenticated':False,'desktop_login_asserted':False}
        if path.stat().st_size>4096:raise ExecutorFailure('rustdesk_native_receipt_limit')
        value=json.loads(path.read_text(encoding='utf-8'))
        expected={'extension':'sentra-peer-gate-v1','session_id':row['id'],'scope_sha256':row['scope'],
                  'peer_id':b.peer_id,'peer_key_sha256':b.peer_key_sha256,'native_pid':process.pid,
                  'peer_authenticated':True,'state':'PEER_VERIFIED','desktop_login_asserted':False}
        if value!=expected:raise ExecutorFailure('rustdesk_native_peer_receipt_mismatch')
        return value

    def _terminate(self,item):
        process,handle,job,directory=item
        # Stop only this retained kernel handle/job; no pkill/taskkill by name.
        # On POSIX don't reap the leader before killing its new process group:
        # an unreaped PID cannot have been reused by an unrelated process.
        if job:handle.terminate();job.close()
        elif process.returncode is None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            handle.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:pass
        handle.close()

    def run(self,b,a):
        with self.lock:
            scope,action=a['_scope'],a['action']
            if action=='session.list':return self.journal.list(scope,'rustdesk',b.identity,limit=a.get('limit',64))
            if action=='open':
                prior=self.journal.reserve_effect(a['_operation_id'],scope,a)
                if prior is not None:return prior
                manifest=self._build(b)
                root=b.runtime_paths.resolve(str(Path(b.runtime_root)/'new-session-placeholder'),write=True).parent
                row=self.journal.create(scope,'rustdesk',b.identity,b.peer_id,
                    {'peer_alias':b.peer_alias,'peer_key_sha256':b.peer_key_sha256,
                     'source_revision':manifest['source_revision'],'resource_kind':'owned-native-client'},state='STARTING')
                directory=root/row['id'];effect_checkpoint();directory.mkdir(mode=0o700)
                profile=directory/'profile';profile.mkdir(mode=0o700)
                config={'peer_id':b.peer_id,'peer_key_sha256':b.peer_key_sha256,'rendezvous_server':b.rendezvous_server,
                    'rendezvous_key':b.rendezvous_public_key,'profile':str(profile),'receipt':str(directory/'receipt.json'),
                    'lease':str(directory/'lease.json'),'session_id':row['id'],'scope_sha256':scope}
                cfg=directory/'native.json';cfg.write_text(json.dumps(config),encoding='utf-8')
                self._lease(b,row,directory)
                env=dict(os.environ,SENTRA_RUSTDESK_CONFIG=str(cfg))
                job=_WindowsJob() if os.name=='nt' else None
                process=handle=None
                try:
                    effect_checkpoint()
                    process=subprocess.Popen([b.executable,'--connect',b.peer_id],env=env,cwd=directory,
                        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        start_new_session=os.name!='nt',creationflags=0x08000000 if os.name=='nt' else 0)
                    handle=OwnedProcessHandle(process.pid)
                    if job:job.assign(handle.handle)
                    self.running[row['id']]=(process,handle,job,directory)
                    metadata=dict(row['metadata'],native_pid=process.pid,runtime_directory=str(directory))
                    self.journal.update(row,metadata=metadata)
                    deadline=time.monotonic()+b.timeout_seconds-2
                    while time.monotonic()<deadline:
                        effect_checkpoint();self._lease(b,row,directory)
                        if process.poll() is not None:raise ExecutorFailure('rustdesk_owned_process_exited_before_peer_verification')
                        receipt=self._receipt(b,row,process,directory)
                        if receipt.get('peer_authenticated'):
                            self.journal.append(row,'identity',json.dumps(receipt).encode())
                            self.journal.update(row,state='PEER_VERIFIED')
                            result={'session_id':row['id'],'peer_alias':b.peer_alias,'peer_authenticated':True,
                                'peer_key_sha256':b.peer_key_sha256,'desktop_login_asserted':False,
                                'control_api_available':False,'lease_seconds':b.lease_seconds}
                            self.journal.complete_effect(a['_operation_id'],result);return result
                        time.sleep(.05)
                    raise ExecutorFailure('rustdesk_peer_verification_timeout',uncertain=True,evidence={'session_id':row['id']})
                except Exception:
                    if row['id'] in self.running:self._terminate(self.running.pop(row['id']))
                    else:
                        if handle:handle.terminate();handle.close()
                        if job:job.close()
                        if process is not None and process.poll() is None:process.kill()
                    raise
            row=self.journal.get(a['session_id'],scope,'rustdesk',b.identity)
            if action=='evidence.export':return {'artifact':self.journal.export(row,b.artifact_paths,str(b.resolve_artifact_output(a['output'])))}
            item=self.running.get(row['id'])
            if action=='close':
                effect_checkpoint()
                if item is not None:self._terminate(item);self.running.pop(row['id'],None)
                self.journal.update(row,state='CLOSED')
                return {'session_id':row['id'],'owned_client_closed':item is not None,'unrelated_client_affected':False}
            if item is None:
                # Kill-on-job-close/native lease expiry means a host restart does
                # not authorize reusing a cached PID or resurrecting a session.
                raise ExecutorFailure('rustdesk_native_process_not_reattachable_open_new_session')
            process,handle,job,directory=item
            if process.poll() is not None:self.journal.update(row,state='DISCONNECTED');raise ExecutorFailure('rustdesk_owned_client_disconnected')
            self._lease(b,row,directory);receipt=self._receipt(b,row,process,directory)
            if not receipt.get('peer_authenticated'):raise ExecutorFailure('rustdesk_peer_verification_receipt_missing')
            if action=='reattach':self.journal.update(row,state='PEER_VERIFIED',new_epoch=True)
            return dict(self.journal.read(row,after=a.get('after',0)),session_id=row['id'],
                identity_last_verified=True,current_transport_state='UNKNOWN',
                desktop_login_asserted=False,native_process_alive=True,
                automatic_native_reconnect_remains_pinned=True,lease_seconds=b.lease_seconds)


class RustDeskExecutor(SessionExecutor):
    kind='rustdesk'
    def __init__(self,*,machine_id,owner_principal_id,bindings,journal,policy=None,backend=None):
        if len({b.capability_id for b in bindings})!=len(bindings):raise ValueError('duplicate_rustdesk_capability')
        super().__init__(machine_id=machine_id,owner_principal_id=owner_principal_id,
            bindings={b.capability_id:b for b in bindings},policy=policy)
        self.backend=backend or RustDeskNativeBackend(journal)

    def _validate(self,request,b):
        a=dict(request.arguments);action=a.get('action')
        if type(action) is not str or action not in b.actions:raise ValueError('rustdesk_action_denied')
        fields={'session.list':{'limit'},'read':{'after'},'evidence.export':{'output'}}.get(action,set())
        if set(a)-({'action'}|fields|({'session_id'} if action not in {'open','session.list'} else set())):
            raise ValueError('rustdesk_caller_cannot_supply_remote_id_key_endpoint_or_executable')
        if action not in {'open','session.list'} and (type(a.get('session_id')) is not str or not a['session_id']):raise ValueError('bound_rustdesk_session_required')
        if 'limit' in a and (type(a['limit']) is not int or not 1<=a['limit']<=100):raise ValueError('bounded_session_list_required')
        if 'after' in a and (type(a['after']) is not int or a['after']<0):raise ValueError('invalid_cursor')
        if action=='evidence.export':
            path=b.resolve_artifact_output(a.get('output'))
            if path.suffix.lower()!='.json':raise ValueError('json_evidence_required')
            a['output']=str(path)
        a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id
        return json.loads(json.dumps(a,allow_nan=False))

    def _run(self,b,a):return self.backend.run(b,a)


def declare_rustdesk_machine(*,machine_id,owner_principal_id,bindings,journal,policy,backend=None):
    executor=RustDeskExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,
        bindings=bindings,journal=journal,policy=policy,backend=backend)
    return declare_session_machine(executor,bindings,'Configured native RustDesk peer identity gate and ownership')
