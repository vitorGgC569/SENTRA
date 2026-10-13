"""OS-protected bounded assets; never a model delivery receipt or authority."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import uuid

from sentra_remote.secrets import protect_secret, unprotect_secret


def checkpoint(*, required=False):
    from sentra_runtime.effect_boundary import current_effect_context
    context = current_effect_context.get()
    if context is None:
        if required:
            raise PermissionError("asset effect requires current central admission")
        return
    context.checkpoint()


def safe_path(root: Path, path: Path) -> Path:
    root = root.absolute()
    path = path.absolute()
    if not path.is_relative_to(root) or any(p.is_symlink() for p in (path, *path.parents)):
        raise PermissionError("asset path escapes protected state root")
    return path


def write_asset(root: Path, path: Path, raw: bytes, *, binding: str):
    checkpoint(required=True)
    path = safe_path(root, path)
    digest = hashlib.sha256(raw).hexdigest()
    value = {"v": 1, "binding": binding, "sha256": digest,
             "bytes": len(raw), "data": base64.b64encode(raw).decode("ascii")}
    protected = protect_secret(json.dumps(value, separators=(",", ":")))
    if not protected.startswith(("dpapi:", "keyring:")):
        raise RuntimeError("OS-protected asset storage unavailable")
    checkpoint(required=True)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        checkpoint(required=True)
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as out:
            out.write(protected)
            out.flush()
            os.fsync(out.fileno())
        checkpoint(required=True)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            checkpoint(required=True)
            temporary.unlink()


def read_asset(root: Path, path: Path, *, binding: str, max_bytes: int) -> bytes:
    checkpoint()
    path = safe_path(root, path)
    # DPAPI/base64 envelopes grow; cap BEFORE reading/decrypting.
    if path.stat().st_size > max_bytes * 3 + 65536:
        raise PermissionError("protected asset outside bounds")
    protected = path.read_text(encoding="ascii")
    if not protected.startswith(("dpapi:", "keyring:")):
        raise PermissionError("legacy plaintext asset requires explicit protected migration")
    value = json.loads(unprotect_secret(protected))
    if not isinstance(value, dict) or value.get("v") != 1 or value.get("binding") != binding:
        raise PermissionError("protected asset binding mismatch")
    raw = base64.b64decode(value["data"], validate=True)
    if (not 0 < len(raw) <= max_bytes or len(raw) != value["bytes"]
            or hashlib.sha256(raw).hexdigest() != value["sha256"]):
        raise PermissionError("protected asset digest mismatch")
    return raw
