"""Core CLI entry point; Web Models is opt-in for this distribution."""
from __future__ import annotations

import os
import sys


def main() -> int:
    # Keep desktop defaults intact and never start a browser for core users.
    os.environ.setdefault("SENTRA_CLI_AUTO_START_GATEWAY", "0")
    # Do not silently borrow credentials from another application's profile.
    os.environ.setdefault("OPENAI_API_KEY", "none")
    if not os.environ.get("SENTRA_CLI_MODEL"):
        os.environ["SENTRA_CLI_MODEL"] = "gpt-4o" if os.environ["OPENAI_API_KEY"] not in {"", "none"} else "local"
    from .__main__ import main as cli_main
    args = sys.argv[1:]
    if args[:1] not in (["--gateway-service"], ["--job-worker"]) and os.environ["SENTRA_CLI_AUTO_START_GATEWAY"].lower() not in {"1", "true", "yes", "on"}:
        args = [*args, "--no-auto-start"]
    return cli_main(args)
