"""One read-only check of the producer CLI proof.

The script does not call sentra-cli, does not send a prompt, and does not
retry an uncertain operation. Exit 3 means the turn was withheld. That exit
is not product success and does not close the trio.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sentra_cli.producer_gate import assess_producer_proof
CODEX = Path.home() / "AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"
OPENCODE = Path.home() / "AppData/Roaming/npm/opencode.ps1"


def _read(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            cwd=str(ROOT),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, type(exc).__name__
    return result.returncode, result.stdout.decode("utf-8", errors="replace")


def main() -> int:
    codex_rc, codex_status = _read([str(CODEX), "login", "status"])
    opencode_rc, opencode_status = _read([
        "powershell", "-NoProfile", "-File", str(OPENCODE), "auth", "list", "--standalone",
    ])
    report = assess_producer_proof({
        "codex_rc": codex_rc,
        "codex_status": codex_status.strip(),
        "opencode_rc": opencode_rc,
        "opencode_status": opencode_status.strip(),
        "authority": None,
    })
    report["prompt_sent"] = False
    report["cli_invoked"] = False
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return 3 if report["producer_turn"] == "withheld" else 0


if __name__ == "__main__":
    sys.exit(main())
