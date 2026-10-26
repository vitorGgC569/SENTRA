"""Owned, peer-pinned native RustDesk launcher. Stock CLI is unsupported.

Uses the real RustDesk client/wire with source instrumentation from the adjacent
build helper. Local receipts/lease are SENTRA instrumentation, not a guessed
RustDesk RPC API. A verified peer does NOT prove desktop login/frame availability.
"""
from __future__ import annotations

from typing import Any
import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass,field
from pathlib import Path
from sentra_remote.windows_paths import filesystem_path

from .identity_sessions import SessionExecutor,SessionScope,SessionJournal,declare_session_machine
from .rpa import ExecutorFailure,effect_checkpoint,AuthorizedPaths,digest,OwnedProcessHandle,_WindowsJob


class _PopenOwnedHandle:
    """Popen retains the original Windows process handle until cleanup."""
    def __init__(self, process): self.process = process
    def terminate(self): self.process.kill()
    def close(self): pass


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
    login_credential:object=field(default=None,repr=False,compare=False)
    allowed_input:tuple[str,...]=()
    allowed_keycodes:tuple[int,...]=()

    def __post_init__(self):
        if (not self.capability_id or not self.peer_alias or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{2,63}',self.peer_id) or
                not re.fullmatch('[0-9a-f]{64}',self.peer_key_sha256) or
                not re.fullmatch('[0-9a-f]{64}',self.executable_sha256) or not self.rendezvous_server or
                not self.rendezvous_public_key or not Path(self.executable).is_absolute() or
                not Path(self.build_manifest).is_absolute() or not Path(self.runtime_root).is_absolute() or
                not 5<=self.timeout_seconds<=60 or not .5<=self.lease_seconds<=5 or
                not set(self.actions)<={'session.list','open','read','reattach','close','evidence.export',
                    'login','desktop.status','frame','input.key','input.mouse'}):
            raise ValueError('explicit_pinned_rustdesk_peer_and_native_build_required')
        if (not set(self.allowed_input)<={'key','mouse'} or
                any(type(code) is not int or not 0<=code<=65535 for code in self.allowed_keycodes) or
                len(self.allowed_keycodes)>1024 or
                self.login_credential is not None and not callable(self.login_credential)):
            raise ValueError('explicit_rustdesk_input_channels_and_credential_required')
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
            self.build_manifest,self.runtime_root,self.actions,self.lease_seconds,self.allowed_input,
            self.allowed_keycodes],separators=(',',':')).encode()).hexdigest()


