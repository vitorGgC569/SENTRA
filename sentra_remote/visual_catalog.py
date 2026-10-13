"""Local visual-model catalog. A missing model is unavailable. No training."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}\Z")


class VisualModelCatalog:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root) / "visual-models"
        self.root.mkdir(parents=True, exist_ok=True)

    def _check(self, name: str) -> None:
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("invalid visual model name")

    def _dir(self, name: str) -> Path:
        self._check(name)
        return self.root / name

    def list_models(self) -> list[dict]:
        names = sorted(path.name for path in self.root.iterdir() if path.is_dir())
        return [self.health(name) for name in names]

    def health(self, name: str) -> dict:
        folder = self._dir(name)
        meta_path = folder / "model.json"
        blob_path = folder / "model.bin"
        if not meta_path.is_file() or not blob_path.is_file():
            return {"name": name, "state": "unavailable", "installed": False}
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        payload = blob_path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if meta.get("sha256") != digest or meta.get("bytes") != len(payload):
            return {"name": name, "state": "unavailable", "installed": True, "reason": "digest"}
        return {"name": name, "state": "ready", "installed": True,
                "sha256": digest, "bytes": len(payload), "grants_execution": False}

    def install(self, name: str, payload: bytes) -> dict:
        if not isinstance(payload, bytes) or not payload or len(payload) > 8_000_000:
            raise ValueError("visual model payload must be 1..8000000 bytes")
        folder = self._dir(name)
        if folder.exists():
            raise FileExistsError("visual model already installed; remove it before replacing")
        digest = hashlib.sha256(payload).hexdigest()
        folder.mkdir()
        (folder / "model.bin").write_bytes(payload)
        (folder / "model.json").write_text(json.dumps(
            {"name": name, "sha256": digest, "bytes": len(payload)}, sort_keys=True),
            encoding="utf-8")
        health = self.health(name)
        if health["state"] != "ready":
            shutil.rmtree(folder)
            raise RuntimeError("visual model install did not verify")
        return health

    def remove_preview(self, name: str) -> dict:
        health = self.health(name)
        body = {"name": name, "action": "remove", "state": health["state"],
                "effect": "delete the local visual model files only"}
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return {**body, "preview_sha256": hashlib.sha256(encoded.encode()).hexdigest()}

    def remove(self, name: str, *, preview_sha256: str) -> dict:
        preview = self.remove_preview(name)
        if preview_sha256 != preview["preview_sha256"]:
            raise PermissionError("visual model remove requires the current preview")
        folder = self._dir(name)
        if folder.is_dir():
            shutil.rmtree(folder)
            return {"name": name, "state": "unavailable", "removed": True, "replayed": False}
        return {"name": name, "state": "unavailable", "removed": False, "replayed": True}
