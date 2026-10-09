"""Configured Hyper-V guest lifecycle and interactive UIA via PowerShell Direct.

No host boot, VM enumeration, unattended logon, registration or elevation on
import. All actions target one disposable VM GUID and protected Interactive task.
"""
from __future__ import annotations
import base64
import hashlib
import json
import math
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass,field
from pathlib import Path,PureWindowsPath
from .guest_process import OwnedProviderRunner,declaration
from .identity_sessions import SessionExecutor,SessionScope
from .rpa import ExecutorFailure,effect_checkpoint,AuthorizedPaths,atomic_output,digest
from .uia_semantic import SemanticUIAExecutor,SemanticUIABackend,SemanticUIABinding


@dataclass(frozen=True)
class GuestLease:
    vm_id:str
    scope_sha256:str
    epoch:int
    expires_monotonic:float
    def __post_init__(self):
        if not self.vm_id or not re.fullmatch('[0-9a-f]{64}',self.scope_sha256) or type(self.epoch) is not int or self.epoch<1 or not math.isfinite(self.expires_monotonic):raise ValueError('invalid_host_guest_lease')


@dataclass(frozen=True)
class HyperVGuestConfig:
    vm_id:str
    vm_name:str
    owner_marker:str
    hardware_sha256:str
    powershell_executable:str
    powershell_sha256:str
    credential:object=field(repr=False,compare=False)
    guest_spool:str=r'C:\ProgramData\SENTRA-Guest\spool'
    task_name:str='SENTRA-Guest-UIA'
    task_path:str='\\SENTRA\\'
    guest_python:str=r'C:\SENTRA\python\python.exe'
    guest_package_root:str=r'C:\SENTRA\package'
    guest_source_pins:tuple[tuple[str,str],...]=()
    baseline_snapshot_id:str|None=None
    snapshot_name:str='SENTRA-acceptance-baseline'
    timeout_seconds:float=40
    fixture_task_name:str|None=None
    fixture_executable:str|None=None
    fixture_arguments:str|None=None
    allowed_switch_ids:tuple[str,...]=()
    fixture_identity_path:str|None=None
    def __post_init__(self):
        if str(uuid.UUID(self.vm_id))!=self.vm_id:raise ValueError('canonical_vm_guid_required')
        if not self.vm_name or not self.owner_marker.startswith('SENTRA-DISPOSABLE:') or not callable(self.credential):raise ValueError('configured_disposable_vm_required')
        if not re.fullmatch('[0-9a-f]{64}',self.hardware_sha256) or not re.fullmatch('[0-9a-f]{64}',self.powershell_sha256) or not Path(self.powershell_executable).is_absolute():
            raise ValueError('pinned_hyperv_hardware_and_transport_required')
        if any(not PureWindowsPath(p).is_absolute() for p in (self.guest_spool,self.guest_python,self.guest_package_root)) or not 5<=self.timeout_seconds<=240:
            raise ValueError('guest_paths_and_timeout_required')
        if not self.guest_source_pins or any(not PureWindowsPath(p).is_absolute() or not re.fullmatch('[0-9a-f]{64}',h) for p,h in self.guest_source_pins):
            raise ValueError('installed_guest_worker_source_pins_required')
        if self.baseline_snapshot_id:uuid.UUID(self.baseline_snapshot_id)


@dataclass(frozen=True)
class HyperVFixtureBinding:
    capability_id:str
    config:HyperVGuestConfig
    actions:tuple[str,...]=('status',)
    @property
    def timeout_seconds(self):return self.config.timeout_seconds+5
    def __post_init__(self):
        if not self.capability_id or not set(self.actions)<={'status','snapshot','reset','start','stop','prepare'}:raise ValueError('invalid_guest_fixture_actions')
        if 'reset' in self.actions and not self.config.baseline_snapshot_id:raise ValueError('pinned_baseline_snapshot_required')
        if 'prepare' in self.actions and not all((self.config.fixture_task_name,self.config.fixture_executable,self.config.fixture_arguments,self.config.fixture_identity_path)):raise ValueError('preinstalled_interactive_fixture_task_required')


