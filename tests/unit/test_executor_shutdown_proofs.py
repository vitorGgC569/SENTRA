"""Backend shutdown retains unconfirmed resources; no real services are used."""
import subprocess

import pytest

from sentra_executors.daytona_sessions import DaytonaSessionBackend
from sentra_executors.remote_rustdesk import RustDeskNativeBackend
from sentra_executors.rpa import ExecutorFailure


class OwnedHandle:
    def __init__(self):
        self.closed = False
        self.terminations = 0

    def terminate(self):
        self.terminations += 1

    def close(self):
        self.closed = True


class Job:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    def terminate(self):
        pass

    def active_processes(self):
        return 0


class Process:
    def __init__(self, *, exits):
        self.exits = exits
        self.returncode = None

    def wait(self, timeout):
        if not self.exits:
            raise subprocess.TimeoutExpired('owned-fixture', timeout)
        self.returncode = 0
        return self.returncode


def test_rustdesk_timeout_keeps_exact_owned_process_and_handle():
    backend = RustDeskNativeBackend(None)
    process = Process(exits=False); handle = OwnedHandle(); job = Job()
    item = (process, handle, job, None); backend.running['session'] = item
    with pytest.raises(ExecutorFailure, match='rustdesk_owned_process_stop_unconfirmed') as error:
        backend.shutdown()
    assert error.value.uncertain is True
    assert backend.running['session'] is item
    assert process.returncode is None and not handle.closed


def test_rustdesk_removes_only_processes_with_confirmed_exit():
    backend = RustDeskNativeBackend(None)
    done = (Process(exits=True), OwnedHandle(), Job(), None)
    pending = (Process(exits=False), OwnedHandle(), Job(), None)
    backend.running.update(done=done, pending=pending)
    with pytest.raises(ExecutorFailure, match='stop_unconfirmed'):
        backend.shutdown()
    assert 'done' not in backend.running and done[1].closed
    assert backend.running['pending'] is pending and not pending[1].closed


@pytest.mark.parametrize('behavior', ['throws', 'still_connected', 'unknown', 'no_verifier'])
def test_daytona_keeps_unconfirmed_handle(behavior):
    class Handle:
        def disconnect(self):
            if behavior == 'throws':
                raise OSError('fixture close failure')

        def is_connected(self):
            return {'still_connected': True, 'unknown': None}.get(behavior, False)

    handle = Handle()
    if behavior == 'no_verifier':
        handle.is_connected = None
    backend = DaytonaSessionBackend(None); backend.handles['session'] = handle
    with pytest.raises(ExecutorFailure, match='daytona_disconnect_un') as error:
        backend.shutdown()
    assert error.value.uncertain is True
    assert backend.handles['session'] is handle


def test_daytona_drops_confirmed_handles_and_retains_failed_log_stream():
    class Handle:
        def disconnect(self): pass
        def is_connected(self): return False

    class Stream:
        def __exit__(self, *_): raise OSError('fixture stream close failure')

    stream = Stream(); backend = DaytonaSessionBackend(None)
    backend.handles['closed'] = Handle(); backend.log_streams['failed'] = (stream, 'fixture')
    with pytest.raises(ExecutorFailure, match='daytona_log_stream_close_unconfirmed') as error:
        backend.shutdown()
    assert error.value.uncertain is True
    assert backend.handles == {} and backend.log_streams['failed'][0] is stream


@pytest.mark.parametrize('kind', ['rustdesk', 'daytona'])
def test_machine_host_keeps_physical_lock_when_actual_backend_cannot_confirm_shutdown(tmp_path, kind):
    from types import SimpleNamespace
    from sentra_mcp.services.control_plane import ControlPlaneService
    from sentra_runtime.effect_boundary import _ResourceLock, ResourceEffectBusy
    from sentra_runtime.machine_host import MachineHost

    if kind == 'rustdesk':
        backend = RustDeskNativeBackend(None)
        backend.running['pending'] = (Process(exits=False), OwnedHandle(), Job(), None)
    else:
        class Handle:
            def disconnect(self): raise OSError('fixture failed')
            def is_connected(self): return True
        backend = DaytonaSessionBackend(None); backend.handles['pending'] = Handle()

    control = ControlPlaneService.from_store(tmp_path / 'central')
    host = MachineHost(control, owner='owner')
    host._factories['machine'] = SimpleNamespace(_declarations={
        'adapter': SimpleNamespace(adapter=SimpleNamespace(backend=backend)),
    })
    competitor = _ResourceLock(control.durable.root / 'effect-locks', 'machine')
    try:
        with pytest.raises(ExecutorFailure) as error:
            host.close()
        assert error.value.uncertain is True
        with pytest.raises(ResourceEffectBusy):
            competitor.acquire(0)
        assert not host._closed
        assert ('pending' in backend.running) if kind == 'rustdesk' else ('pending' in backend.handles)
    finally:
        competitor.release()
        # The fixture knows that its synthetic resources have no real I/O.
        host._teardown_progress[('backend', id(backend))] = 'done'
        while host._teardown_locks:
            host._teardown_locks.pop().release()
        host.close(); control.context.close(); control.durable.close()
