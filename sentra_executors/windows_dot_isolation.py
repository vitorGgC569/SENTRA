"""Windows Dot layouts, commissioning checks and explicit central collection.

Import/planning/recovery have no guest effects. collect_windows_probe is the
explicit guest-read entry through MachineHost; it is not invoked on import.
This module neither provisions users/VMs nor grants a capability. Inventory
must come from the trusted host and probes must be collected through existing
ControlPlane/GuestControl operations. A successful structural check is not an
attestation against a malicious guest, a central receipt, or a Grant.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import math
import ntpath
import re
import time
import uuid
from typing import Mapping, Sequence


_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_USER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,19}\Z")
_SID = re.compile(r"S-1-5-21-(\d+)-(\d+)-(\d+)-(\d+)\Z")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)
_SYSTEM = "S-1-5-18"
_ADMINS = "S-1-5-32-544"
_DANGEROUS_PRIVILEGES = frozenset({
    "SeDebugPrivilege", "SeBackupPrivilege", "SeRestorePrivilege",
    "SeTakeOwnershipPrivilege", "SeImpersonatePrivilege", "SeTcbPrivilege",
    "SeCreateTokenPrivilege", "SeAssignPrimaryTokenPrivilege", "SeLoadDriverPrivilege",
    "SeSecurityPrivilege", "SeManageVolumePrivilege", "SeRelabelPrivilege",
    "SeTrustedCredManAccessPrivilege", "SeSystemEnvironmentPrivilege",
})


def _token(value: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value) or ".." in value:
        raise ValueError("bounded_identity_required")
    return value


def _guid(value: str) -> str:
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("canonical_guid_required")
    if uuid.UUID(value).int == 0:
        raise ValueError("nonzero_guid_required")
    return value


def _private_path(value: str) -> str:
    """Lexical checks only. Reparse points and effective ACLs need guest probes."""
    if not isinstance(value, str) or len(value) > 240 or "/" in value:
        raise ValueError("local_private_windows_path_required")
    if not re.match(r"^[A-Za-z]:\\", value):
        raise ValueError("local_private_windows_path_required")
    parts = value[3:].split("\\")
    if (not parts or any(not p or p in {".", ".."} or p[-1:] in {".", " "}
                         or _RESERVED.fullmatch(p) or any(ord(c) < 32 or c in '<>:"|?*' for c in p)
                         for p in parts)):
        raise ValueError("unambiguous_private_windows_path_required")
    # Avoid accepting system roots as a user's private directory.
    if parts[0].casefold() in {"windows", "program files", "program files (x86)", "programdata"}:
        raise ValueError("system_directory_is_not_private_workspace")
    if len(parts) < 2 or parts[0].casefold() == "users" and parts[1].casefold() in {
            "public", "default", "default user", "all users"}:
        raise ValueError("private_subdirectory_required")
    return ntpath.normcase(value)


def _overlaps(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "\\") or right.startswith(left + "\\")


@dataclass(frozen=True)
class WindowsDotAccount:
    owner: str
    dot_id: str
    vm_id: str
    username: str
    user_sid: str
    profile_path: str
    workspace_path: str
    credential_ref: str = field(repr=False)

    def __post_init__(self):
        for value in (self.owner, self.dot_id, self.credential_ref):
            _token(value)
        _guid(self.vm_id)
        if (not isinstance(self.username, str) or not _USER.fullmatch(self.username)
                or self.username.casefold() in {"administrator", "administrador", "guest", "defaultaccount", "wdagutilityaccount"}):
            raise ValueError("dedicated_local_username_required")
        sid = _SID.fullmatch(self.user_sid) if isinstance(self.user_sid, str) else None
        if (not sid or not all(0 < int(n) <= 4294967295 and str(int(n)) == n for n in sid.groups())
                or int(sid[4]) < 1000):
            raise ValueError("dedicated_local_user_sid_required")
        if _private_path(self.profile_path) == _private_path(self.workspace_path):
            raise ValueError("dedicated_workspace_subdirectory_required")


def validate_account_layout(accounts: Sequence[WindowsDotAccount], *, strategy: str) -> None:
    """Reject aliases/reused secrets/private trees before any provisioning."""
    if strategy not in {"shared_users", "linked_clones"} or not 1 <= len(accounts) <= 200:
        raise ValueError("bounded_known_layout_required")
    seen = {name: set() for name in ("dot", "sid", "username", "credential", "vm")}
    for i, account in enumerate(accounts):
        keys = {"dot": (account.owner, account.dot_id), "sid": (account.vm_id, account.user_sid),
                "username": (account.vm_id, account.username.casefold()), "credential": account.credential_ref}
        if strategy == "linked_clones":
            keys["vm"] = account.vm_id
        for kind, key in keys.items():
            if key in seen[kind]:
                raise ValueError("reused_" + kind)
            seen[kind].add(key)
        for other in accounts[:i]:
            if other.vm_id == account.vm_id:
                if any(_overlaps(_private_path(a), _private_path(b))
                       for a in (account.profile_path, account.workspace_path)
                       for b in (other.profile_path, other.workspace_path)):
                    raise ValueError("overlapping_private_directories")
    if strategy == "shared_users" and len({a.vm_id for a in accounts}) != 1:
        raise ValueError("one_shared_vm_required")


@dataclass(frozen=True)
class GoldenImage:
    vm_id: str
    snapshot_id: str
    disk_id: str
    disk_sha256: str
    generalized: bool
    credentials_absent: bool
    sentra_identity_absent: bool
    desktop_and_guestcontrol_verified: bool

    def __post_init__(self):
        for value in (self.vm_id, self.snapshot_id, self.disk_id):
            _guid(value)
        if not isinstance(self.disk_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.disk_sha256):
            raise ValueError("pinned_base_hash_required")
        for name in ("generalized", "credentials_absent", "sentra_identity_absent", "desktop_and_guestcontrol_verified"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("explicit_image_readiness_required")

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(name for name in ("generalized", "credentials_absent", "sentra_identity_absent",
                                      "desktop_and_guestcontrol_verified") if not getattr(self, name))


@dataclass(frozen=True)
class CloneIdentity:
    vm_id: str
    disk_id: str
    parent_disk_id: str
    installation_id: str
    machine_guid: str
    mac: str

    def __post_init__(self):
        for value in (self.vm_id, self.disk_id, self.parent_disk_id, self.machine_guid):
            _guid(value)
        _token(self.installation_id)
        if not isinstance(self.mac, str) or not re.fullmatch(r"[0-9A-F]{12}", self.mac) or int(self.mac[:2], 16) & 1:
            raise ValueError("unicast_canonical_mac_required")
        if int(self.mac, 16) == 0:
            raise ValueError("nonzero_mac_required")


def validate_clone_layout(base: GoldenImage, clones: Sequence[CloneIdentity]) -> None:
    if base.blockers:
        raise ValueError("golden_image_not_commissioned:" + ",".join(base.blockers))
    if not 1 <= len(clones) <= 200:
        raise ValueError("bounded_clone_count_required")
    seen = {name: set() for name in ("vm_id", "disk_id", "installation_id", "machine_guid", "mac")}
    for clone in clones:
        if clone.parent_disk_id != base.disk_id or clone.vm_id == base.vm_id or clone.disk_id == base.disk_id:
            raise ValueError("clone_must_have_distinct_vm_and_child_disk_of_pinned_base")
        for name, values in seen.items():
            value = getattr(clone, name)
            if value in values:
                raise ValueError("reused_clone_" + name)
            values.add(value)


def estimate_resources(*, base_bytes: int, dots: int, delta_bytes_per_dot: int,
                       profile_bytes_per_dot: int, ram_per_vm_bytes: int,
                       host_reserve_bytes: int, host_ram_bytes: int,
                       max_running_clones: int = 1) -> dict:
    values = (base_bytes, dots, delta_bytes_per_dot, profile_bytes_per_dot,
              ram_per_vm_bytes, host_reserve_bytes, host_ram_bytes, max_running_clones)
    if any(type(n) is not int or n < 0 for n in values) or not 1 <= dots <= 200 or not base_bytes or not ram_per_vm_bytes or not 1 <= max_running_clones <= dots:
        raise ValueError("bounded_nonnegative_resource_budget_required")
    available = max(0, host_ram_bytes - host_reserve_bytes)
    active = min(dots, max_running_clones, available // ram_per_vm_bytes)
    return {"full_clone_base_disk_bytes": dots * base_bytes,
            "linked_clone_disk_bytes": base_bytes + dots * delta_bytes_per_dot,
            "shared_user_disk_bytes": base_bytes + dots * profile_bytes_per_dot,
            "running_clone_limit": active, "one_shared_vm_fits_ram": available >= ram_per_vm_bytes,
            "estimated_active_ram_bytes": host_reserve_bytes + active * ram_per_vm_bytes,
            "measured": False, "includes_snapshot_merge_backup_and_disk_overhead": False,
            "licenses_included": False}


def console_resource_id(vm_id: str) -> str:
    """Matches input_control.resource_for_declaration for canonical VBox UUIDs."""
    return hashlib.sha256(("virtualbox:" + _guid(vm_id)).encode()).hexdigest()


def assess_console_possession(account: WindowsDotAccount, status: Mapping, *,
                              machine_id: str, principal_id: str, work_item_id: str,
                              expected_epoch: int, now: float) -> tuple[str, ...]:
    """Check a fresh trusted InputControl.status projection; never grants input.

    Actual dispatch still requires live BoundWorkItemPolicy, central lease/fence
    and effect_checkpoint immediately before IO. No per-Dot console resource.
    """
    if not isinstance(status, Mapping):
        return ("console_status_not_mapping",)
    expected = {"resource_id": console_resource_id(account.vm_id), "machine_id": machine_id,
                "principal_id": principal_id, "work_item_id": work_item_id, "holder": "agent"}
    issues = ["console_" + key + "_mismatch" for key, value in expected.items() if status.get(key) != value]
    if type(expected_epoch) is not int or expected_epoch < 1 or type(status.get("epoch")) is not int or status.get("epoch") != expected_epoch:
        issues.append("console_epoch_mismatch")
    expires = status.get("expires_at")
    if (status.get("live") is not True or type(expires) not in (int, float)
            or expires < 0 or not math.isfinite(expires) or type(now) not in (int, float)
            or now < 0 or not math.isfinite(now) or not expires > now):
        issues.append("console_lease_not_live")
    return tuple(issues)


def account_probe_script(account: WindowsDotAccount, *, nonce: str,
                         peer_canaries: Sequence[str] = ()) -> str:
    """Read-only script to submit via authorized GuestControl, never executed here.

    Canaries must be pre-existing disposable files, provisioned by another
    authorized operation. Opening a read handle tests access without reading
    contents. Missing files and other failures do not count as denied access.
    No GUI/session-isolation claim is made from a GuestControl process.
    """
    _token(nonce)
    _canary_paths(peer_canaries)
    payload = {"nonce": nonce, "paths": [account.profile_path, account.workspace_path], "canaries": list(peer_canaries)}
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=True).encode()).decode()
    return _PROBE.replace("PAYLOAD_BASE64", encoded)


_PROBE = r'''
$ErrorActionPreference='Stop'
$config=([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PAYLOAD_BASE64'))|ConvertFrom-Json)
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$profileKey='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\'+$identity.User.Value
$profile=[Environment]::ExpandEnvironmentVariables((Get-ItemProperty -LiteralPath $profileKey).ProfileImagePath)
$whoami=Join-Path ([Environment]::SystemDirectory) 'whoami.exe'
$privRaw=@(& $whoami /priv /fo csv /nh)
if($LASTEXITCODE -ne 0){throw 'privilege_inventory_failed'}
$privileges=@($privRaw|ConvertFrom-Csv -Header Name,Description,State|ForEach-Object {$_.Name})
$directories=@(foreach($path in $config.paths){
  $item=Get-Item -LiteralPath $path -Force
  $acl=Get-Acl -LiteralPath $path
  $cursor=$item;$reparse=$false
  while($null -ne $cursor){
    if(($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){$reparse=$true}
    $cursor=$cursor.Parent
  }
  @{path=$path;is_directory=[bool]$item.PSIsContainer;reparse_ancestor=$reparse;
    owner_sid=$acl.GetOwner([Security.Principal.SecurityIdentifier]).Value;
    protected=[bool]$acl.AreAccessRulesProtected;
    allow_sids=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])|
      Where-Object {$_.AccessControlType -eq 'Allow'}|ForEach-Object {$_.IdentityReference.Value}|Sort-Object -Unique)}
})
$canaries=@(foreach($path in $config.canaries){
  $state='error';$handle=$null
  try{$handle=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite);$state='readable'}
  catch [UnauthorizedAccessException]{$state='denied'}
  catch [IO.FileNotFoundException]{$state='missing'}
  catch [IO.DirectoryNotFoundException]{$state='missing'}
  catch {$state='error'}
  finally{if($null -ne $handle){$handle.Dispose()}}
  @{path=$path;state=$state}
})
@{schema='sentra-windows-account-probe-v1';nonce=$config.nonce;
  user_sid=$identity.User.Value;group_sids=@($identity.Groups|ForEach-Object {$_.Value});
  privilege_names=$privileges;profile_path=$profile;
  machine_guid=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Cryptography').MachineGuid;
  session_id=[Diagnostics.Process]::GetCurrentProcess().SessionId;
  interactive_console_verified=$false;directories=$directories;canaries=$canaries}|ConvertTo-Json -Depth 8 -Compress
'''.strip()


@dataclass(frozen=True)
class ProbeAssessment:
    issues: tuple[str, ...]
    structural_checks_passed: bool
    authorization_granted: bool = False
    isolation_homologated: bool = False
    gui_session_verified: bool = False


def _canary_paths(paths: Sequence[str]) -> set[str]:
    if not isinstance(paths, (tuple, list)) or len(paths) > 32:
        raise ValueError("bounded_unique_canaries_required")
    normalized = {_private_path(p) for p in paths}
    if len(normalized) != len(paths):
        raise ValueError("bounded_unique_canaries_required")
    return normalized


def assess_account_probe(account: WindowsDotAccount, probe: Mapping, *, nonce: str,
                         expected_machine_guid: str, peer_canaries: Sequence[str] = ()) -> ProbeAssessment:
    """Structural commissioning checks, not guest attestation or effect admission.

    Caller must separately verify the central Operation/receipt and bind stdout
    to this configured VM/account and probe command. No trust in a model-provided
    stdout, boolean success flag, or old JSON fixture is implied by this API.
    """
    _token(nonce)
    _guid(expected_machine_guid)
    expected_canaries = _canary_paths(peer_canaries)
    issues = []
    if not isinstance(probe, Mapping):
        return ProbeAssessment(("probe_not_mapping",), False)
    for key, value in {"schema": "sentra-windows-account-probe-v1", "nonce": nonce,
                       "user_sid": account.user_sid, "machine_guid": expected_machine_guid}.items():
        if probe.get(key) != value:
            issues.append("probe_" + key + "_mismatch")
    try:
        if _private_path(probe.get("profile_path")) != _private_path(account.profile_path):
            issues.append("profile_mismatch")
    except ValueError:
        issues.append("profile_mismatch")
    groups, privileges = probe.get("group_sids"), probe.get("privilege_names")
    if not isinstance(groups, list) or not groups or any(not isinstance(s, str) for s in groups) or _ADMINS in groups:
        issues.append("non_admin_membership_not_proven")
    if not isinstance(privileges, list) or any(not isinstance(s, str) for s in privileges) or not privileges or _DANGEROUS_PRIVILEGES.intersection(privileges):
        issues.append("limited_privileges_not_proven")
    directories = probe.get("directories")
    expected_paths = {_private_path(account.profile_path), _private_path(account.workspace_path)}
    found = set()
    if not isinstance(directories, list):
        directories = []
        issues.append("private_directories_missing")
    for entry in directories:
        try:
            path = _private_path(entry["path"])
            if path not in expected_paths or path in found:
                raise ValueError("unexpected_directory")
            found.add(path)
            allowed = {account.user_sid, _SYSTEM, _ADMINS}
            sids = entry.get("allow_sids")
            if (entry.get("is_directory") is not True or entry.get("protected") is not True
                    or entry.get("reparse_ancestor") is not False or entry.get("owner_sid") not in allowed
                    or not isinstance(sids, list) or not sids or any(not isinstance(s, str) or s not in allowed for s in sids)
                    or account.user_sid not in sids):
                issues.append("private_acl_or_path_unproven")
        except (ValueError, TypeError, KeyError):
            issues.append("invalid_private_directory_evidence")
    if found != expected_paths:
        issues.append("private_directories_missing")
    found_canaries = set()
    entries = probe.get("canaries")
    if not isinstance(entries, list):
        entries = []
        issues.append("canary_evidence_missing")
    for entry in entries:
        try:
            path = _private_path(entry["path"])
            if path not in expected_canaries or path in found_canaries:
                raise ValueError("unexpected_canary")
            found_canaries.add(path)
            if entry.get("state") != "denied":
                issues.append("peer_canary_access_not_denied")
        except (ValueError, TypeError, KeyError):
            issues.append("invalid_canary_evidence")
    if found_canaries != expected_canaries:
        issues.append("canary_evidence_missing")
    return ProbeAssessment(tuple(dict.fromkeys(issues)), not issues)


@dataclass(frozen=True)
class PreparedWindowsProbe:
    """Host-only plan. Persist it only in protected host state if needed."""
    account: WindowsDotAccount
    workspace_id: str
    conversation_id: str
    machine_guid: str
    nonce: str
    peer_canaries: tuple[str, ...]
    run_id: str
    request: object
    prepared_at: float


def _probe_scope(control, account, workspace_id, conversation_id):
    """Resolve identity from the protected Dot registry and existing governance."""
    from contextlib import closing
    from sentra_core.conversations import _decode
    from sentra_mcp.services.control_plane import ControlPlaneService
    if not isinstance(control, ControlPlaneService):
        raise TypeError("real_control_plane_required")
    if not isinstance(account, WindowsDotAccount):
        raise TypeError("host_enrolled_windows_account_required")
    _token(workspace_id)
    _token(conversation_id)
    with closing(control.store.connect("shell")) as db:
        row = db.execute("SELECT body FROM shell_dot_vms WHERE owner=? AND project=? AND root=?",
                         (account.owner, workspace_id, account.dot_id)).fetchone()
    if row is None:
        raise PermissionError("configured_dot_vm_required")
    cfg = _decode(row["body"])
    if (cfg.get("vm_id") != account.vm_id or cfg.get("root_dot_id") != account.dot_id
            or cfg.get("os_family") != "windows" or not isinstance(cfg.get("username"), str)
            or cfg["username"].casefold() != account.username.casefold()):
        raise PermissionError("configured_windows_account_mismatch")
    wid = cfg.get("work_items", {}).get(conversation_id)
    if not wid:
        raise PermissionError("owning_conversation_work_item_required")
    item = control.work_item_info(wid, account.owner)
    meta = item.get("metadata") or {}
    if (item.get("owner") != account.owner or item.get("state") != "RUNNING"
            or item.get("assignee_agent_id") != cfg.get("agent_id")
            or meta.get("workspace_id") != workspace_id or meta.get("machine_id") != cfg.get("machine_id")
            or meta.get("conversation_id") != conversation_id or meta.get("root_dot_id") != account.dot_id
            or control.durable.run_status(item["run_id"], account.owner, include_details=False)["state"] != "RUNNING"):
        raise PermissionError("active_dot_work_item_scope_required")
    return item["run_id"], cfg["machine_id"], cfg["agent_id"], wid


def prepare_windows_probe(control, account: WindowsDotAccount, *, workspace_id: str,
                          conversation_id: str, expected_machine_guid: str, nonce: str,
                          operation_id: str, idempotency_key: str,
                          peer_canaries: tuple[str, ...] = ()) -> PreparedWindowsProbe:
    """Prepare exact read probe from trusted host enrollment; does not dispatch.

    SID, MachineGuid and account paths must have been enrolled independently by
    the authenticated owner, never supplied by the model being evaluated.
    Existing registry credentials remain private and are resolved by MachineHost.
    """
    from sentra_runtime.contracts import OperationRequest
    _guid(expected_machine_guid)
    _token(operation_id)
    _token(idempotency_key)
    run, machine, agent, work = _probe_scope(control, account, workspace_id, conversation_id)
    command = account_probe_script(account, nonce=nonce, peer_canaries=peer_canaries)
    request = OperationRequest(operation_id, agent, machine, "vm:guest", work, idempotency_key,
                               {"action": "guest.run", "command": command, "timeout_seconds": 60})
    prepared = PreparedWindowsProbe(account, workspace_id, conversation_id, expected_machine_guid,
                                    nonce, tuple(peer_canaries), run, request, time.time())
    _check_prepared_probe(control, prepared)
    return prepared


def _check_prepared_probe(control, prepared):
    from sentra_runtime.authority_bridge import BoundWorkItemPolicy
    from sentra_runtime.contracts import OperationRequest
    from sentra_runtime.executor import _request_snapshot
    if not isinstance(prepared, PreparedWindowsProbe) or not isinstance(prepared.request, OperationRequest):
        raise TypeError("host_prepared_probe_required")
    run, machine, agent, work = _probe_scope(control, prepared.account, prepared.workspace_id,
                                            prepared.conversation_id)
    request = prepared.request
    expected_args = {"action": "guest.run", "command": account_probe_script(prepared.account,
                     nonce=prepared.nonce, peer_canaries=prepared.peer_canaries), "timeout_seconds": 60}
    if (run != prepared.run_id or request.machine_id != machine or request.principal_id != agent
            or request.work_item_id != work or request.capability_id != "vm:guest"
            or request.arguments != expected_args):
        raise PermissionError("prepared_probe_scope_or_command_changed")
    policy = BoundWorkItemPolicy(owner=prepared.account.owner, principal_type="agent",
                                authorization=control.authorization, governance=control.governance)
    if policy(request).allowed is not True:
        raise PermissionError("live_vm_guest_grant_required")
    return _request_snapshot(request)[1]


@dataclass(frozen=True)
class CentralProbeObservation:
    operation_id: str
    state: str
    central_receipt_verified: bool
    guest_execution_receipt_verified: bool
    assessment: ProbeAssessment | None
    automatic_retry: bool = False
    isolation_homologated: bool = False


def recover_windows_probe(control, prepared: PreparedWindowsProbe) -> CentralProbeObservation:
    """Read only the canonical hash-verified protected central result artifact.

    No caller-supplied JSON/stdout/receipt is accepted. No provider is contacted.
    A terminal or uncertain Operation is never promoted from late-return data.
    """
    from sentra_runtime.central_authority import CentralDurableIntentAuthority
    fingerprint = _check_prepared_probe(control, prepared)
    request = prepared.request
    owner = prepared.account.owner
    authority = CentralDurableIntentAuthority(control.durable)
    receipt = authority.receipt_for_operation(request.operation_id, owner)
    if receipt.run_id != prepared.run_id or receipt.intent_sha256 != fingerprint:
        raise PermissionError("canonical_probe_intent_mismatch")
    row = control.durable.operation_status(request.operation_id, owner)
    if (type(prepared.prepared_at) not in (float, int) or not math.isfinite(prepared.prepared_at)
            or not prepared.prepared_at - 1 <= row["started_at"] <= row["updated_at"] <= time.time() + 1
            or time.time() - row["updated_at"] > 300):
        raise PermissionError("canonical_probe_stale_or_time_mismatch")
    result = authority.result_for_receipt(receipt)
    if result is None or result.state != "SUCCEEDED":
        return CentralProbeObservation(request.operation_id, row["state"], result is not None, False, None)
    evidence = result.evidence
    if (evidence.get("vm_id") != prepared.account.vm_id or evidence.get("execution_surface") != "guest"
            or evidence.get("guest_process_confirmed") is not True
            or evidence.get("claims_guest_execution") is not True or evidence.get("host_subprocess") is not False
            or evidence.get("execution_uncertain") is not False):
        raise PermissionError("canonical_result_does_not_prove_guest_process")
    stdout = evidence.get("stdout")
    if not isinstance(stdout, str) or not 1 <= len(stdout) <= 131072:
        raise ValueError("bounded_canonical_probe_stdout_required")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate_probe_json_key")
            value[key] = item
        return value
    probe = json.loads(stdout.lstrip("\ufeff"), object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_probe_json")))
    assessment = assess_account_probe(prepared.account, probe, nonce=prepared.nonce,
                                      expected_machine_guid=prepared.machine_guid,
                                      peer_canaries=prepared.peer_canaries)
    # Recheck revocation/binding after reading the protected artifact.
    _check_prepared_probe(control, prepared)
    return CentralProbeObservation(request.operation_id, result.state, True, True, assessment)


def collect_windows_probe(host, prepared: PreparedWindowsProbe) -> CentralProbeObservation:
    """Explicit effectful entry; use only when guest execution is authorized.

    Uses existing MachineHost admission/fences and the configured VBox executor.
    An existing Operation is observed, never dispatched a second time. The live
    VirtualBox executor remains responsible for Guest Additions/guest placement.
    This entry has NOT been invoked against the existing Windows VM in this QA.
    """
    from sentra_runtime.machine_host import MachineHost
    if not isinstance(host, MachineHost) or host.owner != prepared.account.owner:
        raise PermissionError("owning_machine_host_required")
    _check_prepared_probe(host.control, prepared)
    request = prepared.request
    try:
        host.control.durable.operation_status(request.operation_id, host.owner)
    except FileNotFoundError:
        registered = next((m for m in host.inventory(prepared.workspace_id)
                           if m.get("machine_id") == request.machine_id), None)
        if (not registered or registered.get("kind") != "virtualbox_vm"
                or registered.get("vm_id") != prepared.account.vm_id
                or registered.get("root_dot_id") != prepared.account.dot_id
                or registered.get("agent_id") != request.principal_id
                or "vm:guest" not in registered.get("capabilities", ())):
            raise PermissionError("configured_virtualbox_machine_host_required")
        host.dispatch(workspace_id=prepared.workspace_id, work_item_id=request.work_item_id,
                      machine_id=request.machine_id, capability_id=request.capability_id,
                      operation_id=request.operation_id, idempotency_key=request.idempotency_key,
                      arguments=dict(request.arguments))
    return recover_windows_probe(host.control, prepared)
