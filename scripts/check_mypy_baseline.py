"""Fail CI only when the known typed-core debt regresses.

This is intentionally a ratchet, not an ignore list.  Lower the baseline when
errors are fixed; never raise it to make CI green.
"""
from __future__ import annotations

import re
import subprocess
import sys

TARGETS = [
    "orchestrator/swarm_cycle.py",
    "orchestrator/conversation_pool.py",
    "sentra_mcp/services/control_plane.py",
    "sentra_mcp/services/context_projection.py",
    "orchestrator/providers/extension_provider.py",
]
MAX_ERRORS = 47


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", *TARGETS, "--ignore-missing-imports"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = proc.stdout or ""
    match = re.search(r"Found (\d+) errors? in", output)
    errors = int(match.group(1)) if match else (0 if proc.returncode == 0 else MAX_ERRORS + 1)
    print(output, end="")
    print(f"MYPY_BASELINE errors={errors} max={MAX_ERRORS}")
    if errors > MAX_ERRORS:
        print("Type debt regressed; fix new errors instead of raising the baseline.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

