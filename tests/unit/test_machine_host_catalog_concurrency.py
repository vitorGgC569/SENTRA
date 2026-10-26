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


def test_failed_partial_teardown_is_not_retried_without_proof(tmp_path):
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
        with pytest.raises(RuntimeError, match='outcome uncertain'):
            host.close()
        assert not host._closed and len(attempts) == 1
    finally:
        # Test fixture recovery after asserting the production failure state.
        host._teardown_progress[('factory', id(host._factories['machine']))] = 'done'
        while host._teardown_locks: host._teardown_locks.pop().release()
        host.close(); control.durable.close()


def test_cancelled_thread_work_keeps_host_owned_until_it_finishes(tmp_path):
    import asyncio
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    entered = threading.Event(); release = threading.Event()
    def work():
        entered.set(); assert release.wait(5)
    async def start():
        await asyncio.to_thread(work)
    try:
        with pytest.raises(TimeoutError):
            host._call(start(), timeout=.15)
        assert entered.is_set()
        with pytest.raises(RuntimeError, match='thread workers'):
            host.close(drain_timeout=.1)
        assert not host._closed and host._thread.is_alive()
        release.set()
        host.close(drain_timeout=2)
        assert host._closed and not host._thread.is_alive()
    finally:
        release.set(); host.close(); control.durable.close()


def test_timed_out_backend_shutdown_never_starts_again(tmp_path):
    from types import SimpleNamespace
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    entered = threading.Event(); release = threading.Event(); stopped = threading.Event(); calls = []
    def shutdown():
        calls.append('started'); entered.set(); release.wait(5); stopped.set()
    backend = SimpleNamespace(shutdown=shutdown)
    host._factories['machine'] = SimpleNamespace(
        _declarations={'one': SimpleNamespace(adapter=SimpleNamespace(backend=backend))})
    from sentra_runtime.effect_boundary import _ResourceLock, ResourceEffectBusy
    competitor = _ResourceLock(control.durable.root / 'effect-locks', 'machine')
    host._teardown_timeout = .15
    try:
        with pytest.raises(RuntimeError, match='shutdown still running'):
            host.close()
        assert entered.is_set()
        with pytest.raises(ResourceEffectBusy):
            competitor.acquire(0)
        with pytest.raises(RuntimeError, match='shutdown still running'):
            host.close()
        assert calls == ['started']
        release.set(); assert stopped.wait(2)
        host.close()
        assert calls == ['started'] and host._closed
        competitor.acquire(0)
        competitor.release()
    finally:
        release.set(); stopped.wait(2); competitor.release()
        host.close(); control.durable.close()


def test_completed_backend_not_repeated_after_later_failure(tmp_path):
    from types import SimpleNamespace
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    calls = []
    async def first(): calls.append('first')
    async def second():
        calls.append('second'); raise RuntimeError('failed')
    a = SimpleNamespace(shutdown=first, _declarations={})
    b = SimpleNamespace(shutdown=second, _declarations={})
    host._factories.update(first=a, second=b)
    try:
        with pytest.raises(RuntimeError, match='failed'):
            host.close()
        with pytest.raises(RuntimeError, match='outcome uncertain'):
            host.close()
        assert calls == ['first', 'second'] and not host._closed
    finally:
        host._teardown_progress[('factory', id(b))] = 'done'
        while host._teardown_locks: host._teardown_locks.pop().release()
        host.close(); control.durable.close()


def test_loop_still_stopping_keeps_resources_until_a_later_join(tmp_path, monkeypatch):
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    original_join = host._thread.join
    original_alive = host._thread.is_alive
    try:
        with monkeypatch.context() as context:
            context.setattr(host._thread, 'join', lambda timeout=None: None)
            context.setattr(host._thread, 'is_alive', lambda: True)
            with pytest.raises(RuntimeError, match='loop has not stopped'):
                host.close()
        assert not host._closed and host._loop_stopping and host._draining
        host.close()
        assert host._closed and not original_alive()
    finally:
        original_join(3); host.close(); control.durable.close()


def test_completed_backend_is_not_closed_twice_when_next_backend_fails(tmp_path):
    from types import SimpleNamespace
    from sentra_runtime.effect_boundary import _ResourceLock, ResourceEffectBusy
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    calls = []
    def first(): calls.append('first')
    def second():
        calls.append('second'); raise RuntimeError('backend failed')
    a = SimpleNamespace(shutdown=first); b = SimpleNamespace(shutdown=second)
    host._factories['machine'] = SimpleNamespace(_declarations={
        'first': SimpleNamespace(adapter=SimpleNamespace(backend=a)),
        'second': SimpleNamespace(adapter=SimpleNamespace(backend=b))})
    try:
        with pytest.raises(RuntimeError, match='backend failed'):
            host.close()
        with pytest.raises(RuntimeError, match='outcome uncertain'):
            host.close()
        assert calls == ['first', 'second']
        probe = _ResourceLock(control.durable.root / 'effect-locks', 'machine')
        with pytest.raises(ResourceEffectBusy):
            probe.acquire(0)
    finally:
        host._teardown_progress[('backend', id(b))] = 'done'
        while host._teardown_locks: host._teardown_locks.pop().release()
        host.close(); control.durable.close()


def test_failed_shutdown_retains_lock_while_internal_worker_is_uncertain(tmp_path):
    from types import SimpleNamespace
    from sentra_runtime.effect_boundary import _ResourceLock, ResourceEffectBusy
    control = ControlPlaneService.from_store(tmp_path / 'central'); host = MachineHost(control, owner='owner')
    release = threading.Event(); entered = threading.Event(); threads = []
    def worker():
        entered.set(); release.wait(5)
    def shutdown():
        thread = threading.Thread(target=worker); threads.append(thread); thread.start()
        assert entered.wait(2)
        raise RuntimeError('backend returned before internal worker stopped')
    backend = SimpleNamespace(shutdown=shutdown)
    host._factories['machine'] = SimpleNamespace(
        _declarations={'one': SimpleNamespace(adapter=SimpleNamespace(backend=backend))})
    competitor = _ResourceLock(control.durable.root / 'effect-locks', 'machine')
    try:
        with pytest.raises(RuntimeError, match='internal worker stopped'):
            host.close()
        assert threads[0].is_alive() and not host._closed
        with pytest.raises(ResourceEffectBusy):
            competitor.acquire(0)
        with pytest.raises(RuntimeError, match='physical locks retained'):
            host.close()
        release.set(); threads[0].join(2)
        # Even a finished thread alone does not prove the backend cleaned up.
        with pytest.raises(ResourceEffectBusy):
            competitor.acquire(0)
    finally:
        release.set()
        for thread in threads: thread.join(2)
        competitor.release()
        # This fixture controls and knows its synthetic backend has no work.
        host._teardown_progress[('backend', id(backend))] = 'done'
        while host._teardown_locks: host._teardown_locks.pop().release()
        host.close(); control.durable.close()