HYPERV_SCRIPT=r'''
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$c=[Console]::In.ReadLine()|ConvertFrom-Json
function Emit($v) {[Console]::Out.WriteLine(($v|ConvertTo-Json -Depth 30 -Compress));[Console]::Out.Flush()}
function Gate {
  Emit @{event='checkpoint';phase='guest'}
  if ([Console]::In.ReadLine() -ne 'CONTINUE') {throw 'central_checkpoint_denied'}
  $v=Get-VM -Id ([guid]$c.vm_id)
  if ($v.Id.ToString() -ne $c.vm_id -or $v.Name -ne $c.vm_name -or $v.Notes -ne $c.owner_marker) {throw 'guest_vm_identity_changed'}
  $p=Get-VMProcessor -VM $v;$slots=@(Get-VMHardDiskDrive -VM $v|ForEach-Object {"$($_.ControllerType):$($_.ControllerNumber):$($_.ControllerLocation)"}|Sort-Object)
  $switches=@(Get-VMNetworkAdapter -VM $v|ForEach-Object {[string]$_.SwitchId}|Sort-Object)
  foreach ($switch in $switches) {if ($switch -and $switch -ne '00000000-0000-0000-0000-000000000000' -and $switch -notin $c.allowed_switch_ids) {throw 'guest_network_switch_not_authorized'}}
  # AVHD paths change legitimately when checkpointing; hardware slots do not.
  $doc=[ordered]@{vm_id=$v.Id.ToString();name=$v.Name;generation=[int]$v.Generation;processors=[int]$p.Count;memory_startup=[long]$v.MemoryStartup;configuration_location=$v.ConfigurationLocation;disk_slots=$slots;network_switches=$switches}
  $raw=[Text.Encoding]::UTF8.GetBytes(($doc|ConvertTo-Json -Depth 8 -Compress))
  $hash=([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($raw))).Replace('-','').ToLowerInvariant()
  if ($hash -ne $c.hardware_sha256) {throw 'guest_hardware_fingerprint_changed'}
  return $v
}
$s=$null
try {
  Import-Module Hyper-V -ErrorAction Stop;$v=Gate
  if ($c.action -eq 'status') {Emit @{event='result';ok=$true;evidence=@{vm_id=$v.Id.ToString();state=$v.State.ToString();hardware_sha256=$c.hardware_sha256;vm_api_observed=$true}};exit 0}
  if ($c.action -eq 'snapshot') {
    if (@(Get-VMSnapshot -VM $v|Where-Object {$_.Name -eq $c.snapshot_name}).Count -ne 0) {throw 'baseline_snapshot_name_already_exists'}
    $v=Gate;Checkpoint-VM -VM $v -SnapshotName $c.snapshot_name
    $snap=@(Get-VMSnapshot -VM $v|Where-Object {$_.Name -eq $c.snapshot_name})
    if ($snap.Count -ne 1) {throw 'snapshot_postcondition_failed'}
    Emit @{event='result';ok=$true;evidence=@{vm_id=$v.Id.ToString();snapshot_id=$snap[0].Id.ToString();snapshot_type=$snap[0].SnapshotType.ToString();provider_reported_created=$true}};exit 0
  }
  if ($c.action -eq 'reset') {
    $snap=@(Get-VMSnapshot -VM $v|Where-Object {$_.Id.ToString() -eq $c.baseline_snapshot_id})
    if ($snap.Count -ne 1) {throw 'pinned_baseline_snapshot_missing'}
    $v=Gate;Restore-VMSnapshot -VMSnapshot $snap[0] -Confirm:$false
    $v=Gate
    Emit @{event='result';ok=$true;evidence=@{vm_id=$v.Id.ToString();snapshot_id=$c.baseline_snapshot_id;state=$v.State.ToString();restore_requested=$true;guest_fixture_verified=$false}};exit 0
  }
  if ($c.action -eq 'start') {$v=Gate;Start-VM -VM $v;Emit @{event='result';ok=$true;evidence=@{vm_id=$c.vm_id;start_requested=$true}};exit 0}
  if ($c.action -eq 'stop') {$v=Gate;Stop-VM -VM $v;Emit @{event='result';ok=$true;evidence=@{vm_id=$c.vm_id;shutdown_requested=$true}};exit 0}
  if ($c.action -notin @('uia','collect','prepare')) {throw 'guest_action_not_supported'}
  if ($v.State.ToString() -ne 'Running') {throw 'configured_guest_not_running'}
  $secure=ConvertTo-SecureString $c.password -AsPlainText -Force
  $cred=[pscredential]::new($c.username,$secure);$v=Gate
  $s=New-PSSession -VMId ([guid]$c.vm_id) -Credential $cred
  if ($c.action -eq 'prepare') {
    $v=Gate
    Invoke-Command -Session $s -ArgumentList $c -ScriptBlock {
      param($c)
      foreach ($pin in $c.guest_source_pins) {if ((Get-FileHash -LiteralPath $pin[0] -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pin[1]) {throw 'guest_fixture_source_pin_changed'}}
      $task=Get-ScheduledTask -TaskName $c.fixture_task_name -TaskPath $c.task_path
      if ($task.Principal.LogonType.ToString() -notin @('Interactive','3') -or $task.Principal.RunLevel.ToString() -notin @('Limited','0') -or @($task.Actions).Count -ne 1 -or $task.Actions[0].Execute -ne $c.fixture_executable -or $task.Actions[0].Arguments -ne $c.fixture_arguments -or $task.State.ToString() -eq 'Running') {throw 'configured_fixture_task_not_ready_or_definition_changed'}
      if (Test-Path -LiteralPath $c.fixture_identity_path) {Move-Item -LiteralPath $c.fixture_identity_path -Destination ($c.fixture_identity_path+'.previous.'+$c.job_id)}
      Start-ScheduledTask -TaskName $c.fixture_task_name -TaskPath $c.task_path
      $timer=[Diagnostics.Stopwatch]::StartNew()
      while (!(Test-Path -LiteralPath $c.fixture_identity_path) -and $timer.Elapsed.TotalSeconds -lt 5) {Start-Sleep -Milliseconds 50}
      if (!(Test-Path -LiteralPath $c.fixture_identity_path)) {throw 'guest_fixture_interactive_window_not_ready'}
    } | Out-Null
    Emit @{event='result';ok=$true;evidence=@{vm_id=$c.vm_id;fixture_start_requested=$true;desktop_observation_verified=$false}};exit 0
  }
  if ($c.action -eq 'collect') {
    $v=Gate
    $file=Invoke-Command -Session $s -ArgumentList $c.guest_artifact_path -ScriptBlock {
      param($p)
      if (!(Test-Path -LiteralPath $p -PathType Leaf)) {throw 'configured_guest_artifact_missing'}
      if ((Get-Item -LiteralPath $p).Length -gt 16777216) {throw 'guest_artifact_limit'}
      $raw=[IO.File]::ReadAllBytes($p)
      @{data_base64=[Convert]::ToBase64String($raw);sha256=([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($raw))).Replace('-','').ToLowerInvariant();bytes=$raw.Length}
    }
    Emit @{event='result';ok=$true;evidence=@{vm_id=$c.vm_id;file=$file;transport='powershell-direct'}};exit 0
  }
  $v=Gate
  Invoke-Command -Session $s -ArgumentList $c -ScriptBlock {
    param($c)
    $task=Get-ScheduledTask -TaskName $c.task_name -TaskPath $c.task_path
    $wanted='-m sentra_executors.uia_guest_worker --request-dir "'+$c.guest_spool+'"'
    if ($task.Principal.LogonType.ToString() -notin @('Interactive','3') -or $task.Principal.RunLevel.ToString() -notin @('Limited','0') -or $task.State.ToString() -eq 'Running' -or @($task.Actions).Count -ne 1 -or $task.Actions[0].Execute -ne $c.guest_python -or $task.Actions[0].Arguments -ne $wanted -or $task.Actions[0].WorkingDirectory -ne $c.guest_package_root) {throw 'guest_interactive_task_definition_or_ownership_invalid'}
    foreach ($pin in $c.guest_source_pins) {if ((Get-FileHash -LiteralPath $pin[0] -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pin[1]) {throw 'guest_installed_worker_pin_changed'}}
    if (!(Test-Path -LiteralPath $c.guest_spool -PathType Container)) {throw 'protected_guest_spool_missing'}
    # Previous data is retained under a host-owned operation directory, not
    # silently reused as success for this request.
    foreach ($name in @('pending.json','response.jsonl','ack.json')) {
      $old=Join-Path $c.guest_spool $name
      if (Test-Path -LiteralPath $old) {Move-Item -LiteralPath $old -Destination (Join-Path $c.guest_spool ($c.job_id+'.previous.'+$name))}
    }
    $job=@{job_id=$c.job_id;deadline_unix=$c.deadline_unix;profile=$c.document.profile;arguments=$c.document.arguments}
    [IO.File]::WriteAllText((Join-Path $c.guest_spool 'pending.json'),($job|ConvertTo-Json -Depth 30 -Compress),[Text.UTF8Encoding]::new($false))
  } | Out-Null
  $v=Gate
  Invoke-Command -Session $s -ArgumentList $c -ScriptBlock {param($c) Start-ScheduledTask -TaskName $c.task_name -TaskPath $c.task_path} | Out-Null
  $offset=0
  while ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0 -lt $c.deadline_unix) {
    $v=Gate
    $lines=@(Invoke-Command -Session $s -ArgumentList $c,$offset -ScriptBlock {
      param($c,$offset) $p=Join-Path $c.guest_spool 'response.jsonl'
      if (Test-Path -LiteralPath $p) {
        if ((Get-Item -LiteralPath $p).Length -gt 2097152) {throw 'guest_result_limit'}
        $text=[IO.File]::ReadAllText($p);$parts=$text.Split("`n")
        if ($parts.Length -gt 1) {$parts[0..($parts.Length-2)]|Select-Object -Skip $offset}
      }
    })
    foreach ($line in $lines) {
      $m=$line|ConvertFrom-Json;$offset++
      if ($m.job_id -ne $c.job_id) {throw 'guest_response_operation_mismatch'}
      if ($m.event -eq 'checkpoint') {
        $v=Gate
        Invoke-Command -Session $s -ArgumentList $c,$m.sequence -ScriptBlock {
          param($c,$sequence) $a=@{job_id=$c.job_id;sequence=$sequence;expires_unix=([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0)+2}
          $p=Join-Path $c.guest_spool 'ack.json';$tmp=Join-Path $c.guest_spool 'ack.next'
          [IO.File]::WriteAllText($tmp,($a|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false));Move-Item -LiteralPath $tmp -Destination $p -Force
        } | Out-Null
      } elseif ($m.event -eq 'result') {
        if (!$m.ok) {Emit @{event='result';ok=$false;code=$m.code;uncertain=$m.uncertain};exit 0}
        $image=$null
        if ($c.screenshot_path) {
          $v=Gate
          $image=Invoke-Command -Session $s -ArgumentList $c.screenshot_path -ScriptBlock {param($p) if ((Get-Item -LiteralPath $p).Length -gt 16777216) {throw 'guest_image_limit'};[Convert]::ToBase64String([IO.File]::ReadAllBytes($p))}
        }
        Emit @{event='result';ok=$true;evidence=@{guest_evidence=$m.evidence;image_base64=$image;vm_id=$c.vm_id;transport='powershell-direct-interactive-task'}};exit 0
      } else {throw 'guest_result_event_invalid'}
    }
    Start-Sleep -Milliseconds 50
  }
  throw 'guest_deadline_exceeded'
} catch {
  $code='hyperv_guest_provider_error';$message=$_.Exception.Message
  if ($message -match '^(guest_|configured_|pinned_|baseline_|snapshot_|central_)' -and $message -match '^[a-z_]{3,120}$') {$code=$message}
  Emit @{event='result';ok=$false;code=$code;uncertain=$true;evidence=@{exception_type=$_.Exception.GetType().FullName;error_id=$_.FullyQualifiedErrorId;category=$_.CategoryInfo.Category.ToString();vm_id=$c.vm_id}}
}
finally {if ($s) {Remove-PSSession -Session $s -ErrorAction SilentlyContinue}}
'''


