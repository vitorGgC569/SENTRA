"""Version-regression guard: deterministic detection of version downgrades.

Why: validators judge logic/requirements; a changed version constant looks like
any other line, so `OMA_CS_VERSION = "1.3.17"` -> `"1.3.9"` sailed through four
validators and the Master. Rule: if new_version < current_version, the change
REQUIRES_EXPLICIT_JUSTIFICATION — enforced here as a blocking finding, because
no justification channel exists yet (silent downgrades are never acceptable).

Only *downgrades* block. Upgrades are reported as INFO (visible, non-blocking).
New files carrying a version are reported, never blocked.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

# (path matcher, version regex with ONE capture group for the version string)
VERSION_PATTERNS: List[Tuple[str, str]] = [
    ("manifest.json", r'"version"\s*:\s*"([^"]+)"'),
    ("package.json", r'"version"\s*:\s*"([^"]+)"'),
    ("pyproject.toml", r'(?m)^version\s*=\s*["\']([^"\']+)["\']'),
    ("*.js", r'OMA_(?:SW|CS)_VERSION\s*=\s*"([^"]+)"'),
    ("*.py", r'__version__\s*=\s*["\']([^"\']+)["\']'),
]


def _matches(pattern: str, path: str) -> bool:
    name = PurePosixPath(path).name
    if pattern.startswith("*."):
        return name.endswith(pattern[1:])
    return name == pattern or path.endswith("/" + pattern)


def extract_versions(files: Dict[str, str]) -> Dict[str, str]:
    """path -> version string for every recognized version constant found."""
    found: Dict[str, str] = {}
    for path, content in files.items():
        for pattern, rx in VERSION_PATTERNS:
            if _matches(pattern, path):
                m = re.search(rx, content or "")
                if m:
                    found[path] = m.group(1)
    return found


def _parts(version: str) -> Optional[List[Any]]:
    chunks = re.split(r"[.\-+_]", version.strip())
    if not chunks or not chunks[0]:
        return None
    out: List[Any] = []
    for chunk in chunks:
        out.append(int(chunk) if chunk.isdigit() else chunk)
    return out


def compare_versions(old: str, new: str) -> Optional[int]:
    """-1 if new < old (downgrade), 0 if equal, +1 if new > old, None if unknown."""
    a, b = _parts(old), _parts(new)
    if a is None or b is None:
        return None
    for x, y in zip(a, b):  # x=old part, y=new part; +1 means upgrade
        if type(x) is type(y):
            if x != y:
                return 1 if (x < y if isinstance(x, int) else str(x) < str(y)) else -1
        elif isinstance(x, int):
            return -1  # old numeric vs new tag: new is smaller (1.0 > 1.0-anything)
        else:
            return 1
    if len(a) == len(b):
        return 0
    longer, base = (a, b) if len(a) > len(b) else (b, a)
    rest = longer[len(base):]
    if all(r == 0 for r in rest):
        return 0
    if any(isinstance(r, str) for r in rest):
        return -1 if longer is b else 1  # pre-release suffix side is smaller
    return 1 if longer is b else -1


def check_patch(base_files: Dict[str, str], patch_text: str) -> Dict[str, Any]:
    """Compare version constants before/after applying patch_text to base_files.

    base_files: path -> current content. Returns
    {"changed": [...], "upgrades": [...], "downgrades": [{path, old, new}], "added": [...]},
    where an entry is {"path":..., "old":...|None, "new":...}.
    Never raises on unparseable patches: returns {"error": ...} instead, so a
    broken diff cannot silently skip the version check (caller decides).
    """
    from workspace.patch_manager import PatchManager
    try:
        file_patches = PatchManager.parse_files(patch_text or "")
    except Exception as exc:
        return {"changed": [], "upgrades": [], "downgrades": [], "added": [],
                "error": f"unparseable patch: {exc}"[:200]}
    changed, upgrades, downgrades, added = [], [], [], []
    for fp in file_patches:
        old_content = base_files.get(fp.path, "")
        try:
            new_lines = PatchManager._apply_hunks(
                old_content.splitlines(keepends=True), fp.hunks)
        except Exception as exc:
            return {"changed": [], "upgrades": [], "downgrades": [], "added": [],
                    "error": f"unapplicable patch at {fp.path}: {exc}"[:200]}
        old_versions = extract_versions({fp.path: old_content})
        new_versions = extract_versions({fp.path: "".join(new_lines)})
        old_v, new_v = old_versions.get(fp.path), new_versions.get(fp.path)
        if old_v == new_v:
            continue
        entry = {"path": fp.path, "old": old_v, "new": new_v}
        changed.append(entry)
        if old_v is None:
            added.append(entry)
            continue
        if new_v is None:
            downgrades.append({**entry, "reason": "version constant removed"})
            continue
        cmp = compare_versions(old_v, new_v)
        if cmp is None:
            downgrades.append({**entry, "reason": "uncomparable versions; fail closed"})
        elif cmp < 0:
            downgrades.append(entry)
        else:
            upgrades.append(entry)
    return {"changed": changed, "upgrades": upgrades, "downgrades": downgrades, "added": added}
