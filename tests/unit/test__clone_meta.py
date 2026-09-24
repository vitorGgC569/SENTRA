from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_write_clone_metadata():
    root = Path(__file__).resolve().parents[2]
    repo = root / "third_party" / "codex-chatgpt-web"
    def run(*args):
        p = subprocess.run(["git","-C",str(repo),*args], capture_output=True, text=True, timeout=20)
        assert p.returncode == 0, p.stdout + p.stderr
        return p.stdout.strip()
    meta = {
        "head": run("rev-parse","HEAD"),
        "branch": run("branch","--show-current"),
        "origin": run("remote","get-url","origin"),
        "status": run("status","--short"),
    }
    (root/".sentra"/"codex-chatgpt-web-clone-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
