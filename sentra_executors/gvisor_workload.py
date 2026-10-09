"""Real Linux runsc workloads and explicit experimental checkpoint lifecycle."""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
import tarfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from .guest_process import OwnedProviderRunner,declaration
from .identity_sessions import SessionExecutor,SessionScope
from .rpa import AuthorizedPaths,ExecutorFailure,effect_checkpoint,digest,atomic_output


@dataclass(frozen=True)
class WorkloadLease:
    container_id:str
    scope_sha256:str
    epoch:int
    expires_monotonic:float


@dataclass(frozen=True)
class RunscWorkloadBinding:
    capability_id:str
    container_id:str
    binary:str
    binary_sha256:str
    bundle:str
    config_sha256:str
    program_sha256:str
    state_root:str
    checkpoint_root:str
    paths:AuthorizedPaths
    allowed_readonly_mounts:tuple[str,...]=()
    platform:str='systrap'
    file_access:str='exclusive'
    actions:tuple[str,...]=('session.list','inspect','state','evidence.export')
    timeout_seconds:float=45
    max_checkpoint_bytes:int=448*1024*1024
    def __post_init__(self):
        if not self.capability_id or not re.fullmatch('sentra-lab-[a-z0-9-]{3,48}',self.container_id):raise ValueError('configured_runsc_id_required')
        if any(not Path(p).is_absolute() for p in (self.binary,self.bundle,self.state_root,self.checkpoint_root)) or any(not re.fullmatch('[0-9a-f]{64}',h) for h in (self.binary_sha256,self.config_sha256,self.program_sha256)):
            raise ValueError('pinned_runsc_paths_and_workload_required')
        if self.platform not in {'systrap','kvm'} or self.file_access not in {'exclusive','shared'} or not set(self.actions)<={'session.list','inspect','create','start','state','wait','checkpoint','restore','terminate','delete','evidence.export'} or not 5<=self.timeout_seconds<=120 or not 1024*1024<=self.max_checkpoint_bytes<=448*1024*1024:
            raise ValueError('unsupported_runsc_profile')


def inspect_workload(b):
    root=Path(b.bundle).resolve(strict=True);config=root/'config.json'
    if config.stat().st_size>65536 or digest(config)!=b.config_sha256:raise ExecutorFailure('runsc_workload_spec_pin_changed')
    spec=json.loads(config.read_text(encoding='utf-8'))
    if set(spec)-{'ociVersion','root','process','mounts','linux','annotations','hostname'}:raise ExecutorFailure('runsc_oci_hooks_or_extra_sections_denied')
    if spec.get('ociVersion')!='1.0.2' or spec.get('root')!={'path':'rootfs','readonly':True}:raise ExecutorFailure('runsc_readonly_root_profile_required')
    process=spec.get('process',{});args=process.get('args')
    if not isinstance(args,list) or not args or not all(type(a) is str for a in args) or not args[0].startswith('/') or process.get('terminal') or process.get('noNewPrivileges') is not True or process.get('user',{}).get('uid',0)<1000:
        raise ExecutorFailure('runsc_pinned_nonprivileged_process_required')
    if any(process.get('capabilities',{}).get(k) for k in ('bounding','effective','permitted','inheritable','ambient')):raise ExecutorFailure('runsc_capabilities_denied')
    rootfs=(root/'rootfs').resolve(strict=True);program=(rootfs/args[0].lstrip('/')).resolve(strict=True)
    if not rootfs.is_relative_to(root) or not program.is_relative_to(rootfs) or digest(program)!=b.program_sha256:raise ExecutorFailure('runsc_rootfs_or_program_pin_changed')
    for mount in spec.get('mounts',[]):
        if mount.get('type')=='bind':
            source=str(Path(mount.get('source','')).resolve(strict=True))
            if source not in b.allowed_readonly_mounts or 'ro' not in mount.get('options',[]) or 'rw' in mount.get('options',[]):raise ExecutorFailure('runsc_host_mount_denied')
        elif mount.get('type')=='tmpfs':
            if mount.get('destination')!='/tmp' or not {'nosuid','nodev','noexec','size=67108864'}<=set(mount.get('options',[])):raise ExecutorFailure('runsc_tmpfs_limits_required')
        elif mount.get('type')=='proc':
            if mount.get('destination')!='/proc':raise ExecutorFailure('runsc_proc_mount_denied')
        else:raise ExecutorFailure('runsc_mount_type_denied')
    linux=spec.get('linux',{});namespaces=linux.get('namespaces',[])
    if set(linux)-{'namespaces','resources','maskedPaths','readonlyPaths'}:raise ExecutorFailure('runsc_devices_or_host_namespace_configuration_denied')
    if not {'pid','network','mount','ipc','uts'}<={n.get('type') for n in namespaces} or any('path' in n for n in namespaces):raise ExecutorFailure('runsc_private_namespaces_required')
    limits=linux.get('resources',{})
    if not 1<=limits.get('pids',{}).get('limit',0)<=256 or not 16*1024*1024<=limits.get('memory',{}).get('limit',0)<=4*1024*1024*1024:raise ExecutorFailure('runsc_resource_limits_required')
    return {'config_sha256':b.config_sha256,'program_sha256':b.program_sha256,'args':args,
            'network':'none','file_access':b.file_access,'platform':b.platform,'isolation_attested':False}


