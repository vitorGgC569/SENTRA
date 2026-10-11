"""Build the native SENTRA Canvas executable for the Windows Setup payload."""
from __future__ import annotations

import os
import sys
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def validate_desktop_bundle(ui: Path) -> dict:
    """Fail closed if the packaged React Canvas is missing or stale."""
    ui = Path(ui)
    entry = ui / "desktop.html"
    manifest_file = ui / "desktop-assets" / "manifest.json"
    if not entry.is_file() or not manifest_file.is_file():
        raise FileNotFoundError("SENTRA React Canvas bundle is missing; run npm run build in sentra_canvas/desktop_ui")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError("invalid SENTRA Canvas bundle manifest") from exc
    if (not isinstance(manifest, dict) or manifest.get("entry") != "/desktop.html"
            or manifest.get("script") != "/desktop-assets/desktop.js"
            or manifest.get("styles") != "/desktop-assets/desktop.css"
            or not isinstance(manifest.get("files"), dict)
            or not {"desktop.js", "desktop.css", "bootstrap.js"} <= set(manifest["files"])):
        raise ValueError("incomplete React Canvas bundle contract")
    for name, digest in manifest["files"].items():
        if (not isinstance(name, str) or "/" in name or "\\" in name or name.startswith(".")
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError("invalid React Canvas bundle file/hash")
        asset = manifest_file.parent / name
        if not asset.is_file() or hashlib.sha256(asset.read_bytes()).hexdigest() != digest:
            raise ValueError("stale or tampered React Canvas bundle: " + name)
    if "desktop-assets/bootstrap.js" not in entry.read_text(encoding="utf-8"):
        raise ValueError("React Canvas entry does not load its pinned bootstrap")
    return manifest


def build_canvas(dist: Path, work: Path, spec: Path) -> None:
    from scripts.commander.build_windows import _build
    from scripts.commander.pdfium_pin import require_pdfium

    ui = ROOT / "sentra_canvas" / "static"
    expected = (ui / "native.html", ui / "native.css", ui / "native.js")
    missing = [str(path) for path in expected if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Native SENTRA Canvas UI assets are missing: " + ", ".join(missing)
        )
    from scripts.commander.vendor_canvas_terminal import validate
    validate(ui / "vendor")
    validate_desktop_bundle(ui)
    require_pdfium()
    _build(
        "sentra-canvas",
        "canvas_entry.py",
        dist, work, spec,
        windowed=True,
        extra=[
            "--collect-all", "webview",
            "--collect-all", "pypdfium2",
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
