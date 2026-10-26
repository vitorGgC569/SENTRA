"""The shared retained handle must not request Job-assignment privileges."""
import os

import pytest

from sentra_executors.rpa import OwnedProcessHandle


@pytest.mark.skipif(os.name != 'nt', reason='Windows process access rights')
def test_owned_process_handle_requests_only_termination_sync_and_query(monkeypatch):
    import ctypes

    class Function:
        def __init__(self, action):
            self.action = action
        def __call__(self, *args):
            return self.action(*args)

    requests = []
    class Kernel:
        def __init__(self):
            def open_process(access, inherit, pid):
                requests.append((access, inherit, pid))
                # Model a process ACL that denies PROCESS_SET_QUOTA.
                return 0 if access & 0x0100 else 7
            self.OpenProcess = Function(open_process)
            self.TerminateProcess = Function(lambda *_: 1)
            self.CloseHandle = Function(lambda *_: 1)

    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: Kernel())
    handle = OwnedProcessHandle(123)
    handle.close()
    assert requests == [(0x0001 | 0x00100000 | 0x1000, False, 123)]
