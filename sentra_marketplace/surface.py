"""Useful optional surfaces. An absence stamp does not close the capability.

Authorization stays on the host Grant. This module does not call ``grant``
and does not download weights or sign in to an account.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
from pathlib import Path
from typing import Any

from .connectors import KNOWN_CONNECTORS, _default_package_dir, invoke_connector

SURFACES = ("connector", "skill", "plugin", "automation", "marketplace", "visual")

_RUNTIMES = ("torch", "onnxruntime", "diffusers", "open_clip", "PIL")
_ACCOUNT_CONNECTORS = {
    "github": "conta GitHub e token do host",
    "google-drive": "conta Google e consentimento do host",
    "onedrive": "conta Microsoft e consentimento do host",
    "microsoft-365": "conta Microsoft 365 e consentimento do host",
    "slack": "workspace Slack e token do host",
}


def _importable(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _egress(host: str = "github.com", port: int = 443, timeout: float = 3.0) -> dict[str, Any]:
    """One concrete socket check. Failure is not a general network ban."""
    try:
        with socket.create_connection((host, port), timeout):
            return {"host": host, "port": port, "reachable": True, "assumed_block": False}
    except OSError as exc:
        return {
            "host": host, "port": port, "reachable": False, "assumed_block": False,
            "reason": type(exc).__name__,
        }


def inventory(root: Path | str | None = None, *, probe_egress: bool = False) -> dict[str, Any]:
    """What is on disk and what a concrete account or download would still require."""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    package = _default_package_dir() if root is None else Path(root) / "skills" / "optional_connectors"
    if root is not None and (Path(root) / "local_invoke.py").is_file():
        package = Path(root)
    script = package / "local_invoke.py"
    skill = package / "SKILL.md"
    catalog = base / "sentra_marketplace" / "catalog"
    weights = base / "local_model" / "packs" / "visual"
    runtimes = {name: _importable(name) for name in _RUNTIMES}
    visual_runtime = any(runtimes[name] for name in ("torch", "onnxruntime", "diffusers", "open_clip"))
    items = []
    for name in SURFACES:
        if name == "connector":
            present = script.is_file()
            reason = "local_package_present" if present else "PACKAGE_ABSENT"
            needs = (
                "credencial do host e rede permitida; sem ambas a execucao falha e nao responde pela conta"
                if present else "arquivo local_invoke.py"
            )
        elif name == "skill":
            present = skill.is_file()
            reason = "skill_text_present" if present else "SKILL_ABSENT"
            needs = "o texto continua dado; nao concede Grant"
        elif name == "visual":
            present = weights.exists()
            reason = "weights_present" if present else "MODEL_PACKAGE_ABSENT"
            needs = "runtime visual e pesos locais, ou download concreto do pacote; nao ha bloqueio geral de rede inferido"
        elif name == "marketplace":
            present = catalog.is_dir()
            reason = "catalog_present" if present else "CATALOG_ABSENT"
            needs = "catalogo local opt-in; conectores externos pedem conta concreta, nao um bloqueio geral"
        else:
            present = False
            reason = "PACKAGE_ABSENT"
            needs = "pacote local opt-in ainda nao esta neste checkout"
        items.append({
            "surface": name,
            "present": present,
            "opt_in_required": True,
            "available": present and (name != "visual" or visual_runtime),
            "closed_by_absence": False,
            "capability_closed": False,
            "reason": reason,
            "needs": needs,
            "grants_created": False,
            "homologated": False,
        })
    return {
        "items": items,
        "closed_by_absence": False,
        "package_path": str(script.resolve()) if script.is_file() else None,
        "skill_path": str(skill.resolve()) if skill.is_file() else None,
        "catalog_path": str(catalog) if catalog.is_dir() else None,
        "weights_path": str(weights) if weights.exists() else None,
        "runtimes": runtimes,
        "visual_runtime_importable": visual_runtime,
        "accounts": dict(_ACCOUNT_CONNECTORS),
        "connectors": dict(KNOWN_CONNECTORS),
        "egress": _egress() if probe_egress else {"probed": False, "assumed_block": False},
        "ui": {
            "projection": "optional-surfaces",
            "control_plane": "host Grant via AuthorizationService.authorize",
            "shell_skill_route": "center_skill_library",
            "absence_does_not_close": list(SURFACES),
        },
        "grants_created": False,
        "homologated": False,
    }


def write_execution_artifact(receipt: dict[str, Any], directory: Path | str) -> dict[str, Any]:
    """Persist the host receipt next to the gate state. Absence is not success."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    operation_id = str(receipt.get("operation_id") or "missing-operation")
    path = folder / f"{operation_id}.json"
    package_path = receipt.get("package_path")
    package_sha256 = None
    if isinstance(package_path, str):
        pinned = Path(package_path)
        if not pinned.is_symlink() and pinned.is_file():
            package_sha256 = hashlib.sha256(pinned.read_bytes()).hexdigest()
    body = {
        "artifact": str(path.resolve()),
        "package_path": package_path,
        "package_sha256": package_sha256,
        "operation_id": receipt.get("operation_id"),
        "run_id": receipt.get("run_id"),
        "work_item_id": receipt.get("work_item_id"),
        "grant_id": receipt.get("grant_id"),
        "outcome": receipt.get("outcome"),
        "reason": receipt.get("reason"),
        "connector_real": receipt.get("connector_real"),
        "absence_probe": receipt.get("absence_probe"),
        "closed_by_absence": False,
        "network_used": False,
        "quickjs": False,
        "visual_weights": False,
        "grants_created": False,
        "self_grant": False,
        "homologated": False,
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return body


def execute_authorized(gate, marketplace, authorization, binding, policy, connector_id: str, *,
                       package_dir=None, artifact_dir: Path | str) -> dict[str, Any]:
    """Run only after the host Grant. Writes the receipt artifact. Does not grant."""
    receipt = invoke_connector(
        gate, marketplace, authorization, binding, policy, connector_id,
        package_dir=package_dir,
    )
    artifact = write_execution_artifact(receipt, artifact_dir)
    return {**receipt, "artifact": artifact, "closed_by_absence": False, "homologated": False}
