"""Explicit bounded project snapshots, copied only into the bound guest.

No shared folders, host root, implicit synchronization or guest-selected host
paths. Archives have normalized metadata and reject links/reparse points.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import stat
import tarfile
import uuid

from .rpa import effect_checkpoint
from .virtualbox_installation import verify_guest

EXCLUDED_DIRS = frozenset({'.git', '.sentra', '.ssh', '.gnupg', '.aws', '.azure',
    '.codex', '.claude', '.tmp', '__pycache__', '.pytest_cache', '.mypy_cache',
    'browser_profiles', 'node_modules', '.venv', 'venv'})
EXCLUDED_NAMES = frozenset({'auth.json', 'credentials', 'credentials.json',
    'secrets.json', 'id_rsa', 'id_ed25519', 'id_ecdsa', '.npmrc', '.pypirc', '.netrc'})


def sensitive(name):
    value = name.casefold()
    return (value in EXCLUDED_NAMES or value.startswith('.env')
        or value.endswith(('.pem', '.key', '.p12', '.pfx', '.kdbx')))


def snapshot_project(root, target, *, relative_path='.', max_files=100000, max_bytes=2*1024**3):
    root, target = Path(root).resolve(strict=True), Path(target)
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError('selected project directory required; host root prohibited')
    relative = Path(relative_path)
    if relative.is_absolute() or '..' in relative.parts or any(p.casefold() in EXCLUDED_DIRS or sensitive(p) for p in relative.parts):
        raise ValueError('project-relative non-sensitive directory required')
    selected = root / relative
    # Reject every reparse component before following its target.
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink() or getattr(cursor, 'is_junction', lambda:False)():
            raise ValueError('linked project selection prohibited')
    selected = selected.resolve(strict=True)
    if not selected.is_relative_to(root):
        raise ValueError('project selection escapes root')
    if selected.is_file():
        return _snapshot_file(selected, target)
    if not selected.is_dir():
        raise ValueError('project selection escapes root')
    manifest, skipped, size = [], [], 0
    for directory, dirs, files in os.walk(selected, followlinks=False):
        current = Path(directory)
        accepted = []
        for name in sorted(dirs):
            item = current/name
            if (name.casefold() in EXCLUDED_DIRS or sensitive(name) or item.is_symlink()
                    or getattr(item, 'is_junction', lambda:False)()):
                skipped.append(item.relative_to(selected).as_posix() + '/')
            else:
                accepted.append(name)
        dirs[:] = accepted
        for name in sorted(files):
            item = current/name
            status = item.lstat()
            if (sensitive(name) or not stat.S_ISREG(status.st_mode) or status.st_nlink > 1
                    or getattr(status, 'st_file_attributes', 0) & 0x400
                    or not item.resolve().is_relative_to(selected)):
                skipped.append(item.relative_to(selected).as_posix())
                continue
            size += status.st_size
            if len(manifest) >= max_files or size > max_bytes:
                raise ValueError('project snapshot exceeds file or byte budget')
            manifest.append((item.relative_to(selected).as_posix(), item, status))
    if target.resolve().is_relative_to(selected):
        raise ValueError('snapshot output must be outside exported directory')
    effect_checkpoint()
    with target.open('xb') as output, tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for name, item, before in sorted(manifest):
            effect_checkpoint()
            with item.open('rb') as source:
                actual = os.fstat(source.fileno())
                if (actual.st_ino, actual.st_size, actual.st_mtime_ns) != (before.st_ino, before.st_size, before.st_mtime_ns):
                    raise ValueError('project changed during snapshot')
                header = tarfile.TarInfo(name)
                header.size = before.st_size
                header.mode = 0o755 if before.st_mode & 0o111 else 0o644
                archive.addfile(header, source)
                after = os.fstat(source.fileno())
                if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                    raise ValueError('project changed during snapshot')
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256':digest, 'files':len(manifest), 'source_bytes':size,
        'excluded_count':len(skipped), 'excluded_paths':skipped[:200],
        'entry_kind':'directory', 'direction':'host_project_to_owned_guest'}


def _snapshot_file(selected, target):
    """One regular file. Secrets, links and reparse points stay on the host."""
    name = selected.name
    if sensitive(name):
        raise ValueError('sensitive file is not copied into the guest')
    status = selected.lstat()
    if (selected.is_symlink() or getattr(selected, 'is_junction', lambda: False)()
            or not stat.S_ISREG(status.st_mode) or status.st_nlink > 1
            or getattr(status, 'st_file_attributes', 0) & 0x400):
        raise ValueError('only a regular file can be copied into the guest')
    if status.st_size > 2 * 1024**3:
        raise ValueError('project snapshot exceeds file or byte budget')
    effect_checkpoint()
    with target.open('xb') as output, tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT) as archive:
        effect_checkpoint()
        with selected.open('rb') as source:
            actual = os.fstat(source.fileno())
            if (actual.st_ino, actual.st_size, actual.st_mtime_ns) != (status.st_ino, status.st_size, status.st_mtime_ns):
                raise ValueError('project changed during snapshot')
            header = tarfile.TarInfo(name)
            header.size = status.st_size
            header.mode = 0o644
            archive.addfile(header, source)
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256': digest, 'files': 1, 'source_bytes': status.st_size,
        'excluded_count': 0, 'excluded_paths': [],
        'entry_kind': 'file', 'direction': 'host_project_to_owned_guest'}


def _output_exposes_credential(output, cfg):
    secret = cfg.get('password') if isinstance(cfg, dict) else None
    return isinstance(output, str) and isinstance(secret, str) and len(secret) >= 8 and secret in output


def _guest_account(cfg):
    """The Dot VM account. The default install user remains sentra."""
    username = cfg.get('username') if isinstance(cfg, dict) else None
    if not isinstance(username, str) or not username.strip():
        return 'sentra'
    username = username.strip()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9._-]{0,31}', username) or '..' in username:
        raise ValueError('guest account name is not usable')
    return username


def _guest_import_parent(cfg):
    account = _guest_account(cfg)
    if cfg.get('os_family') == 'windows':
        return 'C:\\Users\\' + account + '\\Imports'
    return '/home/' + account + '/Imports'


def _import_folder(cfg):
    """Import ledger for this Dot VM. A path name cannot leave its folder."""
    name = cfg.get('name') if isinstance(cfg, dict) else None
    base = cfg.get('base_folder') if isinstance(cfg, dict) else None
    if (not isinstance(name, str) or '..' in name
            or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,80}', name) is None):
        raise ValueError('vm name is not a hypervisor token')
    if not isinstance(base, str) or '\0' in base or not Path(base).is_absolute():
        raise ValueError('vm folder is not a host path')
    root = Path(base).resolve()
    home = (root / name).resolve()
    folder = (home / 'imports').resolve()
    if not home.is_relative_to(root) or not folder.is_relative_to(home):
        raise ValueError('vm name is not a hypervisor token')
    return folder


def _import_key(request_key):
    if request_key is None:
        return None
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{8,128}', request_key):
        raise ValueError('invalid import request key')
    return request_key


def resolve_import_root(workspace_root, host_folder):
    """Bound project is the permission boundary. A Windows folder must be named."""
    root = Path(workspace_root).resolve(strict=True)
    if host_folder is None:
        return root, 'bound_project_relative'
    if not isinstance(host_folder, str) or not host_folder.strip():
        raise ValueError('explicit absolute host folder required')
    selected = Path(host_folder)
    if not selected.is_absolute():
        raise ValueError('explicit absolute host folder required')
    if selected == Path(selected.anchor):
        raise ValueError('host root prohibited')
    cursor = Path(selected.anchor)
    for part in selected.parts[1:]:
        cursor = cursor / part
        if cursor.exists() and (cursor.is_symlink() or getattr(cursor, 'is_junction', lambda: False)()):
            raise ValueError('linked host folder prohibited')
    selected = selected.resolve(strict=True)
    if not selected.is_dir() or selected == Path(selected.anchor) or not selected.is_relative_to(root):
        raise ValueError('selected folder is outside the bound project')
    relative = selected.relative_to(root)
    if any(part.casefold() in EXCLUDED_DIRS or sensitive(part) for part in relative.parts):
        raise ValueError('sensitive host folder prohibited')
    return selected, 'explicit_host_folder'


def _receipt_matches(saved, *, request_key, host_folder, relative_path):
    return (saved.get('request_key') == request_key and saved.get('host_folder') == host_folder
        and saved.get('relative_path') == relative_path and saved.get('receipt_state') == 'SUCCEEDED')


def _same_uncertain_import(ledger, *, request_key, vm_id):
    """The same import can be finished. A different key must not start another copy."""
    if request_key is None or not ledger.is_dir():
        return False
    intents = list(ledger.glob('*.intent.json'))
    if len(intents) != 1:
        return False
    try:
        pending = json.loads(intents[0].read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return (pending.get('phase') == 'uncertain'
        and pending.get('request_key') == request_key
        and pending.get('vm_id') == vm_id)


def import_project(client, binding, cfg, *, relative_path='.', host_folder=None, request_key=None,
                   guest_executor=None):
    if not binding.workspace_root:
        raise ValueError('host-bound project root required')
    if not isinstance(relative_path, str):
        raise ValueError('project-relative directory required')
    _guest_account(cfg)
    key = _import_key(request_key)
    selected, selection = resolve_import_root(binding.workspace_root, host_folder)
    stored_folder = None if host_folder is None else str(selected)
    folder = _import_folder(cfg)
    ledger = folder / 'ledger'
    if key:
        receipt_path = ledger / (key + '.receipt.json')
        if receipt_path.is_file():
            saved = json.loads(receipt_path.read_text(encoding='utf-8'))
            if not _receipt_matches(saved, request_key=request_key, host_folder=stored_folder, relative_path=relative_path):
                raise ValueError('duplicate import request was not replayed')
            return {**saved, 'replayed':True, 'physical_effects_performed':False}
    if ledger.is_dir() and any(ledger.glob('*.intent.json')):
        if _same_uncertain_import(ledger, request_key=request_key, vm_id=binding.vm_id):
            return reconcile_uncertain_import(client, binding, cfg)
        raise ValueError('prior import is uncertain and was not replayed')
    orphans = list(folder.glob('*.tar')) if folder.is_dir() else []
    if key and any(path.stem == key for path in orphans):
        raise ValueError('prior import is uncertain and was not replayed')
    verified = verify_guest(client, binding, cfg)
    if not verified.get('installed_os_verified'):
        raise ValueError('authenticated persistent guest required before importing project')
    effect_checkpoint()
    folder.mkdir(exist_ok=True)
    ledger.mkdir(exist_ok=True)
    if key:
        receipt_path = ledger / (key + '.receipt.json')
        if receipt_path.is_file():
            saved = json.loads(receipt_path.read_text(encoding='utf-8'))
            if not _receipt_matches(saved, request_key=request_key, host_folder=stored_folder, relative_path=relative_path):
                raise ValueError('duplicate import request was not replayed')
            return {**saved, 'replayed':True, 'physical_effects_performed':False}
    if any(ledger.glob('*.intent.json')):
        raise ValueError('prior import is uncertain and was not replayed')
    identity = uuid.uuid4().hex
    archive = folder / (identity + '.tar')
    result = snapshot_project(selected, archive, relative_path=relative_path)
    intent_path = ledger / ((key or identity) + '.intent.json')
    intent = {'request_key':request_key, 'sha256':result['sha256'], 'host_folder':stored_folder,
        'relative_path':relative_path, 'selection':selection, 'vm_id':binding.vm_id, 'phase':'intent',
        'archive':archive.name}
    with intent_path.open('x', encoding='utf-8') as handle:
        json.dump(intent, handle)
    windows = cfg.get('os_family') == 'windows'
    account = _guest_account(cfg)
    parent = _guest_import_parent(cfg)
    destination = parent + ('\\' if windows else '/') + identity
    from sentra_executors.guest_execution import is_proven_guest_executor
    proven = is_proven_guest_executor(guest_executor)
    def guest(command):
        if windows:
            return client.run('guestcontrol', binding.vm_id, 'run', '--exe',
                r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe', '--username', account,
                '--passwordfile', 'stdin', '--wait-stdout', '--wait-stderr', '--timeout', 120000,
                '--', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command,
                password=cfg['password'], timeout=130)
        return client.run('guestcontrol', binding.vm_id, 'run', '--exe', '/bin/sh', '--username', account,
            '--passwordfile', 'stdin', '--wait-stdout', '--wait-stderr', '--timeout', 120000,
            '--', '-c', command, password=cfg['password'], timeout=130)
    try:
        if proven:
            proof = guest_executor.execute({
                'action': 'project.import', 'placement': 'guest', 'sha256': result['sha256'],
                'vm_id': binding.vm_id, 'guest_path': destination + ('\\project' if windows else '/project'),
                'archive': str(archive), 'relative_path': relative_path,
            })
            exit_code = proof.get('exit_code') if isinstance(proof, dict) else None
            if (not isinstance(proof, dict) or proof.get('copied') is not True
                    or proof.get('sha256') != result['sha256']
                    or proof.get('execution_surface') != 'guest'
                    or proof.get('host_subprocess') is True
                    or proof.get('claims_guest_execution') is not True
                    or proof.get('execution_uncertain') is True
                    or type(exit_code) is not int or exit_code != 0):
                raise RuntimeError('guest import completion unconfirmed; do not retry automatically')
        else:
            # copyto --target-directory is the guest file path. If that path is
            # an existing directory, this VirtualBox refuses the copy.
            imported_name = archive.name  # generated UUID + '.tar', never user input
            guest_file = parent + ('\\' if windows else '/') + imported_name
            project = parent + ('\\projects\\' if windows else '/projects/') + identity + ('\\project' if windows else '/project')
            if windows:
                guest(
                    "New-Item -ItemType Directory -Force -Path '" + parent + "' | Out-Null; "
                    "Remove-Item -LiteralPath '" + guest_file + "' -Force -ErrorAction SilentlyContinue"
                )
            else:
                guest('mkdir -p ' + parent + ' && rm -f ' + guest_file)
            client.run('guestcontrol', binding.vm_id, 'copyto', '--username', account, '--passwordfile', 'stdin',
                '--target-directory', guest_file, str(archive), password=cfg['password'], timeout=600)
            digest = result['sha256']
            if windows:
                output = guest(
                    "$archive = '" + guest_file + "'; "
                    "$hash = (Get-FileHash -Algorithm SHA256 -Path $archive).Hash.ToLower(); "
                    "if ($hash -ne '" + digest + "') { exit 1 }; "
                    "$project = '" + project + "'; "
                    "New-Item -ItemType Directory -Force -Path $project -ErrorAction Stop | Out-Null; "
                    "tar -xf $archive -C $project; "
                    "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; "
                    "Remove-Item -Force $archive; "
                    "Write-Output 'SENTRA_IMPORT_COMPLETE'"
                )
            else:
                output = guest(
                    f'echo "{digest}  {guest_file}" | sha256sum -c - && '
                    f'mkdir -p {project} && '
                    f'tar --no-same-owner -xf {guest_file} -C {project} && '
                    f'rm {guest_file} && echo SENTRA_IMPORT_COMPLETE'
                )
            if _output_exposes_credential(output, cfg):
                raise RuntimeError('guest import output included a credential and was not accepted')
            if 'SENTRA_IMPORT_COMPLETE' not in output:
                raise RuntimeError('guest import completion unconfirmed; do not retry automatically')
    except Exception:
        uncertain = {**intent, 'phase':'uncertain'}
        intent_path.write_text(json.dumps(uncertain), encoding='utf-8')
        raise
    effect_checkpoint()
    archive.unlink()
    receipt = {**result, 'status':'project_imported', 'receipt_state':'SUCCEEDED', 'vm_id':binding.vm_id,
        'guest_path': project if not proven else (destination + ('\\project' if windows else '/project')), 'bidirectional_sync':False, 'selection':selection,
        'host_folder':stored_folder, 'relative_path':relative_path, 'request_key':request_key,
        'replayed':False, 'physical_effects_performed':True,
        'contemporary_guest_copy': True, 'guest_copy_proven': True,
        'claims_guest_execution': True,
        'execution_surface': 'guest',
        'host_subprocess': False,
        'guest_witness': 'injected_executor' if proven else 'guestcontrol_hash'}
    (ledger / ((key or identity) + '.receipt.json')).write_text(json.dumps(receipt), encoding='utf-8')
    intent_path.unlink()
    return receipt


def reconcile_uncertain_import(client, binding, cfg):
    """Finish the one uncertain copy. Does not snapshot the host again."""
    if not binding.workspace_root:
        raise ValueError('host-bound project root required')
    folder = _import_folder(cfg)
    ledger = folder / 'ledger'
    intents = sorted(ledger.glob('*.intent.json')) if ledger.is_dir() else []
    if len(intents) != 1:
        raise ValueError('one uncertain import is required to reconcile')
    intent_path = intents[0]
    intent = json.loads(intent_path.read_text(encoding='utf-8'))
    if intent.get('phase') != 'uncertain' or intent.get('vm_id') != binding.vm_id:
        raise ValueError('uncertain import does not belong to this VM')
    archive = folder / str(intent.get('archive') or '')
    if archive.parent != folder or not archive.is_file():
        raise ValueError('uncertain import archive is missing')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.tar', archive.name) or '..' in archive.name:
        raise ValueError('uncertain import archive name is not usable')
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != intent.get('sha256'):
        raise ValueError('uncertain import archive changed')
    verified = verify_guest(client, binding, cfg)
    if not verified.get('installed_os_verified'):
        raise ValueError('authenticated persistent guest required before importing project')
    identity = archive.stem
    windows = cfg.get('os_family') == 'windows'
    account = _guest_account(cfg)
    parent = _guest_import_parent(cfg)
    imported_name = archive.name
    guest_file = parent + ('\\' if windows else '/') + imported_name
    project = parent + ('\\projects\\' if windows else '/projects/') + identity + ('\\project' if windows else '/project')
    def guest(command):
        if windows:
            return client.run('guestcontrol', binding.vm_id, 'run', '--exe',
                r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe', '--username', account,
                '--passwordfile', 'stdin', '--wait-stdout', '--wait-stderr', '--timeout', 120000,
                '--', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command,
                password=cfg['password'], timeout=130)
        return client.run('guestcontrol', binding.vm_id, 'run', '--exe', '/bin/sh', '--username', account,
            '--passwordfile', 'stdin', '--wait-stdout', '--wait-stderr', '--timeout', 120000,
            '--', '-c', command, password=cfg['password'], timeout=130)
    if windows:
        guest(
            "New-Item -ItemType Directory -Force -Path '" + parent + "' | Out-Null; "
            "Remove-Item -LiteralPath '" + guest_file + "' -Force -ErrorAction SilentlyContinue"
        )
    else:
        guest('mkdir -p ' + parent + ' && rm -f ' + guest_file)
    client.run('guestcontrol', binding.vm_id, 'copyto', '--username', account, '--passwordfile', 'stdin',
        '--target-directory', guest_file, str(archive), password=cfg['password'], timeout=600)
    if windows:
        output = guest(
            "$archive = '" + guest_file + "'; "
            "$hash = (Get-FileHash -Algorithm SHA256 -Path $archive).Hash.ToLower(); "
            "if ($hash -ne '" + digest + "') { exit 1 }; "
            "New-Item -ItemType Directory -Force -Path '" + project + "' -ErrorAction Stop | Out-Null; "
            "tar -xf $archive -C '" + project + "'; "
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; "
            "Remove-Item -Force $archive; "
            "Write-Output 'SENTRA_IMPORT_COMPLETE'"
        )
    else:
        output = guest(
            f'echo "{digest}  {guest_file}" | sha256sum -c - && '
            f'mkdir -p {project} && '
            f'tar --no-same-owner -xf {guest_file} -C {project} && '
            f'rm {guest_file} && echo SENTRA_IMPORT_COMPLETE'
        )
    if _output_exposes_credential(output, cfg):
        raise RuntimeError('guest import output included a credential and was not accepted')
    if 'SENTRA_IMPORT_COMPLETE' not in output:
        raise RuntimeError('guest import completion unconfirmed; do not retry automatically')
    effect_checkpoint()
    archive.unlink()
    receipt = {
        'status': 'project_imported', 'receipt_state': 'SUCCEEDED', 'sha256': digest,
        'vm_id': binding.vm_id, 'guest_path': project,
        'request_key': intent.get('request_key'), 'relative_path': intent.get('relative_path'),
        'host_folder': intent.get('host_folder'), 'selection': intent.get('selection'),
        'replayed': False, 'physical_effects_performed': True, 'reconciled_uncertain': True,
        'guest_copy_proven': True, 'execution_surface': 'guest', 'host_subprocess': False,
        'guest_witness': 'guestcontrol_hash', 'bidirectional_sync': False,
    }
    (ledger / ((intent.get('request_key') or identity) + '.receipt.json')).write_text(
        json.dumps(receipt), encoding='utf-8')
    intent_path.unlink()
    return receipt
