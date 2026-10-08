from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def exclusive_file_lock(path: str | Path) -> Iterator[None]:
    """Cross-process one-byte advisory lock.

    The file is only a rendezvous point; ownership is held by the OS lock and
    is released automatically if the process dies.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = target.open("a+b")
    try:
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if __import__("os").name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl = __import__("fcntl")
            getattr(fcntl, "flock")(handle.fileno(), getattr(fcntl, "LOCK_EX"))
        try:
            yield
        finally:
            handle.seek(0)
            if __import__("os").name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl = __import__("fcntl")
                getattr(fcntl, "flock")(handle.fileno(), getattr(fcntl, "LOCK_UN"))
    finally:
        handle.close()
