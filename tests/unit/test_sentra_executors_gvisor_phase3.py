"""Phase3 gVisor: OCI contract, pinned subprocess fixture; NO real runsc."""
from __future__ import annotations
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sentra_runtime.contracts import OperationRequest, PolicyDecision
from sentra_runtime.executor import ExecutorRegistry, AuthorizationRequired
from sentra_executors import (
    RunscLease, RunscBinding, PinnedRunscRunner,
    declare_runsc_machine, validate_oci_bundle,
)


def run(coro):
    return asyncio.run(coro)


class Grant:
    allowed = True
    def __call__(self, request):
        return PolicyDecision(self.allowed, "lab")


def spec():
    return {
        "ociVersion": "1.0.2",
        "root": {"path": "rootfs", "readonly": True},
        "process": {"args": ["/bin/true"], "cwd": "/", "env": [],
                    "user": {"uid": 65534, "gid": 65534},
                    "noNewPrivileges": True,
                    "capabilities": {"bounding": [], "effective": [],
                                     "permitted": [], "inheritable": [],
                                     "ambient": []}},
        "mounts": [], "linux": {
            "namespaces": [{"type": v} for v in
                           ("pid", "network", "mount", "ipc", "uts", "user")],
            "resources": {"memory": {"limit": 134217728}, "pids": {"limit": 16}}}
    }


class SubprocessRunscFixture:
    """Runs our pinned fake runsc using Python -I -B in a disposable tmpdir."""
    def __init__(self, directory, *, fail=False, sleep=0):
        self.calls = []
        self.output = directory / "called.jsonl"
        self.script = directory / "fake_runsc.py"
        self.script.write_text(
            "import json,sys,time\n"
            f"time.sleep({sleep!r})\n"
            f"with open({str(self.output)!r},'a') as f: "
            "f.write(json.dumps(sys.argv[1:])+'\\n')\n"
            f"raise SystemExit({1 if fail else 0})\n", encoding="utf8")

    def invoke(self, binary, argv, timeout):
        self.calls.append((str(binary), tuple(argv)))
        completed = subprocess.run(
            [sys.executable, "-I", "-B", str(self.script), *argv],
            shell=False, capture_output=True, timeout=timeout, check=False)
        if completed.returncode != 0:
            raise RuntimeError("runsc_fixture_failed")
        return {"exit_code": 0}


def sandbox(tmp_path, *, actions=("inspect_bundle", "state", "create", "cleanup"),
            grant=None, runner=None, enabled=True):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "rootfs" / "bin").mkdir(parents=True)
    (bundle / "rootfs" / "bin" / "true").write_bytes(b"fixture only; never executed")
    (bundle / "config.json").write_text(json.dumps(spec()), encoding="utf8")
    state = tmp_path / "state"
    state.mkdir()
    binary = tmp_path / "runsc-fixture"
    binary.write_bytes(b"pinned mock binary, never executed")
    lease = RunscLease("lease-1", 9, time.monotonic()+40)
    binding = RunscBinding(
        "gvisor-lab", "sentra-lab-demo", bundle, state, binary,
        hashlib.sha256(binary.read_bytes()).hexdigest(),
        lease, actions, timeout_seconds=.5)
    policy = grant if grant is not None else Grant()
    runner = runner if runner is not None else SubprocessRunscFixture(tmp_path)
    declaration = declare_runsc_machine(
        machine_id="gvisor-machine", owner_principal_id="lab",
        bindings=(binding,), policy=policy,
        lease_reader=lambda _id: lease, runner=runner, allow_create=enabled)
    registry = ExecutorRegistry(authorize=policy)
    declaration.register(registry)
    return registry, policy, runner, binding, declaration


def req(action, op=None):
    op = op or ("runsc-" + action)
    return OperationRequest(
        op, "lab", "gvisor-machine", "gvisor-lab", "lab-work", op,
        {"action": action, "container_id": "sentra-lab-demo",
         "lease_id": "lease-1", "fence": 9})


