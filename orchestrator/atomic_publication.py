"""Publish an already prepared snapshot without repeating its producer."""
from __future__ import annotations

import os
import time
from pathlib import Path


def replace_prepared_snapshot(source: str | Path, destination: str | Path) -> None:
    """Retry only Windows delete-sharing refusals of this exact replacement.

    The caller retains its ownership lock, fsync and temporary-file cleanup.
    Six attempts wait at most 150ms; permanent failures remain failures.
    """
    for attempt in range(6):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            if (os.name != "nt" or getattr(exc, "winerror", None) not in {5, 32, 33}
                    or attempt == 5):
                raise
            time.sleep(0.01 * (attempt + 1))
