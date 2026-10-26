"""The retained Windows job must be empty before its handles are released."""
import os
import subprocess
import sys

import pytest

from sentra_executors.remote_rustdesk import RustDeskNativeBackend, _PopenOwnedHandle
from sentra_executors.rpa import ExecutorFailure, OwnedProcessHandle, _WindowsJob


class Process:
    returncode = None

    def wait(self, timeout):
        self.returncode = 0
        return 0


class Handle:
    closed = False

    def terminate(self):
        pass

    def close(self):
        self.closed = True


class Job:
    closed = False

    def __init__(self, failure):
        self.failure = failure

    def terminate(self):
        if self.failure == 'terminate':
            raise OSError('termination failed')

    def active_processes(self):
        if self.failure == 'query':
            raise OSError('query failed')
        return 1 if self.failure == 'active' else 0

    def close(self):
        self.closed = True


@pytest.mark.parametrize('failure', ['terminate', 'query', 'active'])
def test_uncertain_job_keeps_both_handles_and_session(monkeypatch, failure):
    import sentra_executors.remote_rustdesk as module
    # Advance the clock deterministically without waiting three seconds.
    clock = iter([0, 0, 0, 4, 4, 4])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(clock, 4))
    backend = RustDeskNativeBackend(None)
    job, handle = Job(failure), Handle()
    item = (Process(), handle, job, None)
    backend.running['session'] = item
    with pytest.raises(ExecutorFailure, match='stop_unconfirmed') as error:
        backend.shutdown()
    assert error.value.uncertain
    assert backend.running['session'] is item
    assert not job.closed and not handle.closed


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Objects required')
def test_real_windows_job_reaps_child_before_closing():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    script = ("import subprocess,sys,time; "
              "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
              "print(p.pid,flush=True); time.sleep(60)")
    job = _WindowsJob()
    process = None
    child_handle = None
    handle = None
    try:
        process = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, text=True, creationflags=0x08000004)
        handle = OwnedProcessHandle(process.pid)
        job.assign_suspended_pid(process.pid)
        child_pid = int(process.stdout.readline())
        child_handle = kernel.OpenProcess(0x00100000, False, child_pid)  # SYNCHRONIZE
        assert child_handle and job.active_processes() >= 2
        counts = []
        close = job.close
        def checked_close():
            counts.append(job.active_processes())
            close()
        job.close = checked_close
        backend = RustDeskNativeBackend(None)
        backend.running['session'] = (process, handle, job, None)
        backend.shutdown()
        assert counts == [0] and process.returncode is not None
        assert kernel.WaitForSingleObject(child_handle, 0) == 0
        assert not backend.running
    finally:
        if job.handle:
            job.terminate(); job.close()
        if process and process.poll() is None:
            process.kill(); process.wait(timeout=5)
        if handle: handle.close()
        if child_handle: kernel.CloseHandle(child_handle)
        if process:
            process.stdin.close(); process.stdout.close()


@pytest.mark.skipif(os.name != 'nt', reason='Windows suspended processes required')
def test_failed_assignment_stops_suspended_process_before_code_runs(tmp_path):
    marker = tmp_path / 'ran'
    script = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ran')"
    job = _WindowsJob()
    process = subprocess.Popen([sys.executable, '-c', script, str(marker)],
                               creationflags=0x08000004)
    backend = RustDeskNativeBackend(None)
    backend.running['session'] = (process, _PopenOwnedHandle(process), job, None)
    try:
        # An assignment failure leaves the process suspended and outside the Job.
        # Teardown must still terminate it using its retained Popen handle.
        backend.shutdown()
        assert process.returncode is not None and not marker.exists()
        assert not backend.running and not job.handle
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
        if job.handle:
            job.close()
