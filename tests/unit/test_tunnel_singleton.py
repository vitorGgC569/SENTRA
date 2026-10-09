from __future__ import annotations

from pathlib import Path
import json
import multiprocessing
import os
import time

import pytest

from sentra_remote.tunnel_singleton import TunnelSingleton


def test_registry_is_shared_by_tunnel_id_across_state_roots(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr("sentra_remote.tunnel_singleton.os.name", "nt")
    executable = tmp_path / "tunnel-client.exe"
    executable.write_bytes(b"MZ")
    paths = {42: executable.resolve()}
    first = TunnelSingleton("tunnel_shared_12345", tmp_path / "state-a", process_path=paths.get)
    second = TunnelSingleton("tunnel_shared_12345", tmp_path / "state-b", process_path=paths.get)

    first.write(42, executable, tmp_path / "state-a")

    assert first.registry_path == second.registry_path
    assert second.live()["pid"] == 42


def test_registry_discards_dead_or_reused_pid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr("sentra_remote.tunnel_singleton.os.name", "nt")
    executable = tmp_path / "tunnel-client.exe"
    executable.write_bytes(b"MZ")
    singleton = TunnelSingleton("tunnel_shared_67890", tmp_path / "state", process_path=lambda _pid: None)
    singleton.write(99, executable, tmp_path / "state")

    assert singleton.live() is None
    assert not singleton.registry_path.exists()


def test_singleton_lock_fails_closed_when_held(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr("sentra_remote.tunnel_singleton.os.name", "nt")
    singleton = TunnelSingleton("tunnel_shared_lock", tmp_path / "state", process_path=lambda _pid: None)

    with singleton.acquire():
        with pytest.raises(RuntimeError, match="lock is busy"):
            with singleton.acquire(timeout_s=0.01):
                pass


def _hold_startup_lock(state_root, ready, release, payload):
    singleton = TunnelSingleton("tunnel_startup_test", state_root, process_path=lambda _: None,
                                clock=lambda: 100.0)
    singleton.lock_path.write_bytes(payload)
    with singleton.acquire():
        ready.set()
        release.wait(10)


@pytest.mark.parametrize("payload", [b"", b"unreadable", json.dumps({
    "pid": os.getpid(), "created_at": 1.0,
}).encode()])
def test_live_startup_owner_cannot_be_stolen_for_lock_contents_or_age(tmp_path, monkeypatch, payload):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    ctx = multiprocessing.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_startup_lock, args=(tmp_path, ready, release, payload))
    child.start()
    singleton = TunnelSingleton("tunnel_startup_test", tmp_path, process_path=lambda _: None,
                                clock=lambda: 100.0)
    try:
        assert ready.wait(5)
        before = singleton.lock_path.stat()
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="lock is busy"):
            with singleton.acquire(timeout_s=0.06, stale_after_s=30):
                pytest.fail("a second startup entered while the first was still alive")
        assert time.monotonic() - started < 0.5
        assert singleton.lock_path.stat().st_ino == before.st_ino
        assert child.is_alive()
    finally:
        release.set()
        child.join(5)
        if child.is_alive():
            child.terminate()
            child.join(5)
    assert child.exitcode == 0
    with singleton.acquire(timeout_s=0):
        pass
    assert singleton.lock_path.exists()


def test_process_crash_releases_os_lock_without_timestamp_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    ctx = multiprocessing.get_context("spawn")
    ready, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_startup_lock, args=(tmp_path, ready, release, b""))
    child.start()
    try:
        assert ready.wait(5)
    finally:
        child.terminate()
        child.join(5)
    assert not child.is_alive()
    singleton = TunnelSingleton("tunnel_startup_test", tmp_path, process_path=lambda _: None)
    with singleton.acquire(timeout_s=0):
        pass


def test_context_exception_releases_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    singleton = TunnelSingleton("tunnel_exception_test", tmp_path, process_path=lambda _: None)
    with pytest.raises(ValueError):
        with singleton.acquire():
            raise ValueError("synthetic startup failure")
    with singleton.acquire(timeout_s=0):
        pass
