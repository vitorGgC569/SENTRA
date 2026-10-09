"""Reviewable deployment/fixture scripts. Nothing executes on construction."""
from __future__ import annotations
import json
from pathlib import PureWindowsPath
from .uia_semantic import SemanticUIABinding,DesktopIdentity,UIASelector
from .windows_identity import ProcessIdentity


def ps_quote(value):
    if not isinstance(value,str) or '\x00' in value:raise ValueError('invalid_powershell_literal')
    return "'"+value.replace("'","''")+"'"


def interactive_guest_task_setup(config,*,guest_user):
    """Run manually INSIDE prepared guest after package/ACL provisioning.

    Does not store a password, enable autologon, change execution policy,
    start a VM, or register anything in the Hyper-V host's desktop session.
    """
    if not guest_user:raise ValueError('configured_guest_user_required')
    arguments='-m sentra_executors.uia_guest_worker --request-dir "'+config.guest_spool+'"'
    return '\n'.join([
        "$ErrorActionPreference='Stop'",
        f'$principal=New-ScheduledTaskPrincipal -UserId {ps_quote(guest_user)} -LogonType Interactive -RunLevel Limited',
        f'$action=New-ScheduledTaskAction -Execute {ps_quote(config.guest_python)} -Argument {ps_quote(arguments)} -WorkingDirectory {ps_quote(config.guest_package_root)}',
        '$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew',
        f'Register-ScheduledTask -TaskName {ps_quote(config.task_name)} -TaskPath {ps_quote(config.task_path)} -Action $action -Principal $principal -Settings $settings',
    ])


def windows_forms_fixture_script(*,output_csv,identity_json,window_title='SENTRA-Acceptance-Forms'):
    """Actual Windows Forms fixture: UIA Value/Invoke -> verifiable CSV file.

    Configured output parents must already exist in disposable guest. Script
    uses no host user files, coordinates, clipboard, or benchmark eval code.
    """
    if any(not PureWindowsPath(p).is_absolute() for p in (output_csv,identity_json)):raise ValueError('absolute_guest_fixture_paths_required')
    template=r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form=[Windows.Forms.Form]::new();$form.Text=WINDOW_TITLE;$form.Width=480;$form.Height=220
$entry=[Windows.Forms.TextBox]::new();$entry.Name='InputValue';$entry.AccessibleName='InputValue';$entry.Width=350;$entry.Top=30;$entry.Left=20
$save=[Windows.Forms.Button]::new();$save.Name='SaveResult';$save.AccessibleName='SaveResult';$save.Text='Save';$save.Top=70;$save.Left=20
$status=[Windows.Forms.Label]::new();$status.Name='ResultStatus';$status.AccessibleName='ResultStatus';$status.Text='Not saved';$status.Top=110;$status.Left=20;$status.Width=350
$save.Add_Click({
  [pscustomobject]@{Result=$entry.Text}|ConvertTo-Csv -NoTypeInformation|Set-Content -LiteralPath OUTPUT_CSV -Encoding UTF8
  $status.Text='Saved: '+$entry.Text
})
$form.Controls.AddRange(@($entry,$save,$status))
$form.Add_Shown({
  $process=[Diagnostics.Process]::GetCurrentProcess();$exe=$process.MainModule.FileName
  $record=@{pid=$PID;hwnd=[long]$form.Handle;creation_filetime=$process.StartTime.ToFileTimeUtc();executable_sha256=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant();machine_guid=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography').MachineGuid;session_id=$process.SessionId;window_title=$form.Text;fixture='sentra-windows-forms-v1'}
  [IO.File]::WriteAllText(IDENTITY_JSON,($record|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false));$form.Activate()
})
[Windows.Forms.Application]::Run($form)
'''
    import re
    values={'WINDOW_TITLE':ps_quote(window_title),'OUTPUT_CSV':ps_quote(output_csv),'IDENTITY_JSON':ps_quote(identity_json)}
    return re.sub('WINDOW_TITLE|OUTPUT_CSV|IDENTITY_JSON',lambda match:values[match.group()],template)


def fixture_task_setup(config,*,guest_user):
    if not all((config.fixture_task_name,config.fixture_executable,config.fixture_arguments,guest_user)):raise ValueError('configured_fixture_task_required')
    return '\n'.join([
        "$ErrorActionPreference='Stop'",
        f'$principal=New-ScheduledTaskPrincipal -UserId {ps_quote(guest_user)} -LogonType Interactive -RunLevel Limited',
        f'$action=New-ScheduledTaskAction -Execute {ps_quote(config.fixture_executable)} -Argument {ps_quote(config.fixture_arguments)}',
        f'Register-ScheduledTask -TaskName {ps_quote(config.fixture_task_name)} -TaskPath {ps_quote(config.task_path)} -Principal $principal -Action $action -Settings (New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew)',
    ])


def binding_from_fixture_identity(*,capability_id,identity_bytes,expected_machine_guid,expected_executable_sha256,
                                  paths,selectors,timeout_seconds=50):
    """Host-only after collecting protected fixture metadata from pinned VM.

    Metadata from an agent-writable workspace is not an identity authority.
    The backend still probes actual kernel identity before each UIA action.
    """
    if len(identity_bytes)>8192:raise ValueError('fixture_identity_limit')
    value=json.loads(identity_bytes)
    if value.get('fixture')!='sentra-windows-forms-v1' or value.get('machine_guid','').lower()!=expected_machine_guid.lower() or value.get('executable_sha256')!=expected_executable_sha256:
        raise ValueError('configured_guest_fixture_identity_mismatch')
    identity=ProcessIdentity(**{k:value[k] for k in ('pid','hwnd','creation_filetime','executable_sha256')})
    return SemanticUIABinding(capability_id,identity,value['window_title'],DesktopIdentity(value['machine_guid'],value['session_id']),
        tuple(selectors),paths,actions=('observe','wait','read','invoke','set_value','screenshot'),timeout_seconds=timeout_seconds)


def hyperv_hardware_inventory_script(vm_id):
    """Read-only host inventory command for commissioning, never executed here."""
    import uuid
    if str(uuid.UUID(vm_id))!=vm_id:raise ValueError('canonical_vm_guid_required')
    return '\n'.join([
        "$ErrorActionPreference='Stop';Import-Module Hyper-V",
        f'$v=Get-VM -Id ([guid]{ps_quote(vm_id)});$p=Get-VMProcessor -VM $v',
        '$slots=@(Get-VMHardDiskDrive -VM $v|ForEach-Object {"$($_.ControllerType):$($_.ControllerNumber):$($_.ControllerLocation)"}|Sort-Object)',
        '$switches=@(Get-VMNetworkAdapter -VM $v|ForEach-Object {[string]$_.SwitchId}|Sort-Object)',
        '$doc=[ordered]@{vm_id=$v.Id.ToString();name=$v.Name;generation=[int]$v.Generation;processors=[int]$p.Count;memory_startup=[long]$v.MemoryStartup;configuration_location=$v.ConfigurationLocation;disk_slots=$slots;network_switches=$switches}',
        '$raw=[Text.Encoding]::UTF8.GetBytes(($doc|ConvertTo-Json -Depth 8 -Compress))',
        '$hash=([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($raw))).Replace("-","").ToLowerInvariant()',
        '@{hardware=$doc;hardware_sha256=$hash;notes=$v.Notes}|ConvertTo-Json -Depth 8',
    ])
