"""Prepared publication retries never repeat producers, admission or provider calls."""
from pathlib import Path
from types import SimpleNamespace
import ctypes
import os

import pytest

from orchestrator import atomic_publication as publication
from orchestrator.budgets import HostResourceBudget
from orchestrator.conversation_pool import FixedConversationRouter
from orchestrator.rate_governor import HostResourceGovernor, ProviderRateGovernor
from orchestrator.swarm_cycle import PersistentSwarm


@pytest.fixture(params=['conversations', 'swarm-manifest', 'swarm-output', 'provider-rate', 'host-pressure', 'host-budget'])
def writer(request, tmp_path):
    target = tmp_path / 'snapshot.json'
    if request.param == 'conversations':
        instance = FixedConversationRouter(object(), 'publication-test', store_dir=tmp_path)
        target = instance._path
        write = instance._save
    elif request.param == 'swarm-manifest':
        write = lambda: PersistentSwarm._atomic_json(target, {'value': 'prepared'})
    elif request.param == 'swarm-output':
        instance = object.__new__(PersistentSwarm)
        instance.swarm_root = tmp_path
        target = instance._output_path('run', 1, 'phase', 'role')
        write = lambda: instance._save_output('run', 1, 'phase', 'role', 'prepared')
    elif request.param == 'provider-rate':
        write = ProviderRateGovernor(state_path=target)._save
    elif request.param == 'host-pressure':
        write = HostResourceGovernor(state_path=target)._save
    else:
        write = HostResourceBudget(total_mb=8192, state_path=target)._save
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('previous', encoding='utf-8')
    return write, target


def refusal(code):
    exc = PermissionError('publication refused')
    exc.winerror = code
    return exc


@pytest.mark.parametrize('code', [5, 32, 33])
@pytest.mark.parametrize('permanent', [False, True])
def test_actual_snapshot_wrappers_retry_only_same_fsynced_file(writer, monkeypatch, code, permanent):
    write, target = writer
    actual_replace, actual_fsync = os.replace, os.fsync
    attempts, synced, waits = [], [], []
    def fsync(fd):
        synced.append(fd)
        return actual_fsync(fd)
    def replace(source, destination):
        attempts.append((str(source), str(destination), Path(source).read_bytes()))
        if permanent or len(attempts) < 3:
            raise refusal(code)
        return actual_replace(source, destination)
    monkeypatch.setattr(os, 'fsync', fsync)
    monkeypatch.setattr(publication, 'os', SimpleNamespace(name='nt', replace=replace))
    monkeypatch.setattr(publication, 'time', SimpleNamespace(sleep=waits.append))
    if permanent:
        with pytest.raises(PermissionError):
            write()
        assert target.read_text() == 'previous'
        assert len(attempts) == 6
        assert sum(waits) == pytest.approx(.15)
    else:
        write()
        assert target.read_text() != 'previous'
        assert len(attempts) == 3
        assert waits == [.01, .02]
    assert len(synced) == 1  # No producer/write/fsync repeated on publication retry.
    assert len(set(attempts)) == 1  # Exact source, destination and bytes on every attempt.
    assert not Path(attempts[0][0]).exists()  # Caller cleanup preserved on success/failure.


@pytest.mark.parametrize('platform,error', [('posix', refusal(5)), ('nt', refusal(13)), ('nt', OSError('disk failure'))])
def test_other_errors_propagate_without_retry(writer, monkeypatch, platform, error):
    write, target = writer
    attempts = []
    def replace(source, destination):
        attempts.append(str(source))
        raise error
    def no_sleep(_):
        pytest.fail('non-sharing/permanent OS error must not sleep')
    monkeypatch.setattr(publication, 'os', SimpleNamespace(name=platform, replace=replace))
    monkeypatch.setattr(publication, 'time', SimpleNamespace(sleep=no_sleep))
    with pytest.raises(type(error)) as raised:
        write()
    assert raised.value is error
    assert len(attempts) == 1
    assert target.read_text() == 'previous'
    assert not Path(attempts[0]).exists()


@pytest.mark.skipif(os.name != 'nt', reason='native Windows delete sharing')
def test_native_windows_reader_denies_then_releases_same_publication(writer, monkeypatch):
    from ctypes import wintypes
    write, target = writer
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(target), 0x80000000, 1 | 2, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    waits = []
    def release(delay):
        nonlocal handle
        waits.append(delay)
        assert handle is not None
        assert kernel.CloseHandle(handle)
        handle = None
    monkeypatch.setattr(publication, 'time', SimpleNamespace(sleep=release))
    try:
        write()  # Actual os.replace; an actual Windows reader initially refuses it.
        assert waits == [.01]
        assert target.read_text() != 'previous'
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)

@pytest.mark.asyncio
@pytest.mark.parametrize('when', ['intent', 'result'])
@pytest.mark.parametrize('permanent', [False, True])
async def test_router_publication_refusal_never_replays_provider(tmp_path, monkeypatch, when, permanent):
    from orchestrator.providers.base import AgentRequest, AgentResponse
    calls = []
    class Provider:
        async def execute(self, request, preferred_provider=None):
            calls.append(request)
            return AgentResponse(content='completed once', success=True, model='fixture', metadata={})
    router = FixedConversationRouter(Provider(), 'once', store_dir=tmp_path)
    actual_replace = os.replace
    refusals = []
    def replace(source, destination):
        at_result = bool(calls)
        if at_result == (when == 'result'):
            refusals.append((str(source), str(destination)))
            if permanent or len(refusals) < 3:
                raise refusal(5)
        return actual_replace(source, destination)
    monkeypatch.setattr(publication, 'os', SimpleNamespace(name='nt', replace=replace))
    monkeypatch.setattr(publication, 'time', SimpleNamespace(sleep=lambda _: None))
    request = AgentRequest(system_prompt='system', user_prompt='task', role='executor', timeout=10)
    response = await router.execute(request)
    assert len(calls) == (0 if permanent and when == 'intent' else 1)
    assert len(refusals) == (6 if permanent else 3)
    assert len(set(refusals)) == 1
    if permanent:
        assert not response.success
        assert response.metadata['retry_safe'] is False
        assert response.metadata['delivery_state'] == ('UNCERTAIN' if when == 'result' else 'BLOCKED')
        again = await router.execute(request)
        assert not again.success
        assert len(calls) == (1 if when == 'result' else 0)
    else:
        assert response.success
