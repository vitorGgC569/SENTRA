"""Headless packaging probe; never opens browsers, accounts or product services."""
import json
from pathlib import Path
import subprocess
import sys

from playwright._impl._driver import compute_driver_executable

node, cli = compute_driver_executable()
result = subprocess.run([node, cli, "--version"], capture_output=True, text=True, timeout=20)
support = Path(getattr(sys, "_MEIPASS", ""))
print(json.dumps({"frozen": bool(getattr(sys, "frozen", False)),
    "support_directory": support.name,
    "support_is_installed_sibling": support.parent.samefile(Path(sys.executable).parent),
    "driver_available": Path(node).is_file() and Path(cli).is_file(),
    "driver_runs": result.returncode == 0, "driver_version": result.stdout.strip()}))
raise SystemExit(0 if result.returncode == 0 else 2)
