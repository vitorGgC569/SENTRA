"""Background SENTRA human-task worker. Executes the real persistent OMA queue."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .product import ProductPaths, ProductSettings, run_next_task
from .human_store import HumanStore


def _install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class WorkerLease:
    INVALID_LEASE_GRACE_S = 5.0

    def __init__(self, path: Path) -> None:
        self.path = path

    def is_held(self) -> bool:
        try:
            raw_pid = self.path.read_text(encoding="ascii").strip()
            pid = int(raw_pid)
        except (OSError, ValueError):
            try:
                age_s = max(0.0, time.time() - self.path.stat().st_mtime)
            except OSError:
                return False
            return age_s < self.INVALID_LEASE_GRACE_S
        return _pid_alive(pid)

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="ascii") as handle:
                    handle.write(str(os.getpid()))
                return True
            except FileExistsError:
                if self.is_held():
                    return False
                try:
                    self.path.unlink()
                except OSError:
                    return False
        return False

    def release(self) -> None:
        try:
            current = int(self.path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            current = 0
        if current == os.getpid():
            try:
                self.path.unlink()
            except OSError:
                pass


def run_worker(paths: ProductPaths, *, idle_exit_s: float = 0.0) -> int:
    lease = WorkerLease(paths.state_dir / "human-worker.pid")
    if not lease.acquire():
        return 0
    store = HumanStore(paths)
    idle_since = time.monotonic()
    stop_file = paths.state_dir / "human-worker.stop"
    try:
        while True:
            if stop_file.exists():
                try:
                    stop_file.unlink()
                except OSError:
                    pass
                return 0
            settings = ProductSettings.load(paths.settings)
            result = run_next_task(paths, settings)
            if result is not None:
                idle_since = time.monotonic()
                store.record_task_result(result)
                continue
            if idle_exit_s > 0 and time.monotonic() - idle_since >= idle_exit_s:
                return 0
            time.sleep(0.75)
    finally:
        lease.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentra-human-worker")
    parser.add_argument("--state-dir")
    parser.add_argument("--install-dir")
    parser.add_argument("--idle-exit-secs", type=float, default=0.0)
    args = parser.parse_args(argv)
    if args.state_dir:
        os.environ["SENTRA_STATE_DIR"] = str(Path(args.state_dir).expanduser().resolve())
    paths = ProductPaths.default(Path(args.install_dir).resolve() if args.install_dir else _install_dir())
    return run_worker(paths, idle_exit_s=max(0.0, args.idle_exit_secs))


if __name__ == "__main__":
    raise SystemExit(main())
