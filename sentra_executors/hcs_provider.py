"""Actual exported hcsshim bridge for prepared Windows headless containers.

Host config supplies prepared layers/uVM. No package-private import, layer pull,
GUI claim, automatic privilege escalation, or arbitrary process arguments.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from .guest_process import OwnedProviderRunner,declaration
from .identity_sessions import SessionExecutor,SessionScope,SessionJournal
from .rpa import AuthorizedPaths,ExecutorFailure,effect_checkpoint,digest


@dataclass(frozen=True)
class HCSCommand:
    key:str
    application:str
    command_line:str
    user:str='ContainerUser'
    working_directory:str='C:\\'


@dataclass(frozen=True)
class NativeHCSBinding:
    capability_id:str
    container_id:str
    bridge_executable:str
    bridge_sha256:str
    prepared_config:str
    config_sha256:str
    host_paths:AuthorizedPaths
    paths:AuthorizedPaths
    commands:tuple[HCSCommand,...]=()
    actions:tuple[str,...]=('session.list','status','evidence.export')
    timeout_seconds:float=45
    def __post_init__(self):
        if not self.capability_id or not re.fullmatch('sentra-lab-[a-z0-9-]{3,48}',self.container_id):raise ValueError('owned_hcs_id_required')
        if any(not re.fullmatch('[0-9a-f]{64}',h) for h in (self.bridge_sha256,self.config_sha256)) or not Path(self.bridge_executable).is_absolute():raise ValueError('pinned_hcs_bridge_and_config_required')
        if not set(self.actions)<={'session.list','create','start','status','run','shutdown','terminate','evidence.export'} or not 5<=self.timeout_seconds<=120 or len({c.key for c in self.commands})!=len(self.commands):raise ValueError('invalid_hcs_capability')


def prepared_hcs_config(binding):
    path=binding.host_paths.resolve(binding.prepared_config)
    if path.stat().st_size>65536 or digest(path)!=binding.config_sha256:raise ExecutorFailure('hcs_prepared_config_pin_changed')
    config=json.loads(path.read_text(encoding='utf-8'))
    allowed={'SystemType','Name','Owner','VolumePath','LayerFolderPath','Layers','ProcessorCount','ProcessorMaximum',
             'MemoryMaximumInMB','HvPartition','HvRuntime','MappedDirectories','EndpointList','TerminateOnLastHandleClosed'}
    if not isinstance(config,dict) or set(config)-allowed or config.get('SystemType')!='Container' or config.get('HvPartition') is not True:
        raise ExecutorFailure('hyperv_headless_hcs_profile_required')
    if config.get('Name') not in {None,binding.container_id} or not config.get('Layers') or not config.get('HvRuntime',{}).get('ImagePath'):
        raise ExecutorFailure('hcs_prepared_layer_and_uvm_paths_required')
    if config.get('EndpointList') or config.get('MappedDirectories') or config.get('TerminateOnLastHandleClosed'):
        raise ExecutorFailure('hcs_network_mount_or_ephemeral_handle_profile_denied')
    if not 1<=config.get('ProcessorCount',0)<=8 or not 1<=config.get('ProcessorMaximum',0)<=10000 or not 256<=config.get('MemoryMaximumInMB',0)<=16384:
        raise ExecutorFailure('hcs_resource_limits_required')
    return config


class NativeHCSBackend:
    def __init__(self,journal,runner=None):self.journal=journal;self.runner=runner or OwnedProviderRunner()
    def run(self,b,a):
        scope=a['_scope'];owner='SENTRA:'+scope
        if a['action']=='session.list':return self.journal.list(scope,'hcs',b.config_sha256)
        if a['action']=='evidence.export':
            row=self.journal.get(a['session_id'],scope,'hcs',b.config_sha256)
            return {'artifact':self.journal.export(row,b.paths,a['output'])}
        if sys.platform!='win32':raise ExecutorFailure('windows_hcs_runtime_required')
        config=prepared_hcs_config(b);config.update(Name=b.container_id,Owner=owner,TerminateOnLastHandleClosed=False)
        action=a['action'];row=None
        if action!='status':
            prior=self.journal.reserve_effect(a['_operation_id'],scope,a)
            if prior is not None:return prior
        if action=='create':
            row=self.journal.create(scope,'hcs',b.config_sha256,b.container_id,{'resource_kind':'headless-hyperv-container','owner':owner})
        else:
            row=self.journal.get(a['session_id'],scope,'hcs',b.config_sha256)
            if row['remote_id']!=b.container_id:raise ExecutorFailure('hcs_container_ownership_changed')
        command=None
        if action=='run':
            spec=next(c for c in b.commands if c.key==a['command_key'])
            command={'ApplicationName':spec.application,'CommandLine':spec.command_line,'User':spec.user,
                     'WorkingDirectory':spec.working_directory,'CreateStdOutPipe':True,'CreateStdErrPipe':True}
        if action not in {'create','status'} and not row['metadata'].get('native_identity'):raise ExecutorFailure('hcs_status_required_to_reconcile_native_identity')
        environment=dict(os.environ)
        # Exported CreateContainer merges this environment variable into its
        # config; do not let an inherited host value bypass the pinned profile.
        environment.pop('HCSSHIM_CREATECONTAINER_ADDITIONALJSON',None)
        result=self.runner.invoke(b.bridge_executable,(),input_document={'action':action,'id':b.container_id,'owner':owner,
            'config':config,'command':command,'timeout_ms':int((b.timeout_seconds-5)*1000),
            'expected_identity':row['metadata'].get('native_identity','')},
            executable_sha256=b.bridge_sha256,timeout_seconds=b.timeout_seconds-1,environment=environment)
        self.journal.append(row,'hcs',json.dumps(result).encode())
        metadata=dict(row['metadata'])
        if result.get('native_identity'):metadata['native_identity']=result['native_identity']
        self.journal.update(row,state='TERMINATED' if action in {'shutdown','terminate'} else 'OBSERVED',metadata=metadata)
        result=dict(result,session_id=row['id'],interactive_desktop=False,isolation_attested=False)
        if action!='status':self.journal.complete_effect(a['_operation_id'],result)
        return result


class NativeHCSExecutor(SessionExecutor):
    kind='windows_hcs_native'
    def __init__(self,*,machine_id,owner_principal_id,bindings,journal,policy=None,runner=None):
        super().__init__(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings={b.capability_id:b for b in bindings},policy=policy)
        self.backend=NativeHCSBackend(journal,runner)
    def _validate(self,request,b):
        a=dict(request.arguments);action=a.get('action')
        fields={'run':{'command_key'},'evidence.export':{'output'}}.get(action,set())
        if action not in b.actions or set(a)-({'action'}|fields|({'session_id'} if action not in {'create','session.list'} else set())):raise ValueError('hcs_arguments_denied')
        if action not in {'create','session.list'} and (type(a.get('session_id')) is not str or not a['session_id']):raise ValueError('hcs_owned_session_required')
        if action=='run' and a.get('command_key') not in {c.key for c in b.commands}:raise ValueError('hcs_command_not_allowlisted')
        if action=='evidence.export':a['output']=str(b.paths.resolve(a.get('output'),write=True))
        a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id;return a
    def _run(self,b,a):return self.backend.run(b,a)


def declare_native_hcs_machine(*,machine_id,owner_principal_id,bindings,journal,policy=None,runner=None):
    executor=NativeHCSExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings=bindings,journal=journal,policy=policy,runner=runner)
    return declaration(executor,bindings,'Prepared Hyper-V HCS headless workload through pinned native hcsshim helper')