def test_oci_fixture_subprocess_registry_create_state_cleanup_idempotent(tmp_path):
    registry, policy, runner, binding, declaration = sandbox(tmp_path)
    assert [x.capability_id for x in run(declaration.discover())] == ["gvisor-lab"]
    read = run(registry.submit(req("inspect_bundle")))
    assert read.state == "SUCCEEDED" and len(read.evidence["oci_config_sha256"]) == 64
    assert runner.calls == []
    created = run(registry.submit(req("create")))
    assert created.state == "SUCCEEDED"
    repeated = run(registry.submit(req("create")))
    assert repeated.state == "SUCCEEDED"
    status = run(registry.submit(req("state")))
    assert status.state == "SUCCEEDED"
    deleted = run(registry.submit(req("cleanup")))
    assert deleted.state == "SUCCEEDED"
    delete_again = run(registry.submit(req("cleanup", op="cleanup-new-key")))
    assert delete_again.state == "SUCCEEDED"
    assert len(runner.calls) == 3
    invocations = [json.loads(x) for x in runner.output.read_text().splitlines()]
    assert [line[2] for line in invocations] == ["create", "state", "delete"]
    assert all("--network=none" in line for line in invocations)
    assert all("--root=" in line[0] for line in invocations)
    policy.allowed = False
    with pytest.raises(AuthorizationRequired):
        run(registry.submit(req("state")))
    assert len(runner.calls) == 3


@pytest.mark.parametrize("mutation", [
    "outbound", "mount", "rootfs_escape", "hooks", "privileged",
    "host_network", "oversize", "command", "memory",
    "extra_linux", "annotations", "bad_version", "unexpected_syscall",
])
def test_oci_escape_and_network_deny_before_runner(tmp_path, mutation):
    registry, _, runner, binding, _ = sandbox(tmp_path)
    data = spec()
    if mutation == "outbound":
        data["process"]["args"] = ["/usr/bin/curl", "https://example.com"]
    elif mutation == "mount":
        data["mounts"] = [{"source": "/home", "destination": "/mnt"}]
    elif mutation == "rootfs_escape":
        data["root"]["path"] = "../../Users"
    elif mutation == "hooks":
        data["hooks"] = {"prestart": [{"path": "/bin/sh"}]}
    elif mutation == "privileged":
        data["process"]["capabilities"]["bounding"] = ["CAP_SYS_ADMIN"]
    elif mutation == "host_network":
        data["linux"]["namespaces"] = [{"type": "pid"}]
    elif mutation == "oversize":
        data["payload"] = "x"*66000
    elif mutation == "command":
        data["process"]["env"] = ["HOME=/host"]
    elif mutation == "memory":
        data["linux"]["resources"]["memory"]["limit"] = -1
    elif mutation == "extra_linux":
        data["linux"]["devices"] = [{"path": "/dev/kvm"}]
    elif mutation == "annotations":
        data["annotations"] = {"runsc.io/host": "true"}
    elif mutation == "bad_version":
        data["ociVersion"] = "1.2.0"
    elif mutation == "unexpected_syscall":
        data["process"]["apparmorProfile"] = "unapproved"
    (binding.bundle / "config.json").write_text(json.dumps(data), encoding="utf8")
    result = run(registry.submit(req("create")))
    assert result.state == "FAILED" and result.evidence == {}
    assert runner.calls == []


def test_runsc_symlink_rootfs_refused(tmp_path):
    registry, _, runner, binding, _ = sandbox(tmp_path)
    rootfs = binding.bundle / "rootfs"
    (rootfs / "bin" / "true").unlink()
    (rootfs / "bin").rmdir()
    rootfs.rmdir()
    try:
        rootfs.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("test OS cannot create directory symlinks")
    result = run(registry.submit(req("create")))
    assert result.state == "FAILED" and runner.calls == []


def test_binary_hash_mismatch_and_path_traversal_denial(tmp_path):
    registry, _, runner, binding, _ = sandbox(tmp_path)
    binding.binary.write_bytes(b"replaced binary")
    result = run(registry.submit(req("create")))
    assert result.state == "FAILED" and runner.calls == []


