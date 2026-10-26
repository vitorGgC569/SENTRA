"""Explicit reinstall recovery. Preserve data; never stop an active process."""
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
import shutil

from .product import ProductSettings
from .windows_paths import filesystem_path, resolved_path


def _disk(path):
    return Path(filesystem_path(path, resolve=False))


class InstallationRecoveryError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def validate_clean_destination(destination, state):
    original = Path(destination).absolute()
    root = resolved_path(original)
    protected = {Path.home().resolve(), Path(root.anchor)}
    for name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"):
        if os.environ.get(name):
            protected.add(Path(os.environ[name]).resolve())
    protected.update((Path.home() / name).resolve() for name in ("Desktop", "Documents", "Downloads"))
    system = Path(os.environ.get("SystemRoot", "/__sentra_no_system__")).resolve()
    if (root in protected or root.is_relative_to(system) or Path.cwd().resolve().is_relative_to(root)
            or len(root.parts) < 3 or _disk(original).is_symlink()
            or _disk(original).is_junction() or root == resolved_path(Path(state))
            or _disk(root / ".git").exists()):
        raise InstallationRecoveryError("unsafe_clean_destination")
    # A reparse point in a parent must not redirect a user-selected destination.
    if any(_disk(p).is_symlink() or _disk(p).is_junction() for p in original.parents):
        raise InstallationRecoveryError("unsafe_clean_destination")
    return root


def _relative_name(name):
    if not isinstance(name, str) or not name or '\x00' in name:
        raise InstallationRecoveryError('unsafe_clean_destination')
    path = Path(name)
    if not path.parts or path.is_absolute() or path.anchor or any(part in ('..', '.') or ':' in part for part in path.parts):
        raise InstallationRecoveryError('unsafe_clean_destination')
    return path


def _assert_unlinked(root, relative):
    path = root
    for part in relative.parts:
        path = path / part
        if _disk(path).is_symlink() or _disk(path).is_junction():
            raise InstallationRecoveryError('unsafe_clean_destination')
    if not resolved_path(path).is_relative_to(root):
        raise InstallationRecoveryError('unsafe_clean_destination')
    return path


