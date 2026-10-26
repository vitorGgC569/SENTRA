"""Failures must remain visible to the host and retain owned references."""
import subprocess
import sys

import pytest

from sentra_executors.playwright_browser import PlaywrightBrowserBackend
from sentra_executors.rpa import ExecutorFailure, OwnedProcessHandle


class Resource:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def close(self):
        self.calls += 1
        if self.fail:
            raise OSError('fixture failure')

    def stop(self):
        self.close()


class Session:
    def __init__(self, fail=False):
        self.context = Resource(fail)

    def invalidate(self):
        pass


@pytest.mark.parametrize('failure', ['context', 'browser', 'process', 'driver'])
def test_shutdown_failure_preserves_references_and_never_retries(failure):
    backend = PlaywrightBrowserBackend()
    session = Session(failure == 'context')
    browser, driver, handle = Resource(failure == 'browser'), Resource(failure == 'driver'), Resource()
    backend._sessions['s'] = session
    backend._browser, backend._playwright, backend._browser_handle = browser, driver, handle
    backend._browser_process_exited = lambda: failure != 'process'
    try:
        with pytest.raises(ExecutorFailure, match='browser_shutdown_unconfirmed') as error:
            backend.shutdown()
        assert error.value.uncertain
        assert backend._sessions['s'] is session
        assert backend._browser is browser and backend._playwright is driver
        assert backend._browser_handle is handle and handle.calls == 0
        calls = session.context.calls, browser.calls, driver.calls
        with pytest.raises(ExecutorFailure, match='browser_shutdown_unconfirmed'):
            backend.shutdown()
        assert calls == (session.context.calls, browser.calls, driver.calls)
    finally:
        backend._actor.shutdown(wait=True)


def test_shutdown_releases_references_only_after_confirmed_exit():
    backend = PlaywrightBrowserBackend()
    session, browser, driver, handle = Session(), Resource(), Resource(), Resource()
    backend._sessions['s'] = session
    backend._browser, backend._playwright, backend._browser_handle = browser, driver, handle
    backend._browser_process_exited = lambda: True
    backend.shutdown()
    backend.shutdown()
    assert (session.context.calls, browser.calls, driver.calls, handle.calls) == (1, 1, 1, 1)
    assert backend._sessions == {} and backend._browser_handle is None


def test_browser_without_process_identity_cannot_confirm_exit():
    backend = PlaywrightBrowserBackend()
    backend._browser = Resource()
    try:
        with pytest.raises(ExecutorFailure, match='browser_shutdown_unconfirmed'):
            backend.shutdown()
        assert backend._browser is not None
    finally:
        backend._actor.shutdown(wait=True)


def test_shutdown_checks_real_retained_process_handle():
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    handle = OwnedProcessHandle(process.pid)
    backend = PlaywrightBrowserBackend()
    class Browser:
        def close(self):
            process.terminate()
    backend._browser = Browser()
    backend._browser_handle = handle
    try:
        backend.shutdown()
        assert process.wait(timeout=3) is not None
        assert handle._closed and backend._browser_handle is None
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
        handle.close()
        backend._actor.shutdown(wait=True)
