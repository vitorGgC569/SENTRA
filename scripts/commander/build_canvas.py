"""Build the native SENTRA Canvas executable for the Windows Setup payload."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_canvas(dist: Path, work: Path, spec: Path) -> None:
    from scripts.commander.build_windows import _build

    ui = ROOT / "sentra_canvas" / "static"
    expected = (ui / "native.html", ui / "native.css", ui / "native.js")
    missing = [str(path) for path in expected if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Native SENTRA Canvas UI assets are missing: " + ", ".join(missing)
        )
    from scripts.commander.vendor_canvas_terminal import validate
    validate(ui / "vendor")
    _build(
        "sentra-canvas",
        "canvas_entry.py",
        dist, work, spec,
        windowed=True,
        extra=[
            "--collect-all", "webview",
            "--add-data", f"{ui}{os.pathsep}sentra_canvas/static",
        ],
    )
    result = dist / "sentra-canvas.exe"
    if not result.is_file() or result.stat().st_size == 0:
        raise RuntimeError("native SENTRA Canvas executable was not built")


if __name__ == "__main__":
    from scripts.commander.build_windows import main
    sys.argv[1:1] = ["--phase", "canvas"]
    raise SystemExit(main())