class HyperVClient:
    def __init__(self,config,lease_reader,runner=None):
        if not callable(lease_reader):raise ValueError('trusted_central_guest_lease_reader_required')
        self.config=config;self.lease_reader=lease_reader;self.runner=runner or OwnedProviderRunner()
    def _lease(self,scope,epoch=None):
        effect_checkpoint();lease=self.lease_reader(self.config.vm_id,scope)
        if not isinstance(lease,GuestLease) or lease.vm_id!=self.config.vm_id or lease.scope_sha256!=scope or time.monotonic()>=lease.expires_monotonic or (epoch is not None and lease.epoch!=epoch):
            raise ExecutorFailure('guest_ownership_or_epoch_not_live')
        return lease
    def call(self,scope,action,document=None,*,guest_artifact_path=None):
        if sys.platform!='win32':raise ExecutorFailure('hyperv_powershell_direct_requires_windows_host')
        lease=self._lease(scope);c=self.config
        data={name:getattr(c,name) for name in ('vm_id','vm_name','owner_marker','hardware_sha256','guest_spool','task_name','task_path',
            'guest_python','guest_package_root','guest_source_pins','baseline_snapshot_id','snapshot_name','fixture_task_name','fixture_executable','fixture_arguments','allowed_switch_ids','fixture_identity_path')}
        data.update(action=action,job_id=uuid.uuid4().hex,deadline_unix=time.time()+c.timeout_seconds-3)
        if document is not None or action in {'collect','prepare'}:
            credentials=c.credential()
            if not isinstance(credentials,tuple) or len(credentials)!=2 or any(type(x) is not str or not x for x in credentials):raise ExecutorFailure('configured_guest_credential_missing')
            data.update(username=credentials[0],password=credentials[1])
            if document is not None:data['document']=json.loads(json.dumps(document))
            if action=='collect':data['guest_artifact_path']=guest_artifact_path
            if document is not None and document['arguments']['action']=='screenshot':
                data['screenshot_path']=str(PureWindowsPath(c.guest_spool)/(data['job_id']+'.png'))
                data['document']['arguments']['_temporary_output']=data['screenshot_path']
        encoded=base64.b64encode(HYPERV_SCRIPT.encode('utf-16-le')).decode()
        result=self.runner.invoke(c.powershell_executable,('-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded),
            input_document=data,executable_sha256=c.powershell_sha256,timeout_seconds=c.timeout_seconds,max_result_bytes=32*1024*1024,
            checkpoint=lambda:self._lease(scope,lease.epoch))
        self._lease(scope,lease.epoch);return result


class HyperVInteractiveRunner:
    def __init__(self,client):self.client=client
    def invoke(self,_executable,_argv,*,input_document,**_limits):
        arguments=input_document['arguments'];result=self.client.call(arguments['_scope'],'uia',input_document)
        evidence=result['guest_evidence']
        if arguments['action']=='screenshot':
            raw=base64.b64decode(result['image_base64'],validate=True)
            if len(raw)>16*1024*1024 or raw[:8]!=b'\x89PNG\r\n\x1a\n':raise ExecutorFailure('guest_screenshot_invalid')
            effect_checkpoint();Path(arguments['_temporary_output']).write_bytes(raw)
        return dict(evidence,vm_id=result['vm_id'],transport=result['transport'],isolation_boundary='configured_hyperv_vm',
                    isolation_attested=False)


class HyperVFixtureExecutor(SessionExecutor):
    kind='windows_guest_fixture'
    def __init__(self,*,machine_id,owner_principal_id,bindings,lease_reader,policy=None,runner=None):
        super().__init__(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings={b.capability_id:b for b in bindings},policy=policy)
        self.clients={b.capability_id:HyperVClient(b.config,lease_reader,runner) for b in bindings}
    def _validate(self,request,b):
        a=dict(request.arguments)
        if set(a)!={'action'} or a['action'] not in b.actions:raise ValueError('host_configured_guest_fixture_action_required')
        a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id;return a
    def _run(self,b,a):return self.clients[b.capability_id].call(a['_scope'],a['action'])


def declare_hyperv_fixture_machine(*,machine_id,owner_principal_id,bindings,lease_reader,policy=None,runner=None):
    executor=HyperVFixtureExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings=bindings,lease_reader=lease_reader,policy=policy,runner=runner)
    return declaration(executor,bindings,'Configured disposable Hyper-V VM lifecycle and fixture checkpoints')


