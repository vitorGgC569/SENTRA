"""GATE-4 deterministic ACP launch diagnostics, overload and lifecycle checks.

No external agent/daemon: subprocesses execute ONLY a test-local Python fixture.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys

import pytest

from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision
from sentra_interop import ACPLaunchError, ACPStdioTransport, InteropGate

SIMPLE_AGENT = (
    "import json,sys\n"
    "for line in sys.stdin:\n"
    " m=json.loads(line)\n"
    " if m.get('method')=='initialize': val={'protocolVersion':1}\n"
    " elif m.get('method')=='session/new': val={'sessionId':'fixture'}\n"
    " else: val={'stopReason':'end_turn'}\n"
    " if 'id' in m: print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':val}),flush=True)\n"
)


def make_request(idx, tmp_path, extra_args=()):
    args = ("-u", "-c", SIMPLE_AGENT, *extra_args)
    request = OperationRequest(
        "spawn-g4-" + str(idx), "user-g4", "machine-g4", "acp:launch",
        "test-work", "key-g4-" + str(idx),
        {"executable": sys.executable, "args": list(args), "cwd": str(tmp_path)},
    )
    return args, request


def make_gate(checker):
    machine = Machine("machine-g4", "agent", "user-g4",
                      (Capability("acp:launch", "launch"),))
    return InteropGate(machine, checker)


def allow(request):
    return PolicyDecision(True, "pinned test executable", {
        "executable_paths": [sys.executable],
        "cwd_roots": [request.arguments["cwd"]],
        "argv_sha256": hashlib.sha256(json.dumps(
            request.arguments["args"], ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")).hexdigest(),
    })


def run(task):
    return asyncio.run(task)


def test_policy_denial_has_typed_code_and_no_spawn(tmp_path, monkeypatch):
    called = 0
    async def prohibit(*args, **kwargs):
        nonlocal called
        called += 1
        raise AssertionError("should not spawn")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", prohibit)
    async def case():
        args, request = make_request("no-grant", tmp_path)
        with pytest.raises(ACPLaunchError) as caught:
            await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                           gate=make_gate(None), request=request)
        assert (caught.value.code, caught.value.state) == ("POLICY_DENIED", "FAILED")
        assert called == 0
    run(case())


def test_spawn_os_error_is_typed_and_does_not_leak_path(tmp_path, monkeypatch):
    called = 0
    async def os_failure(*args, **kwargs):
        nonlocal called
        called += 1
        raise OSError("C:\\Users\\confidential\\token.txt")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", os_failure)
    async def case():
        args, request = make_request("os-failure", tmp_path)
        gateway = make_gate(allow)
        with pytest.raises(ACPLaunchError) as caught:
            await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                           gate=gateway, request=request)
        assert (caught.value.code, caught.value.state) == ("SPAWN_OS_ERROR", "UNCERTAIN")
        assert "confidential" not in str(caught.value)
        assert (await gateway.journal.get(request.operation_id)).state == "UNCERTAIN"
        assert called == 1
        with pytest.raises(ACPLaunchError) as replay:
            await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                           gate=gateway, request=request)
        assert replay.value.code == "DUPLICATE_OR_CONFLICT"
        assert called == 1
    run(case())


def test_spawn_timeout_is_typed_and_never_starts_child(tmp_path, monkeypatch):
    started = 0
    cancelled = asyncio.Event() if False else None  # initialized inside loop
    original = asyncio.create_subprocess_exec
    async def case():
        nonlocal started
        cancellation = asyncio.Event()
        async def delayed(*args, **kwargs):
            nonlocal started
            await asyncio.sleep(0.12)
            started += 1
            return await original(*args, **kwargs)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
        args, request = make_request("timeout", tmp_path)
        with pytest.raises(ACPLaunchError) as caught:
            await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                           gate=make_gate(allow), request=request,
                                           spawn_timeout=0.008)
        assert (caught.value.code, caught.value.state) == ("SPAWN_TIMEOUT", "UNCERTAIN")
        await asyncio.sleep(0.14)
        assert started == 0  # cancelled before ever allocating a subprocess
    run(case())


def test_spawn_cancellation_is_journalled_uncertain_no_orphan(tmp_path, monkeypatch):
    original = asyncio.create_subprocess_exec
    async def case():
        started = asyncio.Event()
        progressed = 0
        async def delayed(*args, **kwargs):
            nonlocal progressed
            started.set()
            await asyncio.sleep(5)
            progressed += 1
            return await original(*args, **kwargs)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
        gateway = make_gate(allow)
        args, request = make_request("cancelled", tmp_path)
        pending = asyncio.create_task(ACPStdioTransport.launch(
            sys.executable, args, cwd=str(tmp_path), gate=gateway, request=request))
        await asyncio.wait_for(started.wait(), 2)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert progressed == 0
        result = await gateway.journal.get(request.operation_id)
        assert result is not None and result.state == "UNCERTAIN"
    run(case())


def test_post_spawn_policy_revocation_closes_child_before_raising(tmp_path, monkeypatch):
    original = asyncio.create_subprocess_exec
    child = None
    async def capture(*args, **kwargs):
        nonlocal child
        child = await original(*args, **kwargs)
        return child
    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    checks = 0
    def flip(request):
        nonlocal checks
        checks += 1
        return allow(request) if checks == 1 else PolicyDecision(False, "revoked")
    async def case():
        args, request = make_request("revoke", tmp_path)
        gateway = make_gate(flip)
        with pytest.raises(ACPLaunchError) as caught:
            await ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                           gate=gateway, request=request)
        assert (caught.value.code, caught.value.state) == ("POST_POLICY_DENIED", "UNCERTAIN")
        assert child is not None
        assert child.returncode is not None
        assert (await gateway.journal.get(request.operation_id)).state == "UNCERTAIN"
        assert checks == 2
    run(case())


def test_concurrent_spawn_under_delay_all_unique_and_reaped(tmp_path, monkeypatch):
    original = asyncio.create_subprocess_exec
    created = []
    envs = []
    async def delayed(*args, **kwargs):
        # Delay is deterministic and shared by all contenders.
        await asyncio.sleep(0.035)
        envs.append(kwargs.get("env"))
        process = await original(*args, **kwargs)
        created.append(process)
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    async def case():
        gate = make_gate(allow)
        tasks = []
        for idx in range(8):
            args, request = make_request(idx, tmp_path)
            tasks.append(ACPStdioTransport.launch(
                sys.executable, args, cwd=str(tmp_path), gate=gate, request=request))
        transports = []
        try:
            transports = await asyncio.gather(*tasks)
            assert len({t.process.pid for t in transports}) == len(transports)
            assert len(created) == 8
            assert envs == [{}] * 8
            results = await asyncio.gather(*(
                transport.request("initialize", {"protocolVersion":1}, timeout=3)
                for transport in transports
            ))
            assert all(result["protocolVersion"] == 1 for result in results)
        finally:
            await asyncio.gather(*(t.close() for t in transports))
            # Fail-safe in case a spawned process escaped the result gather.
            for proc in created:
                if proc.returncode is None:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), 3)
        assert all(proc.returncode is not None for proc in created)
    run(case())


def test_concurrent_same_operation_admits_only_one_child(tmp_path, monkeypatch):
    original = asyncio.create_subprocess_exec
    created = []
    async def delayed(*args, **kwargs):
        await asyncio.sleep(0.02)
        process = await original(*args, **kwargs)
        created.append(process)
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    async def case():
        gate = make_gate(allow)
        args, request = make_request("shared", tmp_path)
        results = await asyncio.gather(*(
            ACPStdioTransport.launch(sys.executable, args, cwd=str(tmp_path),
                                     gate=gate, request=request)
            for _ in range(8)
        ), return_exceptions=True)
        transports = [value for value in results if isinstance(value, ACPStdioTransport)]
        rejected = [value for value in results if isinstance(value, ACPLaunchError)]
        try:
            assert len(transports) == 1
            assert len(rejected) == 7
            assert all(err.code == "DUPLICATE_OR_CONFLICT" for err in rejected)
            assert len(created) == 1
        finally:
            await asyncio.gather(*(t.close() for t in transports))
        assert all(proc.returncode is not None for proc in created)
    run(case())


def test_launch_bad_env_and_pinning_are_independent(tmp_path):
    async def case():
        args, request = make_request("env", tmp_path)
        with pytest.raises(ACPLaunchError) as caught:
            await ACPStdioTransport.launch(
                sys.executable, args, cwd=str(tmp_path),
                gate=make_gate(allow), request=request, env={"SECRET":"never-inherit"})
        assert caught.value.code == "ENV_DENIED"
        def wrong_hash(req):
            decision = allow(req)
            return PolicyDecision(True, "wrong hash",
                                  {**decision.constraints, "argv_sha256":"0" * 64})
        with pytest.raises(ACPLaunchError) as second:
            await ACPStdioTransport.launch(
                sys.executable, args, cwd=str(tmp_path), gate=make_gate(wrong_hash), request=request)
        assert second.value.code == "POLICY_DENIED"
    run(case())



def test_policy_timeout_before_spawn_is_deny_by_default(tmp_path, monkeypatch):
    async def slow_policy(_):
        await asyncio.sleep(1)
        return PolicyDecision(True, "too late")
    starts = 0
    async def forbidden_spawn(*args, **kwargs):
        nonlocal starts
        starts += 1
        raise AssertionError("no spawn allowed")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_spawn)
    async def case():
        args, request = make_request("policy-timeout", tmp_path)
        with pytest.raises(ACPLaunchError) as result:
            await ACPStdioTransport.launch(
                sys.executable, args, cwd=str(tmp_path),
                gate=make_gate(slow_policy), request=request, spawn_timeout=0.01)
        assert result.value.code == "POLICY_TIMEOUT"
        assert result.value.state == "FAILED"
        assert starts == 0
    run(case())


def test_post_policy_timeout_reaps_real_child(tmp_path, monkeypatch):
    original = asyncio.create_subprocess_exec
    child = None
    checks = 0
    async def capture(*args, **kwargs):
        nonlocal child
        child = await original(*args, **kwargs)
        return child
    async def blocking_policy(request):
        nonlocal checks
        checks += 1
        if checks == 1:
            return allow(request)
        await asyncio.sleep(1)
        return allow(request)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    async def case():
        args, request = make_request("post-policy", tmp_path)
        gateway = make_gate(blocking_policy)
        with pytest.raises(ACPLaunchError) as result:
            await ACPStdioTransport.launch(
                sys.executable, args, cwd=str(tmp_path),
                gate=gateway, request=request, spawn_timeout=0.09)
        assert result.value.code == "POST_POLICY_TIMEOUT"
        assert result.value.state == "UNCERTAIN"
        assert child is not None and child.returncode is not None
        assert (await gateway.journal.get(request.operation_id)).state == "UNCERTAIN"
        assert checks == 2
    run(case())


def test_cancel_after_subprocess_exists_reaps_child(tmp_path, monkeypatch):
    original = asyncio.create_subprocess_exec
    created = None
    post_policy_entered = None
    async def capture(*args, **kwargs):
        nonlocal created
        created = await original(*args, **kwargs)
        return created
    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    async def case():
        entered = asyncio.Event()
        async def policy(request):
            if not entered.is_set():
                entered.set()
                return allow(request)
            # Separate signal ensures cancellation during policy re-check
            # *after* the child was actually created.
            while True:
                await asyncio.sleep(0.01)
        gate = make_gate(policy)
        args, request = make_request("after-spawn-cancel", tmp_path)
        launch = asyncio.create_task(ACPStdioTransport.launch(
            sys.executable, args, cwd=str(tmp_path), gate=gate, request=request,
            spawn_timeout=5))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            while created is None:
                await asyncio.sleep(0.01)
            launch.cancel()
            with pytest.raises(asyncio.CancelledError):
                await launch
            assert created.returncode is not None
            assert (await gate.journal.get(request.operation_id)).state == "UNCERTAIN"
        finally:
            if created is not None and created.returncode is None:
                created.terminate()
                await created.wait()
    run(case())
