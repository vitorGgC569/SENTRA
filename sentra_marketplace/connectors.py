"""Known connectors stay unavailable until a local package is opted in.

Names are a catalog, not a connection. This module does not open a socket.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from .absence import absence_stamp
from .gate import PackagePin, Subject
from .packages import claims_self_grant

_LOCAL_FILE = "local_invoke.py"
_MODULE_NAME = "sentra_optional_connector_local"

KNOWN_CONNECTORS = {
    "github": "connector:github:invoke",
    "google-drive": "connector:google-drive:invoke",
    "onedrive": "connector:onedrive:invoke",
    "microsoft-365": "connector:microsoft-365:invoke",
    "slack": "connector:slack:invoke",
}


def connector_status(marketplace, connector_id: str, owner: str | None = None) -> dict[str, Any]:
    """Presence is a local package. Opt-in is a separate host decision."""
    if connector_id not in KNOWN_CONNECTORS:
        reason = "CONNECTOR_UNKNOWN"
        return {
            "id": connector_id, "available": False, "reason": reason,
            "opt_in_required": True, "network": False, "grants_created": False,
            "homologated": False, "connector_real": False, **absence_stamp(reason),
        }
    described = marketplace.describe(connector_id, owner)
    if not described.get("present"):
        reason = "CONNECTOR_PACKAGE_ABSENT"
        return {
            "id": connector_id, "capability": KNOWN_CONNECTORS[connector_id],
            "available": False, "reason": reason,
            "opt_in_required": True, "network": False, "grants_created": False,
            "homologated": False, "connector_real": False, **absence_stamp(reason),
        }
    return {
        "id": connector_id, "capability": KNOWN_CONNECTORS[connector_id],
        "available": bool(described.get("opted_in")),
        "present": True, "opted_in": bool(described.get("opted_in")),
        "reason": "opted_in" if described.get("opted_in") else "present_opt_in_required",
        "opt_in_required": True, "network": False, "grants_created": False,
        "homologated": False,
    }


def _default_package_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "skills" / "optional_connectors"


def _directory_manifest(package_dir: Path) -> dict:
    path = package_dir / "sentra-package.json"
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _execute_local_connector(path: Path, context: dict) -> Any:
    import sys
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError("PACKAGE_ABSENT")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    function = getattr(module, "run", None)
    if not callable(function):
        raise RuntimeError("local connector file has no run function")
    return function(context)


def _context_for_local(context, transport, read, credential):
    bound = dict(context)
    if transport is not None:
        bound["transport"] = transport
    if read is not None:
        bound["read"] = read
    if credential is not None:
        bound["credential"] = credential
    return bound


def invoke_connector(gate, marketplace, authorization, binding, policy, connector_id: str,
                     effect=None, package_dir=None, *, transport=None, read=None, credential=None):
    """Invoke only through the optional gate. A missing package does not connect.

    An explicit ``effect`` keeps the marketplace payload path. Without one,
    ``skills/optional_connectors/local_invoke.py`` runs in process. That file
    fails when there is no credential and no permitted network. ``transport``
    is a test double: GitHub may perform one delimited read and return its
    payload. This function does not open a socket.
    """
    status = connector_status(marketplace, connector_id, binding.owner)
    described = marketplace.describe(connector_id, binding.owner)
    manifest = dict(described.get("manifest") or {})
    if described.get("self_grant"):
        manifest["self_grant"] = True
    subject = Subject(
        kind="connector",
        subject_id=connector_id,
        capability=KNOWN_CONNECTORS.get(connector_id, f"connector:{connector_id}:invoke"),
        manifest=manifest,
        content="",
    )
    pin = None
    package_path = None
    local_effect = effect
    if described.get("present") and described.get("sha256") and described.get("payload_path") and effect is not None:
        pin = PackagePin(connector_id, "connector", described["payload_path"], described["sha256"])
    if connector_id not in KNOWN_CONNECTORS:
        subject = Subject(
            kind="connector", subject_id="unknown-connector",
            capability="connector:unknown:invoke", manifest={}, content="",
        )
        return gate.invoke(
            authorization=authorization, binding=binding, policy=policy,
            subject=subject, package=None, effect=None,
            unavailable_reason="CONNECTOR_UNKNOWN",
        )
    if effect is None:
        directory = Path(package_dir) if package_dir is not None else _default_package_dir()
        directory_manifest = _directory_manifest(directory)
        if claims_self_grant(directory_manifest):
            manifest = {**manifest, "self_grant": True}
            subject = Subject(
                kind="connector", subject_id=connector_id, capability=subject.capability,
                manifest=manifest, content="",
            )
            pin = None
            local_effect = None
            package_path = None
        else:
            file = directory / _LOCAL_FILE
            if file.is_symlink() or not file.is_file():
                pin = None
                local_effect = None
                package_path = None
            else:
                digest = hashlib.sha256(file.read_bytes()).hexdigest()
                pin = PackagePin(connector_id, "connector", str(file), digest)
                package_path = str(file.resolve())

                def local_effect(
                    context, _file=file, _transport=transport, _read=read, _credential=credential,
                ):
                    if _transport is not None:
                        context["transport_only"] = True
                    return _execute_local_connector(
                        _file, _context_for_local(context, _transport, _read, _credential),
                    )
    del status
    return gate.invoke(
        authorization=authorization, binding=binding, policy=policy,
        subject=subject, package=pin, effect=local_effect,
        local_process=local_effect is not None,
        package_path=package_path,
    )
