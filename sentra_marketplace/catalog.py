"""Local marketplace catalog. Listing does not install or enable a package."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .absence import absence_stamp
from .gate import PackagePin, Subject
from .packages import MAX_MANIFEST_BYTES, claims_self_grant, verify_file

_MAX_PACKAGES = 64


class LocalMarketplace:
    """Read pinned ``sentra-package.json`` manifests from a local directory.

    A missing directory is ``CATALOG_ABSENT``. Nothing is downloaded.
    """

    def __init__(self, root: Path | str | None, *, state_root: Path | str | None = None):
        self.root = None if root is None else Path(root)
        self.state_root = None if state_root is None else Path(state_root)

    def list(self, owner: str | None = None) -> dict[str, Any]:
        opted = self._opted(owner)
        if self.root is None or not self.root.exists():
            return self._envelope([], reason="CATALOG_ABSENT", opted=opted)
        if self.root.is_symlink() or not self.root.is_dir():
            return self._envelope([], reason="CATALOG_ABSENT", opted=opted)
        items = []
        for manifest_path in self._manifests():
            items.append(self._describe_path(manifest_path, opted))
            if len(items) >= _MAX_PACKAGES:
                break
        reason = "CATALOG_EMPTY" if not items else "listed"
        return self._envelope(items, reason=reason, opted=opted)

    def describe(self, package_id: str, owner: str | None = None) -> dict[str, Any]:
        found = [item for item in self.list(owner)["items"] if item["id"] == package_id]
        if not found:
            reason = "PACKAGE_ABSENT"
            return {
                "id": package_id, "present": False, "available": False,
                "reason": reason, "opt_in_required": True,
                "network": False, "grants_created": False, "homologated": False,
                "connector_real": False, **absence_stamp(reason),
            }
        return found[0]

    def enable(self, gate, authorization, binding, policy, package_id: str) -> dict[str, Any]:
        item = self.describe(package_id, binding.owner)
        manifest = dict(item.get("manifest") or {})
        if item.get("self_grant"):
            manifest["self_grant"] = True
        kind = item.get("kind") if item.get("kind") in {
            "connector", "skill", "plugin", "marketplace_package", "visual_model",
        } else "marketplace_package"
        subject = Subject(
            kind=kind,
            subject_id=package_id,
            capability=item.get("capability") or f"marketplace:{package_id}:enable",
            manifest=manifest,
            content="",
        )
        pin = None
        if item.get("present") and item.get("sha256") and item.get("payload_path"):
            pin = PackagePin(package_id, subject.kind, item["payload_path"], item["sha256"])

        def effect(context):
            gate.record_opt_in(
                binding.owner, package_id, binding.operation.operation_id, context.get("grant_id"),
            )
            return {"opted_in": True, "network": False}

        receipt = gate.invoke(
            authorization=authorization, binding=binding, policy=policy,
            subject=subject, package=pin, effect=effect if pin is not None else None,
        )
        if receipt.get("outcome") == "SUCCEEDED":
            grant_id = receipt.get("grant_id")
            gate.record_opt_in(binding.owner, package_id, binding.operation.operation_id, grant_id)
            receipt = dict(receipt)
            receipt["opted_in"] = True
        return receipt

    def _manifests(self) -> list[Path]:
        found = []
        direct = self.root / "sentra-package.json"
        if direct.is_file() and not direct.is_symlink():
            found.append(direct)
        for child in sorted(self.root.iterdir(), key=lambda item: item.name):
            if child.is_symlink() or not child.is_dir():
                continue
            candidate = child / "sentra-package.json"
            if candidate.is_file() and not candidate.is_symlink():
                found.append(candidate)
            if len(found) >= _MAX_PACKAGES:
                break
        return found

    def _describe_path(self, manifest_path: Path, opted: set[str]) -> dict[str, Any]:
        base = {
            "present": False, "available": False, "opt_in_required": True,
            "opted_in": False, "network": False, "grants_created": False,
            "homologated": False, "self_grant": False, "manifest": {},
        }
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            return {**base, "id": manifest_path.parent.name, "reason": "PACKAGE_UNBOUNDED"}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {**base, "id": manifest_path.parent.name, "reason": "PACKAGE_MANIFEST_INVALID"}
        if not isinstance(manifest, dict):
            return {**base, "id": manifest_path.parent.name, "reason": "PACKAGE_MANIFEST_INVALID"}
        package_id = str(manifest.get("id") or manifest_path.parent.name)
        kind = str(manifest.get("kind") or "marketplace_package")
        capability = str(manifest.get("capability") or f"marketplace:{package_id}:enable")
        self_grant = claims_self_grant(manifest)
        item = {
            **base, "id": package_id, "name": manifest.get("name") or package_id,
            "kind": kind, "version": manifest.get("version"), "capability": capability,
            "self_grant": self_grant, "opted_in": package_id in opted,
            "manifest": {key: manifest.get(key) for key in ("id", "name", "kind", "version", "capability", "payload", "sha256")},
        }
        if self_grant:
            item["reason"] = "PLUGIN_SELF_GRANT"
            return item
        payload_name = manifest.get("payload")
        digest = manifest.get("sha256")
        if type(payload_name) is not str or payload_name != Path(payload_name).name:
            item["reason"] = "PACKAGE_ABSENT"
            return item
        payload = manifest_path.parent / payload_name
        checked = verify_file(payload, digest if isinstance(digest, str) else "")
        item["payload_path"] = str(payload)
        item["sha256"] = digest if isinstance(digest, str) else None
        if not checked.get("ok"):
            item["reason"] = checked.get("reason") or "PACKAGE_ABSENT"
            return item
        item["present"] = True
        item["available"] = package_id in opted
        item["bytes"] = checked["bytes"]
        item["reason"] = "present_opt_in_required" if package_id not in opted else "opted_in"
        return item

    def _opted(self, owner: str | None) -> set[str]:
        if owner is None or self.state_root is None:
            return set()
        path = self.state_root / "optional_receipts.sqlite3"
        if not path.is_file():
            return set()
        import sqlite3
        with sqlite3.connect(path) as db:
            rows = db.execute(
                "SELECT package_id FROM optional_opt_in WHERE owner=?", (owner,)
            ).fetchall()
        return {row[0] for row in rows}

    @staticmethod
    def _envelope(items, *, reason, opted) -> dict[str, Any]:
        del opted
        body = {
            "items": items, "reason": reason, "opt_in_required": True,
            "network": False, "grants_created": False, "homologated": False,
        }
        return {**body, **absence_stamp(reason)}
