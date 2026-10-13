"""Read-only shell release probe for future QA (Vitra-owned).

Does not install, start services, inspect credentials or publish artifacts.
Verifies the shell-first packaging contract without executing validation:
shell bundle presence, bridge envelope, migration journal and release
manifest shell fields.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def probe(static_dir: Path, release_dir: Path | None = None) -> dict:
    from scripts.commander.build_canvas import validate_desktop_bundle, validate_shell_bundle
    desktop = validate_desktop_bundle(static_dir)
    shell = validate_shell_bundle(static_dir)
    result: dict = {
        "schema": 1,
        "desktop_bundle": {"files": len(desktop.get("files", {}))},
        "shell_bundle": shell,
        "bridge_contract": "POST /api/shell/bridge",
        "canvas_role": "internal_orchestration_view",
    }
    if release_dir is not None:
        manifest_file = Path(release_dir) / "release-manifest.json"
        if manifest_file.is_file():
            manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
            surface = manifest.get("shell_surface") or {}
            result["release_shell_surface"] = {
                "bridge_contract": surface.get("bridge_contract"),
                "canvas_role": surface.get("canvas_role"),
                "fallback": surface.get("fallback"),
            }
            if manifest.get("sidecars") is not None:
                result["release_sidecars"] = "present"
            if manifest.get("provider_pins") is not None:
                result["release_provider_pins"] = "present"
            if manifest.get("artwork_provenance") is not None:
                result["release_artwork_provenance"] = "present"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SENTRA shell packaging probe")
    parser.add_argument("--static", type=Path, default=ROOT / "sentra_canvas" / "static")
    parser.add_argument("--release", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(probe(args.static, args.release), sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema": 1, "result": "fail", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