def declare_windows_guest_uia_machine(*,machine_id,owner_principal_id,bindings,guest_config,lease_reader,policy=None,runner=None):
    """Bindings remain SemanticUIABinding; GUI executes ONLY in configured VM task."""
    if any(b.timeout_seconds<guest_config.timeout_seconds+5 for b in bindings):raise ValueError('guest_transport_requires_larger_operation_budget')
    client=HyperVClient(guest_config,lease_reader,runner)
    backend=SemanticUIABackend(runner=HyperVInteractiveRunner(client))
    executor=SemanticUIAExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings=bindings,policy=policy,backend=backend)
    # Kind distinguishes VM-backed inventory without claiming an attested guest.
    executor.kind='windows_guest_uia'
    return declaration(executor,bindings,'Semantic UIA inside configured Hyper-V InteractiveToken guest')


@dataclass(frozen=True)
class GuestArtifactBinding:
    capability_id:str
    config:HyperVGuestConfig
    inventory:tuple[tuple[str,str],...]
    paths:AuthorizedPaths
    @property
    def timeout_seconds(self):return self.config.timeout_seconds+5
    def __post_init__(self):
        if not self.capability_id or not self.inventory or len(dict(self.inventory))!=len(self.inventory) or any(not key or not PureWindowsPath(path).is_absolute() for key,path in self.inventory):raise ValueError('fixed_guest_artifact_inventory_required')


