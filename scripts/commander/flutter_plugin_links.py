"""Prepare isolated Flutter plugin junctions without changing Windows settings.

Flutter treats NTFS junctions as directory links. Only host-selected Pub cache
directories may be linked; existing links must point to the exact same target.
This is a build helper, never part of the installed application's startup.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re


def prepare_flutter_plugin_links(project: Path, pub_cache: Path) -> list[dict]:
    if os.name != "nt":
        raise RuntimeError("Flutter junction helper requires Windows")
    import _winapi

    project = Path(project).resolve(strict=True)
    pub_cache = Path(pub_cache).resolve(strict=True)
    if project.is_relative_to(pub_cache) or pub_cache.is_relative_to(project):
        raise ValueError("Flutter project and Pub cache must be separate")
    descriptor = project / ".flutter-plugins-dependencies"
    if descriptor.is_symlink() or descriptor.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("unsafe Flutter plugin descriptor")
    plugins = json.loads(descriptor.read_text(encoding="utf-8"))["plugins"]
    planned = []
    for platform in ("windows", "linux"):
        link_root = project / platform / "flutter/ephemeral/.plugin_symlinks"
        if not (project / platform).is_dir():
            continue
        if not link_root.resolve().is_relative_to(project):
            raise ValueError("Flutter plugin link directory escaped the build project")
        seen = set()
        entries = plugins.get(platform, [])
        if not isinstance(entries, list) or len(entries) > 256:
            raise ValueError("invalid Flutter plugin list")
        for entry in entries:
            name = entry["name"]
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,128}", name) or name.casefold() in seen:
                raise ValueError("invalid or duplicate Flutter plugin name")
            seen.add(name.casefold())
            target = Path(entry["path"]).resolve(strict=True)
            if not target.is_dir() or not target.is_relative_to(pub_cache) or target == pub_cache:
                raise ValueError("Flutter plugin source escaped the selected Pub cache")
            link = link_root / name
            existing = os.path.lexists(link)
            if existing and (not link.is_junction() or link.resolve(strict=True) != target):
                raise FileExistsError("existing Flutter plugin entry differs: " + name)
            planned.append((link, target, platform, name, existing))
    # Validate the entire plan before mutation. No directory is deleted, and
    # no link target (the shared Pub cache) is modified by this helper.
    for link, target, _, _, existing in planned:
        if existing:
            continue
        link.parent.mkdir(parents=True, exist_ok=True)
        _winapi.CreateJunction(str(target), str(link))
        if not link.is_junction() or link.resolve(strict=True) != target:
            raise RuntimeError("Flutter plugin junction verification failed")
    return [{"platform": platform, "name": name, "target": str(target)}
            for _, target, platform, name, _ in planned]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--pub-cache", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = prepare_flutter_plugin_links(args.project, args.pub_cache)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"junctions_verified": len(result), "system_settings_changed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
