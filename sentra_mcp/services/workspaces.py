"""Central allowlisted workspace registry for SENTRA MCP.

The registry separates *configured roots* (operator boot configuration) from
*approved grants* (locally approved at runtime).  Agents may request grants or
removals but cannot approve them through MCP.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from ..audit import AuditLogger
from ..config import MCPConfig

WORKSPACE_PERMISSIONS = frozenset({"read", "write", "execute"})
_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_MAX_TTL_S = 30 * 24 * 3600


def _safe_alias(value: str, fallback: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.-]+", "-", (value or "").strip()).strip("-.")
    if not candidate or not candidate[0].isalnum():
        candidate = fallback
    return candidate[:64]


def _normalize_permissions(values: Iterable[str]) -> tuple[str, ...]:
    permissions = {str(item).strip().lower() for item in values if str(item).strip()}
    unknown = permissions - WORKSPACE_PERMISSIONS
    if unknown:
        raise ValueError("unknown workspace permissions: " + ", ".join(sorted(unknown)))
    if not permissions:
        raise ValueError("at least one workspace permission is required")
    # Writing/executing necessarily requires being able to inspect the selected root.
    if permissions & {"write", "execute"}:
        permissions.add("read")
    return tuple(sorted(permissions))


def _parse_lifetime(value: str, *, owner: str, now: float) -> tuple[str, float | None]:
    raw = (value or "permanent").strip().lower()
    if raw == "permanent":
        return "permanent", None
    if raw == "session":
        if not owner:
            raise ValueError("session-scoped workspaces require an owner identity")
        return "session", None
    match = re.fullmatch(r"(\d+)(m|h|d)", raw)
    if not match:
        raise ValueError("lifetime must be permanent, session, or a bounded value such as 30m, 24h, 7d")
    amount = int(match.group(1))
    unit = {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
    ttl = amount * unit
    if ttl < 60 or ttl > _MAX_TTL_S:
        raise ValueError("workspace TTL must be between 1 minute and 30 days")
    return "ttl", now + ttl


class WorkspaceRegistry:
    """Resolve project aliases/paths through locally approved grants."""

    def __init__(
        self,
        config: MCPConfig,
        audit: AuditLogger | None = None,
        *,
        state_path: Path | None = None,
        clock=time.time,
    ) -> None:
        self.config = config
        self.audit = audit
        self.clock = clock
        self.state_path = Path(
            state_path or (config.state_root / "workspaces.json")
        )
        self._lock = threading.RLock()
        self._cached_mtime_ns: int | None = None
        self._cached_state: dict[str, Any] | None = None

    def update_config(self, config: MCPConfig) -> None:
        with self._lock:
            self.config = config

    def _empty(self) -> dict[str, Any]:
        return {"version": 1, "grants": [], "pending": {}, "history": []}

    def _load(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            try:
                mtime = self.state_path.stat().st_mtime_ns
            except FileNotFoundError:
                self._cached_mtime_ns = None
                self._cached_state = self._empty()
                return json.loads(json.dumps(self._cached_state))
            if not force and self._cached_state is not None and self._cached_mtime_ns == mtime:
                return json.loads(json.dumps(self._cached_state))
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = self._empty()
            if not isinstance(data, dict):
                data = self._empty()
            data.setdefault("version", 1)
            data.setdefault("grants", [])
            data.setdefault("pending", {})
            data.setdefault("history", [])
            if not isinstance(data["grants"], list):
                data["grants"] = []
            if not isinstance(data["pending"], dict):
                data["pending"] = {}
            if not isinstance(data["history"], list):
                data["history"] = []
            self._cached_mtime_ns = mtime
            self._cached_state = data
            return json.loads(json.dumps(data))

    def _save(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            temp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            temp.replace(self.state_path)
            self._cached_state = json.loads(json.dumps(data))
            self._cached_mtime_ns = self.state_path.stat().st_mtime_ns

    def _configured_grants(self) -> list[dict[str, Any]]:
        grants: list[dict[str, Any]] = []
        used_aliases: set[str] = set()
        for index, raw_root in enumerate(self.config.allowed_roots):
            root = Path(raw_root).expanduser().resolve()
            base = "sentra" if index == 0 else _safe_alias(root.name, f"root-{index}")
            alias = base
            counter = 2
            while alias.casefold() in used_aliases:
                alias = f"{base}-{counter}"
                counter += 1
            used_aliases.add(alias.casefold())
            grants.append({
                "workspace_id": f"config:{index}",
                "alias": alias,
                "path": str(root),
                "permissions": ["execute", "read", "write"],
                "scope": "permanent",
                "owner": None,
                "expires_at": None,
                "source": "configured",
                "created_at": 0.0,
                "approved_at": 0.0,
            })
        return grants

    def _active_grants(self, owner: str | None) -> list[dict[str, Any]]:
        now = self.clock()
        configured = self._configured_grants()
        configured_paths = {str(Path(item["path"]).resolve()) for item in configured}
        dynamic: list[dict[str, Any]] = []
        for raw in self._load().get("grants", []):
            if not isinstance(raw, dict):
                continue
            try:
                path = str(Path(str(raw["path"])).expanduser().resolve())
                permissions = list(_normalize_permissions(raw.get("permissions") or []))
            except (KeyError, ValueError, OSError):
                continue
            if path in configured_paths:
                continue
            scope = str(raw.get("scope") or "permanent")
            grant_owner = raw.get("owner")
            expires_at = raw.get("expires_at")
            if scope == "session" and grant_owner != owner:
                continue
            if scope == "ttl" and (not isinstance(expires_at, (int, float)) or expires_at <= now):
                continue
            item = dict(raw)
            item["path"] = path
            item["permissions"] = permissions
            dynamic.append(item)
        return configured + dynamic

    @staticmethod
    def _view(item: dict[str, Any], index: int) -> dict[str, Any]:
        path = Path(str(item["path"]))
        return {
            "id": f"root:{index}",
            "workspace_id": item["workspace_id"],
            "alias": item["alias"],
            "path": str(path),
            "permissions": list(item["permissions"]),
            "scope": item.get("scope", "permanent"),
            "expires_at": item.get("expires_at"),
            "source": item.get("source", "approved"),
            "exists": path.is_dir(),
            "git_repo": (path / ".git").exists() if path.is_dir() else False,
            "default": index == 0,
        }

    def list_workspaces(self, owner: str | None) -> dict[str, Any]:
        grants = self._active_grants(owner)
        items = [self._view(item, index) for index, item in enumerate(grants)]
        return {
            "items": items,
            "workspaces": items,
            "page": {
                "offset": 0,
                "limit": len(items),
                "returned": len(items),
                "total": len(items),
                "next_offset": None,
            },
        }

    def _resolve_item(
        self,
        selector: str | None,
        owner: str | None,
        permission: str,
    ) -> tuple[int, dict[str, Any]]:
        if permission not in WORKSPACE_PERMISSIONS:
            raise ValueError("invalid workspace permission")
        grants = self._active_grants(owner)
        if not grants:
            raise PermissionError("no workspace is available")
        matches: list[tuple[int, dict[str, Any]]] = []
        if selector is None or not str(selector).strip():
            matches = [(0, grants[0])]
        else:
            value = str(selector).strip()
            if value.startswith("root:"):
                try:
                    index = int(value.split(":", 1)[1])
                except ValueError as exc:
                    raise ValueError("workspace root id must be root:<index>") from exc
                if 0 <= index < len(grants):
                    matches = [(index, grants[index])]
            else:
                candidate = Path(value).expanduser()
                resolved = candidate.resolve() if candidate.is_absolute() else None
                folded = value.casefold()
                for index, item in enumerate(grants):
                    if (
                        str(item["workspace_id"]).casefold() == folded
                        or str(item["alias"]).casefold() == folded
                        or (resolved is not None and Path(item["path"]).resolve() == resolved)
                    ):
                        matches.append((index, item))
        if not matches:
            raise PermissionError("workspace is not allowlisted for this session")
        if len(matches) > 1:
            raise ValueError("workspace selector is ambiguous; use root:<index>")
        index, item = matches[0]
        if permission not in set(item["permissions"]):
            raise PermissionError(
                f"workspace '{item['alias']}' does not grant {permission} permission"
            )
        root = Path(str(item["path"]))
        if not root.is_dir():
            raise FileNotFoundError("allowlisted workspace directory does not exist")
        return index, item

    def resolve(
        self,
        selector: str | None,
        owner: str | None,
        permission: str = "read",
    ) -> dict[str, Any]:
        index, item = self._resolve_item(selector, owner, permission)
        return self._view(item, index)

    def resolve_path(
        self,
        path: Path,
        owner: str | None,
        permission: str = "read",
    ) -> dict[str, Any]:
        candidate = path.expanduser().resolve()
        matches: list[tuple[int, dict[str, Any], int]] = []
        for index, item in enumerate(self._active_grants(owner)):
            root = Path(str(item["path"])).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if permission not in set(item["permissions"]):
                continue
            matches.append((index, item, len(root.parts)))
        if not matches:
            raise PermissionError("path is outside workspaces granting the requested permission")
        # Most specific root wins when roots are nested.
        index, item, _ = max(matches, key=lambda value: value[2])
        return self._view(item, index)

    def request_add(
        self,
        *,
        path: str,
        owner: str,
        alias: str | None = None,
        permissions: Iterable[str] = ("read",),
        lifetime: str = "permanent",
    ) -> dict[str, Any]:
        if not isinstance(path, str) or not path.strip() or "\x00" in path:
            raise ValueError("path must be a non-empty absolute directory path")
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            raise ValueError("workspace requests require an absolute path")
        try:
            root = candidate.resolve(strict=True)
        except OSError as exc:
            raise FileNotFoundError("requested workspace does not exist") from exc
        if not root.is_dir():
            raise NotADirectoryError("requested workspace is not a directory")

        normalized = _normalize_permissions(permissions)
        now = self.clock()
        scope, expires_at = _parse_lifetime(lifetime, owner=owner, now=now)

        visible = self._active_grants(owner)
        same_path: tuple[int, dict[str, Any]] | None = None
        for index, item in enumerate(visible):
            if Path(item["path"]).resolve() != root:
                continue
            same_path = (index, item)
            existing_permissions = set(item["permissions"])
            requested_permissions = set(normalized)
            existing_scope = str(item.get("scope") or "permanent")
            existing_expiry = item.get("expires_at")
            scope_satisfies = (
                existing_scope == "permanent"
                or (
                    existing_scope == "session"
                    and scope == "session"
                    and item.get("owner") == owner
                )
                or (
                    existing_scope == "ttl"
                    and scope == "ttl"
                    and isinstance(existing_expiry, (int, float))
                    and isinstance(expires_at, (int, float))
                    and existing_expiry >= expires_at
                )
            )
            if requested_permissions <= existing_permissions and scope_satisfies:
                return {
                    "already_allowed": True,
                    "workspace": self._view(item, index),
                    "approval_required": None,
                }
            break

        existing_item = same_path[1] if same_path is not None else None
        if alias is None:
            alias = (
                str(existing_item["alias"])
                if existing_item is not None and existing_item.get("source") != "configured"
                else _safe_alias(root.name, "workspace")
            )
        if not _ALIAS_RE.fullmatch(alias):
            raise ValueError("alias must be 1..64 characters using letters, numbers, . _ -")

        all_grants = self._configured_grants() + list(self._load().get("grants", []))
        all_aliases = {
            str(item.get("alias", "")).casefold()
            for item in all_grants
            if Path(str(item.get("path", "."))).expanduser().resolve() != root
        }
        if alias.casefold() in all_aliases:
            raise ValueError("workspace alias is already in use")

        request_id = secrets.token_urlsafe(12)
        workspace_id = (
            str(existing_item["workspace_id"])
            if existing_item is not None and existing_item.get("source") != "configured"
            else "ws:" + secrets.token_hex(8)
        )
        grant = {
            "workspace_id": workspace_id,
            "alias": alias,
            "path": str(root),
            "permissions": list(normalized),
            "scope": scope,
            "owner": owner if scope == "session" else None,
            "expires_at": expires_at,
            "source": "approved",
            "created_at": (
                existing_item.get("created_at", now)
                if existing_item is not None
                else now
            ),
            "approved_at": None,
        }
        data = self._load(force=True)
        data["pending"][request_id] = {
            "kind": "add",
            "workspace": grant,
            "requested_by": owner,
            "created_at": now,
            "status": "PENDING",
        }
        self._save(data)
        if self.audit:
            self.audit.emit("workspace.request_add", "pending", {
                "request_id": request_id,
                "alias": alias,
                "path": str(root),
                "permissions": list(normalized),
                "scope": scope,
            })
        return {
            "already_allowed": False,
            "request_id": request_id,
            "requested_workspace": grant,
            "approval_required": {
                "request_id": request_id,
                "command": f"python -m sentra_remote.admin approve-workspace {request_id}",
                "note": "Workspace grants are never self-approved through MCP.",
            },
        }

    def request_remove(self, selector: str, owner: str) -> dict[str, Any]:
        index, item = self._resolve_item(selector, owner, "read")
        if item.get("source") == "configured":
            raise PermissionError("configured workspaces cannot be removed through runtime approval")
        request_id = secrets.token_urlsafe(12)
        now = self.clock()
        data = self._load(force=True)
        data["pending"][request_id] = {
            "kind": "remove",
            "workspace_id": item["workspace_id"],
            "workspace": self._view(item, index),
            "requested_by": owner,
            "created_at": now,
            "status": "PENDING",
        }
        self._save(data)
        if self.audit:
            self.audit.emit("workspace.request_remove", "pending", {
                "request_id": request_id,
                "workspace_id": item["workspace_id"],
                "alias": item["alias"],
            })
        return {
            "request_id": request_id,
            "workspace": self._view(item, index),
            "approval_required": {
                "request_id": request_id,
                "command": f"python -m sentra_remote.admin approve-workspace {request_id}",
                "note": "Workspace removals require local approval.",
            },
        }

    def pending(self) -> dict[str, Any]:
        return {"pending": self._load(force=True).get("pending", {})}

    def approve_local(self, request_id: str) -> dict[str, Any]:
        data = self._load(force=True)
        item = data["pending"].pop(request_id, None)
        if item is None:
            raise FileNotFoundError("pending workspace request not found")
        now = self.clock()
        kind = item.get("kind")
        if kind == "add":
            grant = dict(item["workspace"])
            grant["approved_at"] = now
            grants = [
                existing
                for existing in data["grants"]
                if existing.get("workspace_id") != grant["workspace_id"]
                and str(existing.get("path", "")).casefold() != str(grant["path"]).casefold()
            ]
            grants.append(grant)
            data["grants"] = grants
            result = {"status": "APPROVED", "kind": "add", "workspace": grant}
        elif kind == "remove":
            workspace_id = item.get("workspace_id")
            before = len(data["grants"])
            data["grants"] = [
                grant for grant in data["grants"]
                if grant.get("workspace_id") != workspace_id
            ]
            if len(data["grants"]) == before:
                raise FileNotFoundError("workspace grant no longer exists")
            result = {
                "status": "APPROVED",
                "kind": "remove",
                "workspace_id": workspace_id,
            }
        else:
            raise ValueError("unknown pending workspace request kind")
        data.setdefault("history", []).append({
            "request_id": request_id,
            "approved_at": now,
            **item,
        })
        self._save(data)
        return result

    def reject_local(self, request_id: str) -> dict[str, Any]:
        data = self._load(force=True)
        item = data["pending"].pop(request_id, None)
        if item is None:
            raise FileNotFoundError("pending workspace request not found")
        data.setdefault("history", []).append({
            "request_id": request_id,
            "rejected_at": self.clock(),
            **item,
        })
        self._save(data)
        return {"request_id": request_id, "status": "REJECTED"}
