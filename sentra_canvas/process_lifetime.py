"""Launch long-lived desktop owners outside the caller's Windows job.

CREATE_NO_WINDOW hides a console but does not detach from Codex/ChatGPT's job.
Never silently fall back to that lifetime when Windows denies breakaway.
"""
from __future__ import annotations
import os
import subprocess
import sys


def independent_flags() -> int:
    if os.name != 'nt':
        return 0
    if os.environ.get('SENTRA_DESKTOP_LAUNCH_CONTEXT') == 'windows-interactive':
        # The root was already launched by Windows in its own interactive job.
        # Task Scheduler may forbid breakaway; that job has no Codex dependency.
        return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_BREAKAWAY_FROM_JOB


def launch_independent(command, **kwargs):
    if getattr(sys, 'frozen', False):
        # A long-lived onefile child must extract its own resources. Reusing
        # the launcher's _MEIPASS loses static UI files when that launcher exits.
        kwargs['env'] = {**(kwargs.get('env') or os.environ), 'PYINSTALLER_RESET_ENVIRONMENT': '1'}
    try:
        return subprocess.Popen(command, creationflags=independent_flags(), **kwargs)
    except OSError as exc:
        if os.name == 'nt' and getattr(exc, 'winerror', None) == 5:
            raise RuntimeError('Windows denied an independent SENTRA process. Open SENTRA from its Windows shortcut.') from exc
        raise