class RunscCLI:
    def __init__(self,runner=None):self.runner=runner or OwnedProviderRunner()
    def call(self,b,args,checkpoint):
        return self.runner.invoke(sys.executable,('-m','sentra_executors.gvisor_worker'),input_document={
            'binary':b.binary,'binary_sha256':b.binary_sha256,'argv':[f'--root={b.state_root}','--network=none',
                f'--platform={b.platform}',f'--file-access={b.file_access}',*args],
            'timeout':b.timeout_seconds-3},timeout_seconds=b.timeout_seconds-1,checkpoint=checkpoint)


class RunscWorkloadBackend:
    def __init__(self,journal,lease_reader,runner=None):
        if not callable(lease_reader):raise ValueError('live_runsc_ownership_reader_required')
        self.journal=journal;self.lease_reader=lease_reader;self.cli=RunscCLI(runner)
    def run(self,b,a):
        scope=a['_scope'];action=a['action']
        if action=='session.list':return self.journal.list(scope,'runsc',b.config_sha256)
        if action=='evidence.export':
            row=self.journal.get(a['session_id'],scope,'runsc',b.config_sha256)
            return {'artifact':self.journal.export(row,b.paths,a['output'])}
        def check(epoch=None):
            effect_checkpoint();lease=self.lease_reader(b.container_id,scope)
            if not isinstance(lease,WorkloadLease) or lease.container_id!=b.container_id or lease.scope_sha256!=scope or time.monotonic()>=lease.expires_monotonic or epoch is not None and lease.epoch!=epoch:
                raise ExecutorFailure('runsc_scope_or_fence_not_live')
            return lease
        lease=check();profile=inspect_workload(b)
        if action=='inspect':return profile
        if sys.platform!='linux':raise ExecutorFailure('runsc_requires_configured_linux_host')
        if digest(Path(b.binary))!=b.binary_sha256:raise ExecutorFailure('runsc_binary_pin_changed')
        if not Path(b.state_root).is_dir() or not Path(b.checkpoint_root).is_dir():raise ExecutorFailure('protected_runsc_runtime_directories_missing')
        def call(*args):return self.cli.call(b,args,lambda:check(lease.epoch))
        if action not in {'state','wait'}:
            prior=self.journal.reserve_effect(a['_operation_id'],scope,a)
            if prior is not None:return prior
        if action=='create':
            # runsc create refuses an existing ID; protected runtime root and
            # durable intent are necessary for ownership, not guest PID alone.
            row=self.journal.create(scope,'runsc',b.config_sha256,b.container_id,{'resource_kind':'oci-workload','profile':profile})
            result=call('create','--bundle',b.bundle,b.container_id)
            self.journal.update(row,state='CREATED')
        else:
            row=self.journal.get(a['session_id'],scope,'runsc',b.config_sha256)
            if row['remote_id']!=b.container_id:raise ExecutorFailure('runsc_owned_id_changed')
            if action=='state':
                raw=call('state',b.container_id);state=json.loads(raw['stdout'])
                if state.get('id')!=b.container_id or str(Path(state.get('bundle','')).resolve())!=str(Path(b.bundle).resolve()):raise ExecutorFailure('runsc_remote_resource_changed')
                result={'state':state,'runtime_reported':True}
            elif action=='start':result=call('start',b.container_id);self.journal.update(row,state='START_REQUESTED')
            elif action=='wait':result=call('wait',b.container_id);result['process_wait_result']=json.loads(result['stdout'])
            elif action=='terminate':result=call('kill','--all',b.container_id,'KILL');self.journal.update(row,state='KILL_REQUESTED')
            elif action=='delete':result=call('delete',b.container_id);self.journal.update(row,state='DELETED')
            elif action=='checkpoint':
                directory=Path(b.checkpoint_root)/uuid.uuid4().hex;check(lease.epoch);directory.mkdir(mode=0o700)
                result=call('checkpoint','--image-path',str(directory),'--leave-running=true',b.container_id)
                manifest=self._manifest(directory,b);(directory/'sentra-compatibility.json').write_text(json.dumps(manifest),encoding='utf-8')
                metadata=dict(row['metadata'],checkpoint_directory=str(directory),checkpoint_manifest_sha256=digest(directory/'sentra-compatibility.json'))
                self.journal.update(row,metadata=metadata)
                def produce(path):
                    with tarfile.open(path,'w') as archive:
                        for name in [*manifest['files'],'sentra-compatibility.json']:
                            check(lease.epoch);archive.add(directory/name,arcname=name,recursive=False)
                artifact=atomic_output(b.paths,a['output'],produce,lambda p:self._verify_tar(p,manifest),max_output_bytes=b.max_checkpoint_bytes+32*1024*1024)
                result={'checkpoint_artifact':artifact,'experimental':True,'external_effect_recovery_asserted':False,'source_workload_left_running':True}
            elif action=='restore':
                if row['state']!='DELETED':raise ExecutorFailure('explicit_delete_required_before_restore')
                directory=Path(row['metadata'].get('checkpoint_directory','')).resolve(strict=True)
                if directory.parent!=Path(b.checkpoint_root).resolve() or digest(directory/'sentra-compatibility.json')!=row['metadata'].get('checkpoint_manifest_sha256'):
                    raise ExecutorFailure('owned_checkpoint_manifest_changed')
                old=json.loads((directory/'sentra-compatibility.json').read_text());current=self._manifest(directory,b)
                if old!=current:raise ExecutorFailure('runsc_checkpoint_compatibility_or_bytes_changed')
                result=call('restore','--bundle',b.bundle,'--image-path',str(directory),'--detach',b.container_id)
                self.journal.update(row,state='RESTORE_REQUESTED',new_epoch=True)
                result.update(experimental=True,restored_state_semantically_verified=False,external_effect_recovery_asserted=False)
            else:raise ExecutorFailure('unsupported_runsc_action')
        self.journal.append(row,'runsc',json.dumps(result).encode())
        result=dict(result,session_id=row['id'],profile=profile)
        if action not in {'state','wait'}:self.journal.complete_effect(a['_operation_id'],result)
        return result
    def _manifest(self,directory,b):
        files={};total=0
        for path in sorted(directory.rglob('*')):
            effect_checkpoint()
            if path==directory/'sentra-compatibility.json':continue
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):raise ExecutorFailure('checkpoint_path_escape')
            if path.is_file():
                total+=path.stat().st_size
                if len(files)>=20000 or total>b.max_checkpoint_bytes:raise ExecutorFailure('checkpoint_budget_exceeded')
                files[path.relative_to(directory).as_posix()]=digest(path)
        if not files:raise ExecutorFailure('empty_runsc_checkpoint')
        return {'runsc_binary_sha256':b.binary_sha256,'oci_config_sha256':b.config_sha256,'program_sha256':b.program_sha256,
                'files':files,'bytes':total,'experimental':True,'sockets_recovered_asserted':False}
    def _verify_tar(self,path,manifest):
        with tarfile.open(path,'r') as archive:
            members=archive.getmembers()
            if {m.name for m in members}!={*manifest['files'],'sentra-compatibility.json'} or any(not m.isfile() for m in members):raise ExecutorFailure('checkpoint_archive_invalid')
            for member in members:
                effect_checkpoint();stream=archive.extractfile(member);hasher=hashlib.sha256()
                for block in iter(lambda:stream.read(1024*1024),b''):hasher.update(block)
                if member.name in manifest['files'] and hasher.hexdigest()!=manifest['files'][member.name]:raise ExecutorFailure('checkpoint_archive_bytes_changed')
                if member.name=='sentra-compatibility.json':
                    if member.size>4*1024*1024 or json.load(archive.extractfile(member))!=manifest:raise ExecutorFailure('checkpoint_archive_manifest_changed')


