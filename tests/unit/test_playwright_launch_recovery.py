"""An incomplete browser launch must retain ownership and cannot be reused."""
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

from sentra_executors import playwright_browser as module
from sentra_executors.rpa import ExecutorFailure


@pytest.mark.parametrize('failure', ['attach', 'identity', 'handle', 'launch', 'driver_start'])
def test_incomplete_launch_retains_references_and_fences_reuse(monkeypatch, failure):
    calls = []
    class Root:
        def on(self, *_): pass
        def send(self, method, params=None):
            if method == 'SystemInfo.getProcessInfo':
                return {'processInfo': [] if failure == 'identity' else [{'type': 'browser', 'id': 42}]}
            if method == 'Target.setAutoAttach' and failure == 'attach':
                raise RuntimeError('Only flatten protocol is supported')
    class Browser:
        def new_browser_cdp_session(self): return root
        def is_connected(self): return True
        def close(self):
            calls.append('close'); raise OSError('close unconfirmed')
    class Chromium:
        executable_path = __file__
        def launch(self, **kwargs):
            calls.append('launch')
            if failure == 'launch': raise OSError('launch failed after possible creation')
            return browser
    class Driver:
        chromium = Chromium()
        def stop(self): calls.append('stop')
    root = Root(); browser = Browser(); driver = Driver()
    fake = ModuleType('playwright.sync_api')
    def start():
        if failure == 'driver_start': raise OSError('driver startup failed')
        return driver
    fake.sync_playwright = lambda: SimpleNamespace(start=start)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', fake)
    monkeypatch.setattr(module, 'dependency', lambda *_: None)
    monkeypatch.setattr(module, 'effect_checkpoint', lambda: None)
    def owned(pid):
        if failure == 'handle': raise OSError('handle unavailable')
        return SimpleNamespace(pid=pid, _closed=False, close=lambda: calls.append('handle close'))
    monkeypatch.setattr(module, 'OwnedProcessHandle', owned)
    backend = module.PlaywrightBrowserBackend()
    binding = SimpleNamespace(headless=True)
    try:
        with pytest.raises(Exception):
            backend._launch(binding, time.monotonic() + 10)
        assert backend._launch_state == 'failed'
        assert backend._playwright is (None if failure == 'driver_start' else driver)
        assert backend._browser is (None if failure in {'launch', 'driver_start'} else browser)
        assert backend._browser_handle is not None if failure == 'attach' else backend._browser_handle is None
        with pytest.raises(ExecutorFailure, match='browser_launch_unconfirmed_restart_required'):
            backend._launch(binding, time.monotonic() + 10)
        assert calls == ([] if failure == 'driver_start' else ['launch'])
        with pytest.raises(ExecutorFailure, match='browser_shutdown_unconfirmed'):
            backend.shutdown()
        assert backend._playwright is (None if failure == 'driver_start' else driver)
        assert 'stop' not in calls and 'handle close' not in calls
    finally:
        backend._actor.shutdown(wait=True)
