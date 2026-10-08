"""OS-held serialization of operations on a single installation path."""
from contextlib import contextmanager
from functools import wraps
import hashlib
import os
from pathlib import Path

@contextmanager
def installation_lock(path):
    path = Path(path).resolve()
    digest = hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()
    lock = path.parent / (".sentra-install-" + digest + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"0"); stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("another installation operation is running") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

def serialized_update(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        path = kwargs.get("install_dir") or args[1 if function.__name__ == "apply_update" else 0]
        with installation_lock(path):
            return function(*args, **kwargs)
    return wrapped
