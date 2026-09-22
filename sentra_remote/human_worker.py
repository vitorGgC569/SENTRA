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
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class WorkerLease:
    def __init__(self, path: Path) -> None:
        self.path = path

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="ascii") as handle:
                    handle.write(str(os.getpid()))
                return True
            except FileExistsError:
                try:
                    pid = int(self.path.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    pid = 0
                if _pid_alive(pid):
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