def prepare_clean_install(destination, state, products, *, incoming=None, on_backup=None):
    root = validate_clean_destination(destination, state)
    if not _disk(root).exists() or not any(_disk(root).iterdir()):
        return {"requested": True, "previous_components": False}
    from .app_exit_update import assert_installation_offline
    assert_installation_offline(root)
    state = resolved_path(Path(state))
    marker = root / ".sentra-install.json"
    try:
        old_marker = json.loads(_disk(marker).read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        old_marker = {}
    recognized = isinstance(old_marker, dict) and old_marker.get('product') == 'SENTRA Desktop'
    identity = old_marker.get("installation_id") if recognized else None
    if not isinstance(identity, str) or not 1 <= len(identity) <= 128:
        identity = uuid.uuid4().hex
    # The old marker records individual files. A familiar directory name is
    # not proof that every file beneath it belongs to SENTRA.
    recorded = old_marker.get('owned_files', []) if recognized else []
    if not isinstance(recorded, list):
        raise InstallationRecoveryError('unsafe_clean_destination')
    known_roots = {name.casefold() for name in products} | {
        'sentra-installer.exe', 'tunnel-client.exe', 'runtime-components.json',
        'web-models', 'sentra-electron', 'sentra-mobile', 'sentra-terminal',
        'runtime', 'browser-enrollment', 'edge_extension', 'licenses', 'docs',
    }
    known_roots.update(('_runtime_' + Path(name).stem).casefold() for name in (*products, 'sentra-installer.exe'))
    owned = {}
    for name in recorded:
        relative = _relative_name(name)
        if relative.parts[0].casefold() not in known_roots:
            continue  # Never claim projects, state, launcher receipts or other user data.
        target = _assert_unlinked(root, relative)
        if state == target or state.is_relative_to(target):
            raise InstallationRecoveryError('unsafe_clean_destination')
        if _disk(target).exists():
            if not _disk(target).is_file():
                raise InstallationRecoveryError('unsafe_clean_destination')
            owned[os.path.normcase(str(relative))] = relative
    # Refuse before moving anything if a new payload file would overwrite an
    # existing file whose ownership is not established by the old marker.
    for name in (incoming if incoming is not None else products):
        relative = _relative_name(name)
        target = _assert_unlinked(root, relative)
        if target == state or target.is_relative_to(state):
            raise InstallationRecoveryError('unsafe_clean_destination')
        if _disk(target).exists() and os.path.normcase(str(relative)) not in owned:
            raise InstallationRecoveryError('unowned_clean_conflict')
    targets = sorted(owned.values(), key=lambda path: str(path).casefold())
    if _disk(marker).exists():
        if _disk(marker).is_symlink() or _disk(marker).is_junction() or not _disk(marker).is_file():
            raise InstallationRecoveryError('unsafe_clean_destination')
        targets.insert(0, Path(marker.name))
    backup_disk = Path(tempfile.mkdtemp(prefix=".sentra-clean-", dir=_disk(root.parent)))
    backup = resolved_path(backup_disk)
    moved = []
    pending = root / (".sentra-install.clean-" + uuid.uuid4().hex + ".tmp")
    try:
        # Persist the complete plan and the backup path before the first move.
        # On interruption the backup itself shows which planned moves happened.
        with _disk(backup / 'clean-install.json').open('x', encoding='utf-8') as stream:
            json.dump({'schema': 2, 'install_dir': str(root),
                       'components': [p.as_posix() for p in targets], 'created_at': time.time()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        if on_backup is not None:
            on_backup({"requested": True, "previous_components": bool(targets), "backup": str(backup)})
        for relative in targets:
            target = _assert_unlinked(root, relative)
            dest = backup / relative
            _disk(dest.parent).mkdir(parents=True, exist_ok=True)
            _disk(target).rename(_disk(dest))
            moved.append(relative)
        # Claim only the new product files. Unrelated files, state, projects,
        # browser profiles and the desktop-launcher ownership receipt stay put.
        _disk(pending).write_text(json.dumps({"product": "SENTRA Desktop", "installation_id": identity,
                                      "owned_files": [], "installed_at": time.time()}), encoding="utf-8")
        if os.name == "nt":
            _disk(pending).rename(_disk(marker))
        else:
            os.link(_disk(pending), _disk(marker))
    except BaseException:
        for name in reversed(moved):
            target = root / name
            if not _disk(target).exists():
                _disk(target.parent).mkdir(parents=True, exist_ok=True)
                _disk(backup / name).rename(_disk(target))
        raise
    finally:
        _disk(pending).unlink(missing_ok=True)
    return {"requested": True, "previous_components": bool(moved), "backup": str(backup)}


def planned_clean_targets(source, extension, docs, products, tunnel_archive=None, installer_binary=None,
                          include_registration=True):
    """Map verified payload files to installed paths for conflict detection."""
    from .installer_preflight import payload_files
    targets = set(products) | {'tunnel-client.exe'}
    for name, _ in payload_files(source, extension, docs, products):
        if name.startswith('payload/prerequisites/browser-enrollment/'):
            name = 'browser-enrollment/' + name.removeprefix('payload/prerequisites/browser-enrollment/')
        elif name.startswith('payload/prerequisites/codex-registration/'):
            name = 'runtime/codex-registration/' + name.removeprefix('payload/prerequisites/codex-registration/')
        elif name.startswith('payload/prerequisites/'):
            continue
        elif name.startswith('payload/'):
            name = name.removeprefix('payload/')
        targets.add(name)
    if not (Path(source) / 'prerequisites' / 'browser-enrollment').is_dir() and installer_binary is None:
        # The development path generates these files instead of copying the
        # packaged extension. Reserve their exact targets before any move.
        for family in ('chromium', 'firefox'):
            targets.update(f'browser-enrollment/{family}/{name}' for name in ('manifest.json', 'background.js', 'dom.js'))
        targets.update({'browser-enrollment/firefox-signed.xpi', 'browser-enrollment/distribution.json'})
    if include_registration:
        targets.update(f'browser-enrollment/native-{name}.json' for name in ('config', 'chromium', 'firefox'))
    if installer_binary is not None:
        targets.add('sentra-installer.exe')
        support = Path(installer_binary).parent / '_runtime_sentra-installer'
        if support.is_dir():
            targets.update((Path(support.name) / path.relative_to(support)).as_posix()
                           for path in support.rglob('*') if path.is_file())
    if tunnel_archive:
        import zipfile
        with zipfile.ZipFile(tunnel_archive) as archive:
            for item in archive.infolist():
                name = Path(item.filename).name
                if name.upper() in {'LICENSE', 'NOTICE'} or name.endswith(('.spdx.json', '-licenses.txt')):
                    targets.add((Path('licenses') / 'tunnel-client' / name).as_posix())
    return sorted(targets)


def restore_missing_clean_backup(destination, backup):
    """Restore missing old files only; never replace new or unknown bytes."""
    root = resolved_path(Path(destination))
    folder = resolved_path(Path(backup))
    if folder.parent != root.parent or not folder.name.startswith('.sentra-clean-'):
        raise InstallationRecoveryError('unsafe_clean_destination')
    manifest = json.loads(_disk(folder / 'clean-install.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 2 or manifest.get('install_dir') != str(root):
        raise InstallationRecoveryError('unsafe_clean_destination')
    restored = 0
    conflicts = 0
    for name in manifest.get('components', []):
        relative = _relative_name(name)
        source = _assert_unlinked(folder, relative)
        if not _disk(source).is_file():
            continue  # A planned move may not have happened before interruption.
        target = _assert_unlinked(root, relative)
        _disk(target.parent).mkdir(parents=True, exist_ok=True)
        # Copy into the same directory first. A disk error or interruption
        # must not leave a partial file at the original installation path.
        pending = target.with_name('.sentra-restore-' + uuid.uuid4().hex + '.tmp')
        try:
            with _disk(source).open('rb') as src, _disk(pending).open('xb') as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            shutil.copystat(_disk(source), _disk(pending))
            # A hard link creates the final name atomically and fails if a
            # new file appeared while the backup was being copied.
            os.link(_disk(pending), _disk(target))
            restored += 1
        except FileExistsError:
            conflicts += 1
        finally:
            _disk(pending).unlink(missing_ok=True)
    return {'restored_missing': restored, 'conflicts': conflicts,
            'manual_recovery_required': conflicts > 0}


def record_clean_recovery(state, destination, result, status):
    """Keep one durable record per backup, even when another install starts."""
    root = resolved_path(Path(destination))
    backup = resolved_path(Path(result['backup']))
    if backup.parent != root.parent or not backup.name.startswith('.sentra-clean-'):
        raise InstallationRecoveryError('unsafe_clean_destination')
    directory = Path(state) / 'installer-clean-recoveries'
    if _disk(directory).is_symlink() or _disk(directory).is_junction():
        raise InstallationRecoveryError('unsafe_clean_destination')
    _disk(directory).mkdir(parents=True, exist_ok=True)
    target = directory / (backup.name + '.json')
    if _disk(target).is_symlink() or _disk(target).is_junction():
        raise InstallationRecoveryError('unsafe_clean_destination')
    if _disk(target).exists():
        previous = json.loads(_disk(target).read_text(encoding='utf-8'))
        if previous.get('install_dir') != str(root) or previous.get('backup_directory') != str(backup):
            raise InstallationRecoveryError('unsafe_clean_destination')
    record = {'schema': 1, 'install_dir': str(root), 'backup_directory': str(backup),
              'status': status, 'updated_at': time.time(), 'recovery': result.get('recovery')}
    pending = directory / (target.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with _disk(pending).open('x', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        _disk(pending).replace(_disk(target))
    finally:
        _disk(pending).unlink(missing_ok=True)
    return target


def recover_interrupted_clean_installs(state, destination):
    """Reconcile pre-move receipts left by an interrupted installer.

    A prepared receipt is durable before the first move. Restore only missing
    bytes and stop if anything has since occupied an old path; never begin a
    second installation on top of an uncertain partial replacement.
    """
    root = resolved_path(Path(destination))
    directory = Path(state) / 'installer-clean-recoveries'
    if not _disk(directory).exists():
        return []
    if _disk(directory).is_symlink() or _disk(directory).is_junction() or not _disk(directory).is_dir():
        raise InstallationRecoveryError('unsafe_clean_destination')
    pending = []
    for receipt in _disk(directory).glob('.sentra-clean-*.json'):
        if receipt.is_symlink() or receipt.is_junction() or not receipt.is_file():
            raise InstallationRecoveryError('unsafe_clean_destination')
        try:
            record = json.loads(receipt.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            raise InstallationRecoveryError('unsafe_clean_destination') from None
        if not isinstance(record, dict) or record.get('schema') != 1:
            raise InstallationRecoveryError('unsafe_clean_destination')
        if record.get('recovery') is not None and not isinstance(record['recovery'], dict):
            raise InstallationRecoveryError('unsafe_clean_destination')
        needs_recovery = (record.get('status') in ('prepared', 'interrupted_manual')
                          or (record.get('status') == 'failed'
                              and (record.get('recovery') or {}).get('manual_recovery_required') is True))
        if record.get('install_dir') == str(root) and needs_recovery:
            pending.append(record)
    if not pending:
        return []
    if len(pending) != 1:
        # Different interrupted generations cannot safely be merged by guessing
        # their order. Keep every backup and ask for explicit recovery.
        result = {'requested': True, 'backup': pending[0].get('backup_directory'),
                  'recovery': {'manual_recovery_required': True}}
        error = InstallationRecoveryError('interrupted_clean_recovery')
        error._sentra_clean_install = result
        raise error
    from .app_exit_update import assert_installation_offline
    assert_installation_offline(root)
    recovered = []
    for record in pending:
        result = {'requested': True, 'previous_components': True,
                  'backup': record.get('backup_directory')}
        try:
            result['recovery'] = restore_missing_clean_backup(root, result['backup'])
        except Exception as exc:
            result['recovery'] = {'manual_recovery_required': True}
            error = InstallationRecoveryError('interrupted_clean_recovery')
            error._sentra_clean_install = result
            raise error from exc
        record_clean_recovery(state, root, result, 'interrupted_recovered'
                              if not result['recovery']['manual_recovery_required'] else 'interrupted_manual')
        recovered.append(result)
        if result['recovery']['manual_recovery_required']:
            error = InstallationRecoveryError('interrupted_clean_recovery')
            error._sentra_clean_install = result
            raise error
    return recovered


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
