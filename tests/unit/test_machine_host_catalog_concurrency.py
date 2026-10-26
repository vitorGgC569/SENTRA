"""Read-only host scheduling regression; admission and effects are unchanged."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import pytest
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.machine_host import MachineHost


def test_slow_task_catalog_does_not_block_the_host_loop(tmp_path,monkeypatch):
    control=ControlPlaneService.from_store(tmp_path/'central');host=MachineHost(control,owner='owner')
    entered=threading.Event();release=threading.Event()
    def slow_read(*args,**kwargs):
        entered.set();assert release.wait(15);return {'items':[]}
    monkeypatch.setattr(control,'list_work_items',slow_read)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending=pool.submit(host.task_catalog,workspace_id='workspace')
            try:
                assert entered.wait(5)
                # Inventory must finish while the catalog read is still blocked.
                assert pool.submit(host.inventory,'workspace').result(timeout=3)==[]
                assert not pending.done()
                with pytest.raises(RuntimeError,match='catalog readers'):host.close()
                assert host.inventory('workspace')==[]
            finally:release.set()
            assert pending.result(timeout=5)==[]
    finally:release.set();host.close();control.durable.close()


def test_sync_call_from_host_loop_is_refused_without_waiting_for_itself(tmp_path):
    control=ControlPlaneService.from_store(tmp_path/'central');host=MachineHost(control,owner='owner')
    async def nested():return host.inventory('workspace')
    try:
        with pytest.raises(RuntimeError,match='own event loop'):host._call(nested(),timeout=3)
    finally:host.close();control.durable.close()


def test_closed_host_releases_its_async_loop_and_default_worker(tmp_path):
    import asyncio
    control=ControlPlaneService.from_store(tmp_path/'central');host=MachineHost(control,owner='owner')
    async def identify_worker():
        return await asyncio.to_thread(threading.current_thread)
    worker=host._call(identify_worker())
    try:
        assert worker.is_alive()
        host.close()
        assert not host._thread.is_alive()
        assert not worker.is_alive()
        assert host._loop.is_closed()
    finally:host.close();control.durable.close()


def test_executor_cleanup_never_releases_an_owned_physical_boundary(tmp_path):
    from types import SimpleNamespace
    from sentra_runtime.effect_boundary import _ResourceLock
    control=ControlPlaneService.from_store(tmp_path/'central');host=MachineHost(control,owner='owner')
    host._factories['busy-machine']=SimpleNamespace(_declarations={})
    boundary=_ResourceLock(control.durable.root/'effect-locks','busy-machine')
    boundary.acquire(1)
    try:
        with pytest.raises(RuntimeError,match='physical workers'):
            host.close()
        assert host._thread.is_alive() and not host._loop.is_closed()
        assert host.inventory('unknown')==[]
    finally:
        boundary.release();host.close();control.durable.close()
    assert not host._thread.is_alive() and host._loop.is_closed()


def test_bounded_close_drains_catalog_read_without_cancelling_it(tmp_path, monkeypatch):
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    entered = threading.Event(); release = threading.Event()
    def slow_read(*args, **kwargs):
        entered.set(); assert release.wait(5); return {'items': []}
    monkeypatch.setattr(control, 'list_work_items', slow_read)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(host.task_catalog, workspace_id='workspace')
            assert entered.wait(5)
            timer = threading.Timer(.15, release.set); timer.start()
            try:
                host.close(drain_timeout=2)
                assert pending.result(timeout=2) == []
                assert host._closed and not host._thread.is_alive()
            finally:
                release.set(); timer.join()
    finally:
        release.set(); host.close(); control.durable.close()


def test_bounded_close_retains_store_and_host_until_reader_finishes(tmp_path, monkeypatch):
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    entered = threading.Event(); release = threading.Event()
    def slow_read(*args, **kwargs):
        entered.set(); assert release.wait(5); return {'items': []}
    monkeypatch.setattr(control, 'list_work_items', slow_read)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(host.task_catalog, workspace_id='workspace')
            assert entered.wait(5)
            with pytest.raises(RuntimeError, match='catalog readers'):
                host.close(drain_timeout=.1)
            assert not host._closed and host._thread.is_alive()
            assert control.durable.db.execute('SELECT 1').fetchone()[0] == 1
            release.set(); assert pending.result(timeout=2) == []
            host.close(drain_timeout=1)
            assert host._closed
    finally:
        release.set(); host.close(); control.durable.close()


def test_bounded_close_waits_for_physical_owner_without_forcing_it(tmp_path):
    from types import SimpleNamespace
    from sentra_runtime.effect_boundary import _ResourceLock
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    host._factories['busy-machine'] = SimpleNamespace(_declarations={})
    boundary = _ResourceLock(control.durable.root / 'effect-locks', 'busy-machine')
    boundary.acquire(1)
    timer = threading.Timer(.15, boundary.release); timer.start()
    try:
        host.close(drain_timeout=2)
        assert host._closed and not host._thread.is_alive()
    finally:
        timer.join(); boundary.release(); host.close(); control.durable.close()


def test_drain_rejects_new_calls_and_reopens_admission_after_timeout(tmp_path, monkeypatch):
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    entered = threading.Event(); release = threading.Event(); reads = []
    def slow_read(*args, **kwargs):
        reads.append('started'); entered.set(); assert release.wait(5); return {'items': []}
    monkeypatch.setattr(control, 'list_work_items', slow_read)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(host.task_catalog, workspace_id='workspace')
            assert entered.wait(5)
            closing = pool.submit(host.close, drain_timeout=.5)
            deadline = time.monotonic() + 2
            while not host._draining and time.monotonic() < deadline:
                time.sleep(.005)
            assert host._draining
            with pytest.raises(RuntimeError, match='draining'):
                host.task_catalog(workspace_id='workspace')
            with pytest.raises(RuntimeError, match='draining'):
                host.inventory('workspace')
            with pytest.raises(RuntimeError, match='catalog readers'):
                closing.result(timeout=2)
            assert reads == ['started']
            assert host.inventory('workspace') == []
            release.set(); assert pending.result(timeout=2) == []
            host.close(drain_timeout=1)
            assert host._closed
    finally:
        release.set(); host.close(); control.durable.close()


def test_drain_waits_for_already_admitted_host_call(tmp_path):
    import asyncio
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    entered = threading.Event(); release = threading.Event()
    async def inflight():
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.01)
        return 'complete'
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(host._call, inflight())
            assert entered.wait(5)
            closing = pool.submit(host.close, drain_timeout=2)
            deadline = time.monotonic() + 2
            while not host._draining and time.monotonic() < deadline:
                time.sleep(.005)
            assert host._draining and not closing.done()
            release.set()
            assert pending.result(timeout=2) == 'complete'
            closing.result(timeout=2)
            assert host._closed
    finally:
        release.set(); host.close(); control.durable.close()


def test_failed_partial_teardown_keeps_admission_fenced_until_retry(tmp_path):
    from types import SimpleNamespace
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    attempts = []
    async def shutdown():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError('backend cleanup interrupted')
    host._factories['machine'] = SimpleNamespace(_declarations={}, shutdown=shutdown)
    try:
        with pytest.raises(RuntimeError, match='backend cleanup interrupted'):
            host.close()
        with pytest.raises(RuntimeError, match='draining'):
            host.inventory('workspace')
        host.close()
        assert host._closed and len(attempts) == 2
    finally:
        host.close(); control.durable.close()