class GuestArtifactExecutor(SessionExecutor):
    kind='windows_guest_artifact'
    def __init__(self,*,machine_id,owner_principal_id,bindings,lease_reader,policy=None,runner=None):
        super().__init__(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings={b.capability_id:b for b in bindings},policy=policy)
        self.clients={b.capability_id:HyperVClient(b.config,lease_reader,runner) for b in bindings}
    def _validate(self,request,b):
        a=dict(request.arguments)
        if set(a)!={'action','artifact_key','output'} or a['action']!='collect' or a['artifact_key'] not in dict(b.inventory):raise ValueError('configured_guest_artifact_key_required')
        a['output']=str(b.paths.resolve(a['output'],write=True));a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id;return a
    def _run(self,b,a):
        result=self.clients[b.capability_id].call(a['_scope'],'collect',guest_artifact_path=dict(b.inventory)[a['artifact_key']])
        raw=base64.b64decode(result['file']['data_base64'],validate=True)
        if len(raw)>16*1024*1024 or hashlib.sha256(raw).hexdigest()!=result['file']['sha256']:raise ExecutorFailure('guest_collected_bytes_invalid')
        def verify(path):
            if digest(path)!=result['file']['sha256']:raise ExecutorFailure('guest_artifact_copy_changed')
        artifact=atomic_output(b.paths,a['output'],lambda p:p.write_bytes(raw),verify,max_output_bytes=16*1024*1024)
        return {'artifact':artifact,'actual_key':a['artifact_key'],'path':a['output'],'sha256':result['file']['sha256'],
                'artifact_id':artifact.get('artifact_id'),'resource_uri':artifact.get('resource_uri'),'vm_id':result['vm_id']}


def declare_guest_artifact_machine(*,machine_id,owner_principal_id,bindings,lease_reader,policy=None,runner=None):
    executor=GuestArtifactExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings=bindings,lease_reader=lease_reader,policy=policy,runner=runner)
    return declaration(executor,bindings,'Fixed guest artifact capture over configured Hyper-V PowerShell Direct')
