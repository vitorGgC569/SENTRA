import ctypes
import json
import os
import subprocess
import sys
import time

import pytest
from sentra_canvas.process_lifetime import launch_independent, independent_flags


@pytest.mark.skipif(os.name != 'nt', reason='Windows job object lifetime')
def test_real_child_survives_callers_kill_on_close_job(tmp_path):
    # Other Windows/package jobs may remain. Test the actual lifetime property:
    # closing this caller's kill-on-close job must not terminate its child.
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_ = [('processTime', ctypes.c_longlong), ('jobTime', ctypes.c_longlong),
                    ('flags', wintypes.DWORD), ('minws', ctypes.c_size_t), ('maxws', ctypes.c_size_t),
                    ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                    ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', ctypes.c_ulonglong * 6), ('memory', ctypes.c_size_t * 4)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    info = Extended(); info.basic.flags = 0x2800  # BREAKAWAY_OK | KILL_ON_JOB_CLOSE
    assert kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    gate, ready, survived = (tmp_path / name for name in ('gate', 'ready', 'survived'))
    child_code = f"import time;from pathlib import Path;Path({str(ready)!r}).touch();time.sleep(2);Path({str(survived)!r}).touch()"
    parent_code = f'''import sys,time
from pathlib import Path
from sentra_canvas.process_lifetime import launch_independent
while not Path({str(gate)!r}).exists():time.sleep(.02)
launch_independent([sys.executable,'-c',{child_code!r}])
time.sleep(20)
'''
    parent = subprocess.Popen([sys.executable, '-c', parent_code], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert kernel.AssignProcessToJobObject(job, int(parent._handle)), ctypes.get_last_error()
        gate.touch()
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline: time.sleep(.05)
        assert ready.exists(), 'independent child did not start'
        kernel.CloseHandle(job); job = None
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while not survived.exists() and time.monotonic() < deadline: time.sleep(.05)
        assert survived.exists(), 'closing caller job terminated independent child'
    finally:
        if job: kernel.CloseHandle(job)
        if parent.poll() is None: parent.terminate(); parent.wait(timeout=5)
    assert independent_flags() & subprocess.CREATE_BREAKAWAY_FROM_JOB


def test_denied_breakaway_never_retries_in_callers_job(monkeypatch):
    calls = []
    def denied(*args, **kwargs):
        calls.append(kwargs)
        error = OSError('denied'); error.winerror = 5
        raise error
    monkeypatch.setattr(subprocess, 'Popen', denied)
    if os.name == 'nt':
        with pytest.raises(RuntimeError, match='Windows shortcut'):
            launch_independent(['owned-desktop'])
    else:
        with pytest.raises(OSError):
            launch_independent(['owned-desktop'])
    assert len(calls) == 1


@pytest.mark.skipif(os.name != 'nt', reason='Windows interactive task-service launch')
def test_windows_owned_entry_uses_its_independent_interactive_lifetime(monkeypatch):
    monkeypatch.setenv('SENTRA_DESKTOP_LAUNCH_CONTEXT', 'windows-interactive')
    assert independent_flags() == subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def test_frozen_owner_extracts_independent_resources(monkeypatch):
    calls = []
    sentinel = object()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(subprocess, 'Popen', lambda command, **options: calls.append(options) or sentinel)
    original = {'KEEP': 'application-setting'}
    assert launch_independent(['owned-canvas.exe', '--broker'], env=original) is sentinel
    assert calls[0]['env'] == {'KEEP': 'application-setting', 'PYINSTALLER_RESET_ENVIRONMENT': '1'}
    assert original == {'KEEP': 'application-setting'}
