"""Cross-process singleton ownership for one OpenAI Secure MCP Tunnel ID."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Callable, Iterator


class TunnelSingleton:
    """Coordinate tunnel-client ownership across SENTRA launchers/state roots."""

    def __init__(
        self,
        tunnel_id: str,
        state_root: Path | str,
        *,
        process_path: Callable[[int], Path | None],
        clock: Callable[[], float] = time.time,
    ) -> None:
        value = str(tunnel_id or "").strip()
        if not value:
            raise ValueError("tunnel_id is required")
        self.tunnel_id = value
        self.state_root = Path(state_root).resolve()
        self.process_path = process_path
        self.clock = clock
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
        local = os.environ.get("LOCALAPPDATA", "").strip()
        if os.name == "nt" and local:
            root = Path(local).expanduser().resolve() / "SENTRA" / "runtime-locks"
        else:
            root = self.state_root / "runtime-locks"
        root.mkdir(parents=True, exist_ok=True)
        self.registry_path = root / f"tunnel-{digest}.json"
        self.lock_path = root / f"tunnel-{digest}.lock"

    @contextmanager
    def acquire(
        self,
        *,
        timeout_s: float = 5.0,
        stale_after_s: float = 30.0,
    ) -> Iterator[None]:
        # Keep the file/inode stable throughout startup. Age or malformed
        # contents never revoke ownership; stale_after_s is compatibility only.
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                def lock() -> None:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                def lock() -> None:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            while True:
                try:
                    lock()
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError("tunnel singleton lock is busy") from None
                    time.sleep(min(0.05, remaining))
            yield
        finally:
            # OS ownership also disappears automatically when the process dies.
            os.close(fd)

    def live(self) -> dict | None:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            pid = int(data.get("pid", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.registry_path.unlink(missing_ok=True)
            return None
        if pid <= 0:
            self.registry_path.unlink(missing_ok=True)
            return None
        actual = self.process_path(pid)
        expected = str(data.get("executable") or "").strip()
        if actual is None:
            self.registry_path.unlink(missing_ok=True)
            return None
        if expected and str(actual).casefold() != str(Path(expected).resolve()).casefold():
            self.registry_path.unlink(missing_ok=True)
            return None
        return data

    def write(self, pid: int, executable: Path, state_dir: Path) -> dict:
        payload = {
            "tunnel_id_hash": hashlib.sha256(
                self.tunnel_id.encode("utf-8")
            ).hexdigest(),
            "pid": int(pid),
            "executable": str(Path(executable).resolve()),
            "state_dir": str(Path(state_dir).resolve()),
            "updated_at": self.clock(),
        }
        temp = self.registry_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(self.registry_path)
        return payload

    def clear(self, *, expected_pid: int | None = None) -> None:
        if expected_pid is not None:
            live = self.live()
            if live is not None and int(live["pid"]) != int(expected_pid):
                return
        self.registry_path.unlink(missing_ok=True)