def test_runsc_create_disabled_default(tmp_path):
    registry, _, runner, _, _ = sandbox(tmp_path, enabled=False)
    result = run(registry.submit(req("create")))
    assert result.state == "FAILED" and runner.calls == []


def test_runsc_cleanup_denied_for_non_manager_owned(tmp_path):
    registry, _, runner, _, _ = sandbox(tmp_path)
    result = run(registry.submit(req("cleanup")))
    assert result.state == "FAILED" and runner.calls == []


def test_unknown_action_container_and_fence_never_reach_runner(tmp_path):
    registry, _, runner, _, _ = sandbox(tmp_path)
    for index, invalid in enumerate([
        {"action": "exec", "container_id": "sentra-lab-demo",
         "lease_id": "lease-1", "fence": 9},
        {"action": "create", "container_id": "../other",
         "lease_id": "lease-1", "fence": 9},
        {"action": "create", "container_id": "sentra-lab-demo",
         "lease_id": "lease-1", "fence": 10},
    ]):
        r = OperationRequest(
            f"bad-{index}", "lab", "gvisor-machine", "gvisor-lab",
            "work", f"bad-{index}", invalid)
        outcome = run(registry.submit(r))
        assert outcome.state == "FAILED"
    assert runner.calls == []


def test_stale_lease_and_uncertain_error_prevent_replay(tmp_path):
    registry, _, runner, binding, declaration = sandbox(tmp_path)
    wrong = RunscLease("lease-1", 10, time.monotonic()+20)
    declaration.adapter.lease_reader = lambda _id: wrong
    stale = run(registry.submit(req("create")))
    assert stale.state == "FAILED" and runner.calls == []

    # A failed fixture call may have applied an effect: do NOT retry.
    class Failing(SubprocessRunscFixture):
        def invoke(self, binary, argv, timeout):
            self.calls.append((str(binary), tuple(argv)))
            raise TimeoutError("fixture runsc create outcome unknown")
    failing = Failing(tmp_path)
    declaration.adapter.lease_reader = lambda _id: binding.lease
    declaration.adapter.runner = failing
    first = run(registry.submit(req("create", op="maybe-created")))
    again = run(registry.submit(req("create", op="second-attempt")))
    assert first.state == "UNCERTAIN" and again.state == "FAILED"
    assert first.error == "timeout_may_have_executed"
    assert len(failing.calls) == 1


def test_pinned_real_runner_never_called_on_unsupported_platform(tmp_path):
    _, _, _, binding, _ = sandbox(tmp_path)
    runner = PinnedRunscRunner(approved=False)
    with pytest.raises(PermissionError, match="runsc_real_linux_approval_required"):
        runner.invoke(binding.binary, ("create",), .3)


@pytest.mark.parametrize("bad_expiry", [True, float("nan"), float("inf"), -1.0])
def test_runsc_lease_rejects_boolean_nan_infinity_and_expired(bad_expiry):
    with pytest.raises(ValueError, match="invalid_runsc_lease"):
        RunscLease("lease-1", 9, bad_expiry)


def test_duplicate_oci_manifest_keys_deny(tmp_path):
    registry, _, runner, binding, _ = sandbox(tmp_path)
    path = binding.bundle / "config.json"
    original = path.read_text(encoding="utf8")
    # Ambiguous duplicate top-level config key must be denied, not silently
    # take the last value (which can differ between OCI parsers).
    path.write_text(original[:-1]+', "ociVersion":"1.0.2"}', encoding="utf8")
    result = run(registry.submit(req("create")))
    assert result.state == "FAILED" and runner.calls == []


def test_missing_rootfs_program_denied_before_runsc(tmp_path):
    registry, _, runner, binding, _ = sandbox(tmp_path)
    (binding.bundle / "rootfs" / "bin" / "true").unlink()
    result = run(registry.submit(req("create")))
    assert result.state == "FAILED"
    assert runner.calls == []
