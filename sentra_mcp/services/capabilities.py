"""Runtime capability/build/schema negotiation for SENTRA."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import MCPConfig
from ..version import (
    CAPABILITY_VERSION,
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
)

SEMANTIC_ERRORS = {
    "SCHEMA_MISMATCH",
    "PROTOCOL_MISMATCH",
    "CAPABILITY_MISMATCH",
    "CAPABILITY_MISSING",
    "PLUGIN_STALE",
    "REMOTE_AGENT_STALE",
    "SESSION_WRONG_PLACE",
    "SESSION_REQUIRED",
    "OPERATION_STILL_RUNNING",
    "STALE_FENCE",
    "STATE_CONFLICT",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _source_tree_hash(project_root: Path) -> str | None:
    """Hash executable SENTRA source so dirty builds cannot impersonate HEAD."""
    roots = (
        "sentra_mcp", "sentra_remote", "browser", "native_bridge",
        "orchestrator", "workspace",
    )
    files: list[Path] = []
    for name in roots:
        root = project_root / name
        if root.is_dir():
            files.extend(
                item for item in root.rglob("*.py")
                if "__pycache__" not in item.parts
            )
    for name in ("sentra_version.py",):
        candidate = project_root / name
        if candidate.is_file():
            files.append(candidate)
    if not files:
        return None
    digest = hashlib.sha256()
    for item in sorted(set(files), key=lambda p: p.relative_to(project_root).as_posix()):
        try:
            relative = item.relative_to(project_root).as_posix().encode("utf-8")
            payload = item.read_bytes()
        except OSError:
            continue
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _git_head(project_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and len(value) == 40 else None


@lru_cache(maxsize=8)
def server_build_identity(project_root: Path) -> dict[str, Any]:
    explicit = os.environ.get("SENTRA_BUILD_ID", "").strip()
    project_root = Path(project_root).resolve()
    commit = _git_head(project_root)
    source_hash = _source_tree_hash(project_root)
    executable_hash = (
        _file_sha256(Path(sys.executable))
        if getattr(sys, "frozen", False)
        else None
    )
    basis = {
        "server": SERVER_NAME,
        "server_version": SERVER_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "capability_version": CAPABILITY_VERSION,
        "git_commit": commit,
        "source_hash": source_hash,
        "executable_sha256": executable_hash,
        "executable": Path(sys.executable).name,
    }
    if explicit:
        build_id = explicit
        source = "environment"
    elif source_hash:
        prefix = commit[:8] if commit else "src"
        build_id = f"{prefix}-{source_hash[:16]}"
        source = "source-tree"
    elif executable_hash:
        build_id = "exe-" + executable_hash[:20]
        source = "binary"
    elif commit:
        build_id = commit[:16]
        source = "git"
    else:
        build_id = _sha(basis)[:20]
        source = "derived"
    return {
        "build_id": build_id,
        "git_commit": commit,
        "source_hash": source_hash,
        "executable_sha256": executable_hash,
        "source": source,
        "fingerprint": _sha(basis),
    }


def tool_schema_document(mcp: Any) -> dict[str, Any]:
    manager = getattr(mcp, "_tool_manager", None)
    tools = manager.list_tools() if manager is not None else []
    canonical = []
    for tool in tools:
        metadata = getattr(tool, "fn_metadata", None)
        output_schema = getattr(metadata, "output_schema", {}) if metadata is not None else {}
        canonical.append({
            "name": str(tool.name),
            "description": str(getattr(tool, "description", "") or ""),
            "parameters": getattr(tool, "parameters", {}) or {},
            "output_schema": output_schema or {},
        })
    canonical.sort(key=lambda item: item["name"])
    return {
        "tool_count": len(canonical),
        "tool_names": [item["name"] for item in canonical],
        "tools": canonical,
        "schema_hash": _sha(canonical),
    }


def _flatten_capabilities(value: Any, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if child is True:
                found.add(name)
            elif isinstance(child, (dict, list, tuple, set)):
                found.update(_flatten_capabilities(child, name))
            elif isinstance(child, str) and child:
                found.add(f"{name}:{child}")
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            if isinstance(child, str) and child:
                found.add(child)
            else:
                found.update(_flatten_capabilities(child, prefix))
    return found


def _client_capabilities(value: dict[str, Any] | list[str] | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, dict):
        return _flatten_capabilities(value)
    if isinstance(value, list):
        return {str(item) for item in value if str(item).strip()}
    raise TypeError("client_capabilities must be an object or list")


class CapabilityService:
    """Build identity, schema hashing and capability negotiation."""

    def __init__(
        self,
        config: MCPConfig,
        mcp: Any,
        *,
        browser: Any | None = None,
    ) -> None:
        self.config = config
        self.mcp = mcp
        self.browser = browser
        self.project_root = Path(__file__).resolve().parents[2]
        self.build_identity = server_build_identity(self.project_root)

    def update_config(self, config: MCPConfig) -> None:
        self.config = config

    def schema(self) -> dict[str, Any]:
        return tool_schema_document(self.mcp)

    def server_capabilities(self) -> dict[str, Any]:
        surfaces = sorted(self.config.enabled_surfaces)
        return {
            "durable_run": True,
            "durable_operation": True,
            "idempotency": True,
            "operation_status": True,
            "operation_progress": True,
            "operation_wait": True,
            "readiness": True,
            "event_sourcing": True,
            "control_plane": True,
            "shared_context": True,
            "typed_context_events": True,
            "context_cursors": True,
            "context_subscriptions": True,
            "context_messages": True,
            "context_grants": True,
            "context_transport_optional": True,
            "shared_context_bridge": True,
            "claims_bus": True,
            "dag_resource_locks": True,
            "task_progress_heartbeat": True,
            "timeout_uncertain_semantics": True,
            "checkpoint": True,
            "reconciliation": True,
            "leases": True,
            "fencing_tokens": True,
            "process_tree": "core" in surfaces,
            "binary_resource": True,
            "image_resource": True,
            "semantic_errors": True,
            "capability_negotiation": True,
            "plugin_build_identity": "browser" in surfaces,
            "invasive_fallback_default": "fail_closed",
            "surfaces": surfaces,
        }

    async def target_manifest(self, target: str | None) -> dict[str, Any]:
        if not target:
            return {
                "target": None,
                "available": True,
                "capabilities": {},
            }
        normalized = target.strip().lower()
        if normalized in {"edge", "browser", "chatgpt"}:
            if self.browser is None:
                return {
                    "target": normalized,
                    "available": False,
                    "error_code": "CAPABILITY_MISSING",
                    "capabilities": {},
                }
            try:
                return await self.browser.capability_manifest()
            except Exception as exc:
                return {
                    "target": normalized,
                    "available": False,
                    "error_code": getattr(exc, "code", "TARGET_UNAVAILABLE"),
                    "error": str(exc)[:500],
                    "capabilities": {},
                }
        return {
            "target": normalized,
            "available": False,
            "error_code": "CAPABILITY_MISSING",
            "capabilities": {},
        }

    async def manifest(self, target: str | None = None) -> dict[str, Any]:
        schema = self.schema()
        build = dict(self.build_identity)
        result: dict[str, Any] = {
            "server": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "capability_version": CAPABILITY_VERSION,
                **build,
            },
            "contract": {
                "schema_hash": schema["schema_hash"],
                "tool_count": schema["tool_count"],
                "tool_names": schema["tool_names"],
                "semantic_error_codes": sorted(SEMANTIC_ERRORS),
            },
            "capabilities": self.server_capabilities(),
            "fallback_policy": {
                "silent_invasive_fallbacks": False,
                "invasive_fallback_requires_opt_in": True,
            },
        }
        if target is not None:
            result["target"] = await self.target_manifest(target)
        return result

    async def negotiate(
        self,
        *,
        client_protocol_version: str | None = None,
        client_schema_hash: str | None = None,
        client_capabilities: dict[str, Any] | list[str] | None = None,
        required_capabilities: list[str] | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        manifest = await self.manifest(target)
        reasons: list[dict[str, Any]] = []

        if (
            client_protocol_version is not None
            and client_protocol_version != PROTOCOL_VERSION
        ):
            reasons.append({
                "code": "PROTOCOL_MISMATCH",
                "message": "client protocol version does not match SENTRA",
                "expected": PROTOCOL_VERSION,
                "actual": client_protocol_version,
            })

        expected_schema = manifest["contract"]["schema_hash"]
        if client_schema_hash is not None and client_schema_hash != expected_schema:
            reasons.append({
                "code": "SCHEMA_MISMATCH",
                "message": "client tool schema does not match SENTRA",
                "expected": expected_schema,
                "actual": client_schema_hash,
            })

        available = _flatten_capabilities(manifest["capabilities"])
        target_manifest = manifest.get("target")
        if isinstance(target_manifest, dict):
            available.update(_flatten_capabilities(target_manifest.get("capabilities", {})))
            if target_manifest.get("available") is False:
                reasons.append({
                    "code": str(target_manifest.get("error_code") or "CAPABILITY_MISSING"),
                    "message": str(
                        target_manifest.get("error")
                        or "requested target is not available"
                    ),
                    "target": target_manifest.get("target"),
                })

        required = {
            str(item).strip()
            for item in (required_capabilities or [])
            if str(item).strip()
        }
        missing = sorted(item for item in required if item not in available)
        if missing:
            reasons.append({
                "code": "CAPABILITY_MISSING",
                "message": "required SENTRA capabilities are unavailable",
                "missing": missing,
            })

        client = _client_capabilities(client_capabilities)
        if client:
            negotiated = sorted(available & client)
        else:
            negotiated = sorted(available)

        return {
            "compatible": not reasons,
            "manifest": manifest,
            "negotiated_capabilities": negotiated,
            "reasons": reasons,
        }
