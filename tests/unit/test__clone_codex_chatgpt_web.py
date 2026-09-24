from __future__ import annotations

import subprocess
from pathlib import Path


def test_clone_codex_chatgpt_web():
    root = Path(__file__).resolve().parents[2]
    parent = root / "third_party"
    target = parent / "codex-chatgpt-web"
    parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        assert (target / ".git").is_dir(), "target exists but is not a git clone"
        return

    proc = subprocess.run(
        [
            "git", "clone",
            "https://github.com/miuuyy/codex-chatgpt-web.git",
            str(target),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert (target / ".git").is_dir()
