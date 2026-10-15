"""Local package pins. Missing bytes are an explicit absence, never a fetch."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_SHA = re.compile(r"^[a-f0-9]{64}\Z")
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
VISUAL_FORMAT = "sentra-visual-pack-v1"

_SELF_GRANT_KEYS = {"grant", "grants", "self_grant", "issue_grant", "authorization"}


def claims_self_grant(manifest) -> bool:
    """True when a manifest tries to mint or declare a Grant for itself."""
    if not isinstance(manifest, dict):
        return False
    for key, value in manifest.items():
        if str(key).casefold() in _SELF_GRANT_KEYS and value not in (None, False, "", [], {}):
            return True
    return False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_file(path: Path, expected_sha256: str, *, absent_reason: str = "PACKAGE_ABSENT") -> dict:
    """Read a pinned local file. No network, no install, no symlink."""
    if type(expected_sha256) is not str or not _SHA.fullmatch(expected_sha256):
        return {"ok": False, "reason": "PACKAGE_HASH_REQUIRED", "bytes": 0}
    if path.is_symlink():
        return {"ok": False, "reason": "PACKAGE_SYMLINK_REFUSED", "bytes": 0}
    if not path.is_file():
        return {"ok": False, "reason": absent_reason, "bytes": 0}
    size = path.stat().st_size
    if size > MAX_PACKAGE_BYTES or size < 1:
        return {"ok": False, "reason": "PACKAGE_UNBOUNDED", "bytes": size}
    digest = _sha256(path.read_bytes())
    if digest != expected_sha256:
        return {"ok": False, "reason": "PACKAGE_HASH_MISMATCH", "bytes": size, "sha256": digest}
    return {"ok": True, "reason": "present", "bytes": size, "sha256": digest}


def verify_visual_pack(path: Path, expected_sha256: str) -> dict:
    """A visual pack is a local directory with model.json and a weights file.

    Hash match of the weights file is presence. It is not inference.
    """
    if type(expected_sha256) is not str or not _SHA.fullmatch(expected_sha256):
        return {"ok": False, "reason": "PACKAGE_HASH_REQUIRED", "bytes": 0,
                "inference_homologated": False}
    if path.is_symlink():
        return {"ok": False, "reason": "PACKAGE_SYMLINK_REFUSED", "bytes": 0,
                "inference_homologated": False}
    if not path.exists():
        return {"ok": False, "reason": "MODEL_PACKAGE_ABSENT", "bytes": 0,
                "inference_homologated": False}
    if path.is_file():
        checked = verify_file(path, expected_sha256, absent_reason="MODEL_PACKAGE_ABSENT")
        checked["inference_homologated"] = False
        if checked["ok"]:
            checked["reason"] = "weights_present"
        elif checked["reason"] == "PACKAGE_HASH_MISMATCH":
            checked["reason"] = "MODEL_HASH_MISMATCH"
        return checked
    if not path.is_dir():
        return {"ok": False, "reason": "MODEL_PACKAGE_ABSENT", "bytes": 0,
                "inference_homologated": False}
    manifest_path = path / "model.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return {"ok": False, "reason": "MODEL_PACKAGE_ABSENT", "bytes": 0,
                "inference_homologated": False}
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        return {"ok": False, "reason": "PACKAGE_UNBOUNDED", "bytes": 0,
                "inference_homologated": False}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"ok": False, "reason": "PACKAGE_MANIFEST_INVALID", "bytes": 0,
                "inference_homologated": False}
    if not isinstance(manifest, dict):
        return {"ok": False, "reason": "PACKAGE_MANIFEST_INVALID", "bytes": 0,
                "inference_homologated": False}
    if claims_self_grant(manifest):
        return {"ok": False, "reason": "PLUGIN_SELF_GRANT", "bytes": 0,
                "inference_homologated": False, "manifest": manifest}
    if manifest.get("kind") != "visual" or manifest.get("format") != VISUAL_FORMAT:
        return {"ok": False, "reason": "MODEL_KIND_MISMATCH", "bytes": 0,
                "inference_homologated": False}
    weights_name = manifest.get("weights")
    if type(weights_name) is not str or weights_name != Path(weights_name).name or not weights_name:
        return {"ok": False, "reason": "MODEL_PACKAGE_ABSENT", "bytes": 0,
                "inference_homologated": False}
    pinned = manifest.get("sha256")
    if pinned != expected_sha256:
        return {"ok": False, "reason": "MODEL_HASH_MISMATCH", "bytes": 0,
                "inference_homologated": False}
    checked = verify_file(path / weights_name, expected_sha256, absent_reason="MODEL_PACKAGE_ABSENT")
    checked["inference_homologated"] = False
    if checked["reason"] == "PACKAGE_HASH_MISMATCH":
        checked["reason"] = "MODEL_HASH_MISMATCH"
    elif checked["ok"]:
        checked["reason"] = "weights_present"
        checked["manifest"] = {k: manifest[k] for k in ("kind", "name", "format", "weights")
                               if k in manifest}
    return checked


def verify_pin(pin) -> dict:
    path = Path(pin.path)
    if pin.kind == "visual_model":
        return verify_visual_pack(path, pin.sha256)
    absent = "MODEL_PACKAGE_ABSENT" if pin.kind == "visual_model" else "PACKAGE_ABSENT"
    return verify_file(path, pin.sha256, absent_reason=absent)
