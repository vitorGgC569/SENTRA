"""Local license display and a support bundle that omits credentials."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

_SECRET_NAMES = frozenset({
    "auth.json", ".env", "relay-token", "credentials.json", "id_rsa",
})
_SECRET_LINE = re.compile(r"(api[_-]?key|token|password|bearer|secret)\s*[:=]", re.I)


def license_state(path: Path | str) -> dict:
    """Read a local license file. The license never authorizes an effect."""
    source = Path(path)
    if not source.is_file():
        return {"state": "unlicensed", "grants_execution": False}
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("license file schema required")
    state = value.get("state")
    if state not in {"active", "expired", "unlicensed"}:
        raise ValueError("unsupported license state")
    return {"state": state, "holder": value.get("holder") or "",
            "grants_execution": False}


def write_support_bundle(source: Path | str, dest: Path | str) -> dict:
    """Zip readable notes. Credential names and secret lines are omitted."""
    root = Path(source).resolve()
    target = Path(dest)
    if target.exists():
        raise FileExistsError("support bundle destination already exists")
    included: list[str] = []
    omitted: list[str] = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if path.name in _SECRET_NAMES or any(part in _SECRET_NAMES for part in path.parts):
                omitted.append(relative)
                continue
            text = None
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None and _SECRET_LINE.search(text):
                omitted.append(relative)
                continue
            archive.write(path, relative)
            included.append(relative)
    return {"included": included, "omitted": omitted, "contains_credentials": False}
