"""Read-only host scheduling regression; admission and effects are unchanged."""
from concurrent.futures import ThreadPoolExecutor
import threading
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