class RustDeskNativeBackend:
    def __init__(self,journal:SessionJournal):
        self.journal=journal;self.running: dict[str, Any] = {};self.lock=threading.RLock()

    def shutdown(self):
        with self.lock:
            for ident,item in list(self.running.items()):
                self._terminate(item)
                self.running.pop(ident,None)

    def _build(self,b):
        executable=Path(b.executable)
        if not Path(filesystem_path(executable)).is_file():raise ExecutorFailure('rustdesk_native_client_missing')
        try:executable=b.build_paths.resolve(str(executable))
        except (ValueError,OSError) as exc:raise ExecutorFailure('rustdesk_host_build_asset_path_denied') from exc
        if digest(executable)!=b.executable_sha256:raise ExecutorFailure('rustdesk_native_executable_pin_mismatch')
        manifest_path=b.build_paths.resolve(b.build_manifest)
        if Path(filesystem_path(manifest_path)).stat().st_size>65536:raise ExecutorFailure('rustdesk_native_manifest_limit')
        manifest=json.loads(Path(filesystem_path(manifest_path)).read_text(encoding='utf-8'))
        if (manifest.get('extension')!='sentra-peer-gate-v1' or
                manifest.get('executable_sha256')!=b.executable_sha256 or
                manifest.get('stock_cli_supported') is not False or not manifest.get('source_revision')):
            raise ExecutorFailure('rustdesk_peer_pin_build_not_attested_by_host')
        if (set(b.actions)&{'login','desktop.status','frame','input.key','input.mouse'} and
                manifest.get('control_extension')!='sentra-desktop-control-v1'):
            raise ExecutorFailure('rustdesk_desktop_control_native_build_required')
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
            from sentra_remote.windows_paths import resolved_path
            path=resolved_path(root/relative,strict=True)
            try:path=b.build_paths.resolve(str(path))
            except (ValueError,OSError) as exc:raise ExecutorFailure('rustdesk_host_build_asset_path_denied') from exc
            if not path.is_relative_to(root) or not Path(filesystem_path(path)).is_file() or digest(path)!=expected:
                raise ExecutorFailure('rustdesk_native_bundle_pin_mismatch',evidence={'file':name})
        return manifest

    def _lease(self,b,row,directory):
        effect_checkpoint()
        from sentra_runtime.effect_boundary import current_effect_context
        context=current_effect_context.get()
        path=directory/'lease.json';tmp=directory/'lease.next'
        b.runtime_paths.resolve(str(path),write=True);b.runtime_paths.resolve(str(tmp),write=True)
        data={'session_id':row['id'],'scope_sha256':row['scope'],
              'expires_unix_ms':int((time.time()+b.lease_seconds)*1000),
              'operation_id':context.request.operation_id if context is not None else None}
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
        deadline=time.monotonic()+3
        if job:
            try:
                job.terminate()
                # Also terminate the retained process if assignment failed;
                # this is harmless if the Job already terminated it.
                handle.terminate()
            except Exception as exc:
                raise ExecutorFailure('rustdesk_owned_process_stop_unconfirmed',uncertain=True) from exc
        elif process.returncode is None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            handle.terminate()
        try:exit_code=process.wait(timeout=max(0,deadline-time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            # Keep the retained process handle and entry. The host must retain
            # physical exclusion until an owner can establish the outcome.
            raise ExecutorFailure('rustdesk_owned_process_stop_unconfirmed',uncertain=True) from exc
        if type(exit_code) is not int or process.returncode is None:
            raise ExecutorFailure('rustdesk_owned_process_stop_unconfirmed',uncertain=True)
        if job:
            try:
                while job.active_processes():
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('owned process tree still active')
                    time.sleep(min(.05,remaining))
            except Exception as exc:
                raise ExecutorFailure('rustdesk_owned_process_stop_unconfirmed',uncertain=True) from exc
            job.close()
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
                controls=directory/'control';controls.mkdir(mode=0o700)
                frames=directory/'frames';frames.mkdir(mode=0o700)
                config={'peer_id':b.peer_id,'peer_key_sha256':b.peer_key_sha256,'rendezvous_server':b.rendezvous_server,
                    'rendezvous_key':b.rendezvous_public_key,'profile':str(profile),'receipt':str(directory/'receipt.json'),
                    'lease':str(directory/'lease.json'),'session_id':row['id'],'scope_sha256':scope,
                    'control_root':str(controls),'frame_root':str(frames)}
                cfg=directory/'native.json';cfg.write_text(json.dumps(config),encoding='utf-8')
                self._lease(b,row,directory)
                env=dict(os.environ,SENTRA_RUSTDESK_CONFIG=str(cfg))
                job=_WindowsJob() if os.name=='nt' else None
                process=handle=None
                try:
                    effect_checkpoint()
                    process=subprocess.Popen([b.executable,'--connect',b.peer_id],env=env,cwd=directory,
                        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        start_new_session=os.name!='nt',creationflags=0x08000004 if os.name=='nt' else 0)
                    if job:
                        # Register immediately, even if obtaining a separate handle
                        # or assignment fails, so failed cleanup remains retryable.
                        self.running[row['id']]=(process,_PopenOwnedHandle(process),job,directory)
                    handle=OwnedProcessHandle(process.pid)
                    self.running[row['id']]=(process,handle,job,directory)
                    if job:job.assign_suspended_pid(process.pid)
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
                                'control_api_available':manifest.get('control_extension')=='sentra-desktop-control-v1',
                                'lease_seconds':b.lease_seconds}
                            self.journal.complete_effect(a['_operation_id'],result);return result
                        time.sleep(.05)
                    raise ExecutorFailure('rustdesk_peer_verification_timeout',uncertain=True,evidence={'session_id':row['id']})
                except Exception:
                    if row['id'] in self.running:
                        self._terminate(self.running[row['id']]);self.running.pop(row['id'],None)
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
            if action in {'login','desktop.status','frame','input.key','input.mouse'}:
                return self._desktop(b,a,row,item)
            if action=='reattach':self.journal.update(row,state='PEER_VERIFIED',new_epoch=True)
            return dict(self.journal.read(row,after=a.get('after',0)),session_id=row['id'],
                identity_last_verified=True,current_transport_state='UNKNOWN',
                desktop_login_asserted=False,native_process_alive=True,
                automatic_native_reconnect_remains_pinned=True,lease_seconds=b.lease_seconds)

    def _desktop_status(self,b,row,item):
        process,_,_,directory=item
        path=b.runtime_paths.resolve(str(directory/'control'/'desktop.json'),write=True)
        if not path.is_file():return {'desktop_login_verified':False}
        if path.stat().st_size>4096:raise ExecutorFailure('rustdesk_desktop_status_byte_limit')
        value=json.loads(path.read_text(encoding='utf-8'))
        if any(value.get(k)!=v for k,v in {'session_id':row['id'],'scope_sha256':row['scope'],
            'native_pid':process.pid,'desktop_login_verified':True}.items()):
            raise ExecutorFailure('rustdesk_desktop_session_identity_mismatch')
        observed=value.get('observed_unix_ms')
        if type(observed) is not int or not 0<=time.time()*1000-observed<=b.lease_seconds*1000+1000:
            return {'desktop_login_verified':False,'reason':'native_connection_heartbeat_stale'}
        return value

    def _desktop(self,b,a,row,item):
        process,_,_,directory=item;action=a['action']
        if action=='desktop.status':
            return dict(self._desktop_status(b,row,item),session_id=row['id'],native_process_alive=process.poll() is None)
        if action=='frame':return self._frame(b,a,row,item)
        prior=self.journal.reserve_effect(a['_operation_id'],row['scope'],a)
        if prior is not None:return prior
        root=directory/'control';pending=b.runtime_paths.resolve(str(root/'input.json'),write=True)
        if pending.exists() or (root/'claimed-input.json').exists():
            raise ExecutorFailure('rustdesk_native_input_pending_requires_reconciliation',uncertain=True)
        operation=a['_operation_id']
        if not re.fullmatch('[A-Za-z0-9_-]{1,128}',operation):raise ExecutorFailure('rustdesk_native_operation_id_invalid')
        payload={k:a[k] for k in ('keycode','down','mask','x','y') if k in a}
        payload.update(operation_id=operation,action=action,session_id=row['id'],scope_sha256=row['scope'],
                       expires_unix_ms=int((time.time()+min(4,b.lease_seconds))*1000))
        if action=='login':
            if b.login_credential is None:raise ExecutorFailure('rustdesk_login_credential_not_configured')
            password=b.login_credential()
            if not isinstance(password,str) or not password or len(password)>4096:raise ExecutorFailure('rustdesk_login_credential_unavailable')
            payload['password']=password
        elif not self._desktop_status(b,row,item).get('desktop_login_verified'):
            raise ExecutorFailure('rustdesk_desktop_login_required_before_input')
        temporary=b.runtime_paths.resolve(str(root/'input.next'),write=True)
        effect_checkpoint();temporary.write_text(json.dumps(payload),encoding='utf-8');os.replace(temporary,pending)
        received=b.runtime_paths.resolve(str(root/(operation+'.json')),write=True)
        try:
            return self._wait_input_receipt(b,a,row,item,received)
        finally:
            # Credential IPC is transient. Only this operation's own packet may
            # be removed; a native-owned claimed request stays UNCERTAIN until
            # that retained process is known to have exited.
            candidates=[pending,temporary]
            if process.poll() is not None:candidates.append(root/'claimed-input.json')
            for path in candidates:
                try:
                    path=b.runtime_paths.resolve(str(path),write=True)
                    if path.is_file() and path.stat().st_size<=16384:
                        document=json.loads(path.read_text(encoding='utf-8'))
                        if document.get('operation_id')==operation:path.unlink()
                except (OSError,ValueError):pass

    def _wait_input_receipt(self,b,a,row,item,received):
        process,_,_,directory=item;action=a['action'];operation=a['_operation_id']
        deadline=time.monotonic()+b.timeout_seconds-2
        while time.monotonic()<deadline:
            self._lease(b,row,directory)
            if process.poll() is not None:raise ExecutorFailure('rustdesk_native_input_process_lost',uncertain=True)
            if received.is_file():
                if received.stat().st_size>4096:raise ExecutorFailure('rustdesk_input_receipt_byte_limit',uncertain=True)
                value=json.loads(received.read_text(encoding='utf-8'))
                expected={'session_id':row['id'],'scope_sha256':row['scope'],'operation_id':operation,
                          'native_pid':process.pid,'action':action,'sent':True}
                if any(value.get(k)!=v for k,v in expected.items()):
                    raise ExecutorFailure('rustdesk_input_receipt_invalid_or_send_failed',uncertain=True)
                if action=='login' and not self._desktop_status(b,row,item).get('desktop_login_verified'):
                    time.sleep(.05);continue
                self.journal.append(row,'native-input-receipt',json.dumps(value).encode())
                self.journal.complete_effect(operation,value)
                return dict(value,desktop_login_verified=action=='login',input_values_recorded=False)
            time.sleep(.05)
        raise ExecutorFailure('rustdesk_native_input_receipt_timeout',uncertain=True,evidence={'session_id':row['id']})

    def _frame(self,b,a,row,item):
        try:from PIL import Image
        except ImportError as exc:raise ExecutorFailure('rustdesk_frame_provider_missing_pillow') from exc
        from .rpa import atomic_output
        process,_,_,directory=item;root=directory/'frames'
        gate=b.runtime_paths.resolve(str(root/'capture.json'),write=True)
        started=int(time.time()*1000);deadline=time.monotonic()+b.timeout_seconds-2
        try:
            while time.monotonic()<deadline:
                self._lease(b,row,directory)
                effect_checkpoint();gate.write_text(json.dumps({'expires_unix_ms':int((time.time()+min(4,b.lease_seconds))*1000)}),encoding='utf-8')
                manifest=b.runtime_paths.resolve(str(root/'frame.json'),write=True)
                if manifest.is_file() and manifest.stat().st_size<=4096:
                    value=json.loads(manifest.read_text(encoding='utf-8'))
                    if value.get('captured_unix_ms',0)>=started:
                        if any(value.get(k)!=v for k,v in {'session_id':row['id'],'scope_sha256':row['scope'],'native_pid':process.pid}.items()):
                            raise ExecutorFailure('rustdesk_frame_identity_mismatch')
                        rawpath=b.runtime_paths.resolve(str(root/'frame.raw'))
                        if rawpath.stat().st_size>64*1024*1024:raise ExecutorFailure('rustdesk_frame_byte_limit')
                        raw=rawpath.read_bytes()
                        if len(raw)!=value['bytes'] or hashlib.sha256(raw).hexdigest()!=value['sha256']:
                            time.sleep(.05);continue  # Concurrent next frame; read-only retry.
                        width,height=value['width'],value['height']
                        if type(width) is not int or type(height) is not int or not 1<=width<=8192 or not 1<=height<=8192 or value['format'] not in {'RGBA','BGRA'}:
                            raise ExecutorFailure('rustdesk_frame_dimensions_or_format_invalid')
                        stride=len(raw)//height
                        if len(raw)%height or not width*4<=stride<=width*4+4096:raise ExecutorFailure('rustdesk_frame_stride_invalid')
                        image=Image.frombytes('RGBA',(width,height),raw,'raw',value['format'],stride,1)
                        artifact=atomic_output(b.artifact_paths,a['output'],lambda p:image.save(p,format='PNG'),
                            lambda p:Image.open(p).verify(),max_output_bytes=64*1024*1024)
                        return {'artifact':artifact,'session_id':row['id'],'width':width,'height':height,
                                'desktop_login_verified':self._desktop_status(b,row,item).get('desktop_login_verified',False)}
                time.sleep(.05)
            raise ExecutorFailure('rustdesk_native_decoded_frame_timeout')
        finally:
            gate.unlink(missing_ok=True)


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
        fields={'session.list':{'limit'},'read':{'after'},'evidence.export':{'output'},'frame':{'output'},
                'input.key':{'keycode','down'},'input.mouse':{'mask','x','y'}}.get(action,set())
        if set(a)-({'action'}|fields|({'session_id'} if action not in {'open','session.list'} else set())):
            raise ValueError('rustdesk_caller_cannot_supply_remote_id_key_endpoint_or_executable')
        if action not in {'open','session.list'} and (type(a.get('session_id')) is not str or not a['session_id']):raise ValueError('bound_rustdesk_session_required')
        if 'limit' in a and (type(a['limit']) is not int or not 1<=a['limit']<=100):raise ValueError('bounded_session_list_required')
        if 'after' in a and (type(a['after']) is not int or a['after']<0):raise ValueError('invalid_cursor')
        if action=='input.key' and ('key' not in b.allowed_input or a.get('keycode') not in b.allowed_keycodes or
                type(a.get('keycode')) is not int or type(a.get('down')) is not bool):raise ValueError('rustdesk_key_not_allowlisted')
        if action=='input.mouse' and ('mouse' not in b.allowed_input or any(type(a.get(k)) is not int for k in ('mask','x','y')) or
                not 0<=a['mask']<=255 or not 0<=a['x']<=8192 or not 0<=a['y']<=8192):raise ValueError('rustdesk_mouse_denied_or_invalid')
        if action in {'evidence.export','frame'}:
            path=b.resolve_artifact_output(a.get('output'))
            if path.suffix.lower()!=('.json' if action=='evidence.export' else '.png'):raise ValueError('rustdesk_artifact_extension_invalid')
            a['output']=str(path)
        a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id
        return json.loads(json.dumps(a,allow_nan=False))

    def _run(self,b,a):return self.backend.run(b,a)


def declare_rustdesk_machine(*,machine_id,owner_principal_id,bindings,journal,policy,backend=None):
    executor=RustDeskExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,
        bindings=bindings,journal=journal,policy=policy,backend=backend)
    return declare_session_machine(executor,bindings,'Configured native RustDesk peer identity gate and ownership')