class RunscWorkloadExecutor(SessionExecutor):
    kind='gvisor_workload'
    def __init__(self,*,machine_id,owner_principal_id,bindings,journal,lease_reader,policy=None,runner=None):
        super().__init__(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings={b.capability_id:b for b in bindings},policy=policy)
        self.backend=RunscWorkloadBackend(journal,lease_reader,runner)
    def _validate(self,request,b):
        a=dict(request.arguments);action=a.get('action');extra={'output'} if action in {'checkpoint','evidence.export'} else set()
        if action not in b.actions or set(a)-({'action'}|extra|({'session_id'} if action not in {'session.list','inspect','create'} else set())):raise ValueError('runsc_typed_arguments_required')
        if action not in {'session.list','inspect','create'} and not isinstance(a.get('session_id'),str):raise ValueError('owned_runsc_session_required')
        if extra:a['output']=str(b.paths.resolve(a.get('output'),write=True))
        a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id;return a
    def _run(self,b,a):return self.backend.run(b,a)


def declare_runsc_workload_machine(*,machine_id,owner_principal_id,bindings,journal,lease_reader,policy=None,runner=None):
    executor=RunscWorkloadExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings=bindings,journal=journal,lease_reader=lease_reader,policy=policy,runner=runner)
    return declaration(executor,bindings,'Pinned Linux runsc workload with explicit experimental checkpoint/restore')
