"""Exclusive application instance lock. Prevents falsely marking live PTYs stale."""
from __future__ import annotations
import os
from pathlib import Path

class InstanceLock:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=open(self.path,"a+b")
        try:
            self.file.seek(0)
            if not self.file.read(1):
                self.file.seek(0)
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except (OSError,IOError) as exc:
            self.file.close()
            raise RuntimeError("SENTRA Canvas is already running for this root") from exc

    def close(self):
        if self.file.closed:return
        self.file.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
        self.file.close()
