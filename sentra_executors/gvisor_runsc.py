"""gVisor runsc OCI boundary: fail-closed bundle plan, optional pinned runner.

Only operator-supplied disposable Linux bundles and pinned runsc binary.
No runsc invocation unless allow_create=True and trusted runner approved.
Cannot attest host kernel/network isolation. No arbitrary shell fallback.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from sentra_runtime.contracts import Capability, Machine
from ._base import GuardedExecutor
from .rpa import effect_checkpoint

_CONTAINER_RE = re.compile(r"sentra-lab-[a-z0-9-]{3,45}\Z")


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for data in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(data)
    return digest.hexdigest()


def _no_symlink_chain(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError("symlink_or_reparse_path_denied")


def _contained(path: Path, parent: Path) -> bool:
    return path != parent and parent in path.parents


@dataclass(frozen=True)
class RunscLease:
    lease_id: str
    fence: int
    expires_monotonic: float

    def __post_init__(self):
        if (not self.lease_id or type(self.fence) is not int or self.fence <= 0
                or type(self.expires_monotonic) not in (float, int)
                or not math.isfinite(self.expires_monotonic)
                or self.expires_monotonic <= time.monotonic()):
            raise ValueError("invalid_runsc_lease")


@dataclass(frozen=True)
class RunscBinding:
    capability_id: str
    container_id: str
    bundle: Path
    state_root: Path
    binary: Path
    binary_sha256: str
    lease: RunscLease
    allowed_actions: tuple[str, ...] = ("inspect_bundle", "state")
    timeout_seconds: float = 5.0

    def __post_init__(self):
        if (not self.capability_id or not _CONTAINER_RE.fullmatch(self.container_id)
                or not set(self.allowed_actions).issubset(
                    {"inspect_bundle", "create", "state", "cleanup"})
                or not self.allowed_actions or
                "cleanup" in self.allowed_actions and "create" not in self.allowed_actions
                or not isinstance(self.bundle, Path) or not isinstance(self.state_root, Path)
                or not isinstance(self.binary, Path)
                or not re.fullmatch(r"[0-9a-f]{64}", self.binary_sha256)
                or not 0 < self.timeout_seconds <= 30):
            raise ValueError("invalid_runsc_binding")


def validate_oci_bundle(binding: RunscBinding) -> str:
    """Validate restricted OCI baseline, rootfs path, mounts and resource caps."""
    bundle, state, exe = binding.bundle, binding.state_root, binding.binary
    for path in (bundle, state, exe):
        if not path.is_absolute():
            raise ValueError("runsc_paths_must_be_absolute")
        _no_symlink_chain(path)
    if not bundle.is_dir() or not state.is_dir() or not exe.is_file():
        raise ValueError("runsc_paths_missing")
    if _sha_file(exe) != binding.binary_sha256:
        raise ValueError("runsc_binary_digest_mismatch")
    config = bundle / "config.json"
    _no_symlink_chain(config)
    if not config.is_file() or config.stat().st_size > 65_536:
        raise ValueError("oci_config_missing_or_too_large")
    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("oci_duplicate_manifest_key")
            result[key] = value
        return result
    payload = json.loads(config.read_text(encoding="utf-8"),
                         object_pairs_hook=reject_duplicate_keys)
    if (type(payload) is not dict or
            set(payload) != {"ociVersion", "root", "process", "mounts", "linux"}
            or payload["ociVersion"] != "1.0.2"):
        raise ValueError("invalid_or_unpinned_oci_manifest")
    root = payload.get("root")
    process = payload.get("process")
    linux = payload.get("linux")
    if (any(type(x) is not dict for x in (root, process, linux))
            or set(root) != {"path", "readonly"}
            or set(process) != {"args", "cwd", "env", "user",
                                "noNewPrivileges", "capabilities"}
            or set(linux) != {"namespaces", "resources"}):
        raise ValueError("invalid_or_extra_oci_sections")
    rp = root.get("path")
    if (type(rp) is not str or rp != "rootfs" or
            root.get("readonly") is not True):
        raise ValueError("oci_rootfs_scope_denied")
    rootfs = bundle / rp
    _no_symlink_chain(rootfs)
    if not rootfs.is_dir() or not _contained(rootfs, bundle):
        raise ValueError("oci_rootfs_escape")
    # The sole permitted command must actually reside inside this rootfs;
    # do not follow a host-targeted symlink to an executable outside.
    allowed_program = rootfs / "bin" / "true"
    _no_symlink_chain(allowed_program)
    if not allowed_program.is_file():
        raise ValueError("oci_pinned_command_missing")
    if payload["mounts"] != []:
        raise ValueError("oci_mounts_denied")
    if (process.get("args") != ["/bin/true"] or process.get("cwd") != "/"
            or process.get("env") not in ([], None)
            or process.get("noNewPrivileges") is not True
            or process.get("user") != {"uid": 65534, "gid": 65534}):
        raise ValueError("oci_process_not_allowlisted")
    caps = process.get("capabilities")
    if (type(caps) is not dict or
            set(caps) != {"bounding", "effective", "permitted",
                          "inheritable", "ambient"} or
            any(v != [] for v in caps.values())):
        raise ValueError("oci_linux_capabilities_denied")
    ns = linux.get("namespaces")
    if (type(ns) is not list
            or {item.get("type") for item in ns if type(item) is dict}
            != {"pid", "network", "mount", "ipc", "uts", "user"}
            or len(ns) != 6 or any(
                type(item) is not dict or set(item) != {"type"} for item in ns)):
        raise ValueError("oci_isolation_namespaces_required")
    resources = linux.get("resources")
    if (type(resources) is not dict or set(resources) != {"pids", "memory"}
            or resources.get("pids") != {"limit": 16}
            or resources.get("memory") != {"limit": 134217728}):
        raise ValueError("oci_resources_not_pinned")
    return hashlib.sha256(config.read_bytes()).hexdigest()


class PinnedRunscRunner:
    """Opt-in real subprocess only on Linux; no PATH search or shell."""
    def __init__(self, approved: bool = False):
        self.approved = approved

    def invoke(self, binary: Path, argv: tuple[str, ...], timeout: float):
        if not self.approved or sys.platform != "linux":
            raise PermissionError("runsc_real_linux_approval_required")
        effect_checkpoint()
        result = subprocess.run([str(binary), *argv], shell=False,
                                env={"PATH": "/usr/bin:/bin", "LANG": "C"},
                                cwd="/", capture_output=True, timeout=timeout,
                                check=False)
        if result.returncode != 0:
            raise RuntimeError("runsc_nonzero_exit")
        return {"exit_code": 0, "stdout_sha256":
                hashlib.sha256(result.stdout).hexdigest()}


class RunscExecutor(GuardedExecutor):
    kind = "gvisor_runsc"

    def __init__(self, *, machine_id: str, owner_principal_id: str,
                 bindings: tuple[RunscBinding, ...], policy,
                 lease_reader, runner=None, allow_create=False):
        if not callable(lease_reader):
            raise ValueError("trusted_lease_reader_required")
        if len({b.capability_id for b in bindings}) != len(bindings):
            raise ValueError("duplicate_runsc_capability")
        super().__init__(machine_id=machine_id, owner_principal_id=owner_principal_id,
                         bindings={b.capability_id: b for b in bindings}, policy=policy)
        self.lease_reader = lease_reader
        self.runner = runner if runner is not None else PinnedRunscRunner()
        self.allow_create = bool(allow_create)
        self._lock_effect = threading.RLock()
        self._created: set[str] = set()
        self._uncertain: set[str] = set()
        self._deleted: set[str] = set()

    def _validate(self, request, binding):
        args = dict(request.arguments)
        if (set(args) != {"action", "container_id", "lease_id", "fence"} or
                args["action"] not in binding.allowed_actions
                or args["container_id"] != binding.container_id
                or args["lease_id"] != binding.lease.lease_id
                or type(args["fence"]) is not int or args["fence"] != binding.lease.fence):
            raise ValueError("runsc_capability_or_fence_denied")
        return args

    def _verify(self, binding):
        if self.lease_reader(binding.lease.lease_id) != binding.lease:
            raise PermissionError("runsc_stale_fence")
        if time.monotonic() >= binding.lease.expires_monotonic:
            raise PermissionError("runsc_lease_expired")
        return validate_oci_bundle(binding)

    def _execute(self, binding, args):
        action, cid = args["action"], binding.container_id
        with self._lock_effect:
            digest = self._verify(binding)
            if action == "inspect_bundle":
                return {"oci_config_sha256": digest, "container_id": cid}
            if action == "create" and not self.allow_create:
                raise PermissionError("runsc_create_disabled")
            if action == "cleanup" and cid not in self._created:
                raise PermissionError("runsc_cleanup_unmanaged")
            if action == "create" and (cid in self._created or cid in self._uncertain):
                raise RuntimeError("runsc_create_already_claimed")
            if action == "cleanup" and cid in self._deleted:
                return {"container_id": cid, "state": "deleted"}
            if cid in self._uncertain:
                raise RuntimeError("runsc_uncertain_manual_reconcile")
            prefix = (f"--root={binding.state_root}", "--network=none")
            if action == "create":
                argv = (*prefix, "create", "--bundle", str(binding.bundle), cid)
                self._uncertain.add(cid)  # before external effect
            elif action == "state":
                argv = (*prefix, "state", cid)
            else:
                argv = (*prefix, "delete", cid)
                self._uncertain.add(cid)
            try:
                effect_checkpoint()
                response = self.runner.invoke(binding.binary, argv, binding.timeout_seconds)
                if type(response) is not dict or response.get("exit_code") != 0:
                    raise RuntimeError("runsc_response_invalid")
                self._verify(binding)  # failure after effect leaves UNCERTAIN
                if action == "create":
                    self._created.add(cid)
                if action == "cleanup":
                    self._deleted.add(cid)
                self._uncertain.discard(cid)
                return {"container_id": cid, "action": action,
                        "oci_config_sha256": digest,
                        "runner_exit_code": 0}
            except Exception:
                if action not in ("create", "cleanup"):
                    self._uncertain.add(cid)
                raise


def declare_runsc_machine(*, machine_id, owner_principal_id, bindings, policy,
                          lease_reader, runner=None, allow_create=False):
    from .discovery import MachineDeclaration
    machine = Machine(machine_id, "gvisor_runsc", owner_principal_id, tuple(
        Capability(b.capability_id, "Restricted pinned OCI/runsc capability", "critical")
        for b in bindings))
    return MachineDeclaration(machine, RunscExecutor(
        machine_id=machine_id, owner_principal_id=owner_principal_id,
        bindings=bindings, policy=policy, lease_reader=lease_reader,
        runner=runner, allow_create=allow_create))
