"""Explicit reinstall recovery. Preserve data; never stop an active process."""
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from .product import ProductSettings


class InstallationRecoveryError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def validate_clean_destination(destination, state):
    original = Path(destination).absolute()
    root = original.resolve()
    protected = {Path.home().resolve(), Path(root.anchor)}
    for name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"):
        if os.environ.get(name):
            protected.add(Path(os.environ[name]).resolve())
    protected.update((Path.home() / name).resolve() for name in ("Desktop", "Documents", "Downloads"))
    system = Path(os.environ.get("SystemRoot", "/__sentra_no_system__")).resolve()
    if (root in protected or root.is_relative_to(system) or Path.cwd().resolve().is_relative_to(root)
            or len(root.parts) < 3 or original.is_symlink()
            or original.is_junction() or root == Path(state).resolve()
            or (root / ".git").exists()):
        raise InstallationRecoveryError("unsafe_clean_destination")
    # A reparse point in a parent must not redirect a user-selected destination.
    if any(p.is_symlink() or p.is_junction() for p in original.parents):
        raise InstallationRecoveryError("unsafe_clean_destination")
    return root


def prepare_clean_install(destination, state, products):
    root = validate_clean_destination(destination, state)
    if not root.exists() or not any(root.iterdir()):
        return {"requested": True, "previous_components": False}
    from .app_exit_update import assert_installation_offline
    assert_installation_offline(root)
    state = Path(state).resolve()
    marker = root / ".sentra-install.json"
    try:
        old_marker = json.loads(marker.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        old_marker = {}
    identity = old_marker.get("installation_id") if isinstance(old_marker, dict) and old_marker.get("product") == "SENTRA Desktop" else None
    if not isinstance(identity, str) or not 1 <= len(identity) <= 128:
        identity = uuid.uuid4().hex
    names = set(products) | {"sentra-installer.exe", "tunnel-client.exe", ".sentra-install.json"}
    names.update("_runtime_" + Path(name).stem for name in (*products, "sentra-installer.exe"))
    names.update({"web-models", "sentra-electron", "sentra-mobile", "sentra-terminal",
                  "runtime", "prerequisites", "browser-enrollment", "licenses", "docs"})
    targets = []
    for name in sorted(names):
        target = root / name
        if target.is_symlink() or target.is_junction():
            raise InstallationRecoveryError("unsafe_clean_destination")
        if target.exists():
            if state.is_relative_to(target):
                raise InstallationRecoveryError("unsafe_clean_destination")
            targets.append(target)
    backup = Path(tempfile.mkdtemp(prefix=".sentra-clean-", dir=root.parent))
    moved = []
    pending = root / (".sentra-install.clean-" + uuid.uuid4().hex + ".tmp")
    try:
        for target in targets:
            assert target.parent == root and target.resolve().is_relative_to(root)
            target.rename(backup / target.name)
            moved.append(target.name)
        # Claim only the new product files. Unrelated files, state, projects,
        # browser profiles and the desktop-launcher ownership receipt stay put.
        (backup / "clean-install.json").write_text(json.dumps({"schema": 1, "install_dir": str(root),
            "components": moved, "created_at": time.time()}), encoding="utf-8")
        pending.write_text(json.dumps({"product": "SENTRA Desktop", "installation_id": identity,
                                      "owned_files": [], "installed_at": time.time()}), encoding="utf-8")
        if os.name == "nt":
            pending.rename(marker)
        else:
            os.link(pending, marker)
    except BaseException:
        for name in reversed(moved):
            target = root / name
            if not target.exists():
                (backup / name).rename(target)
        raise
    finally:
        pending.unlink(missing_ok=True)
    return {"requested": True, "previous_components": bool(moved), "backup": str(backup)}


def load_install_settings(path, *, repair_damaged=False):
    """A reset requires the owner's explicit setup choice and uses Safe mode."""
    path = Path(path)
    try:
        value = ProductSettings.load(path, migrate_legacy_web=True)
        if (value.profile not in {"Safe", "Developer", "Full"}
                or type(value.mcp_port) is not int or not 1024 <= value.mcp_port <= 65535
                or type(value.relay_port) is not int or not 1024 <= value.relay_port <= 65535
                or value.mcp_port == value.relay_port or not isinstance(value.allowed_roots, list)
                or not isinstance(value.workspace_permissions, dict) or not isinstance(value.tool_allowlist, list)):
            raise ValueError("invalid local settings")
        if (any(not isinstance(root, str) for root in value.allowed_roots)
                or any(not isinstance(tool, str) for tool in value.tool_allowlist)
                or any(type(getattr(value, name)) is not bool for name in (
                    "autostart_desktop", "autostart_mcp", "autostart_relay", "autostart_tunnel", "autostart_agent", "auto_update"))):
            raise ValueError("invalid local settings types")
        return value, None
    except (ValueError, TypeError):
        if not repair_damaged:
            raise InstallationRecoveryError("settings_invalid") from None
    backup = path.with_name(path.stem + ".damaged-" + uuid.uuid4().hex + path.suffix)
    path.rename(backup)  # Same-directory rename retains the original file/ACL.
    value = ProductSettings(profile="Safe", access_scope="workspace")
    try:
        value.save(path)
    except BaseException:
        if not path.exists():
            backup.rename(path)
        raise
    return value, {"recovered": True, "profile": "Safe", "backup": backup.name}
