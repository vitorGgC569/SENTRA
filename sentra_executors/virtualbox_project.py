"""Explicit bounded project snapshots, copied only into the bound guest.

No shared folders, host root, implicit synchronization or guest-selected host
paths. Archives have normalized metadata and reject links/reparse points.
"""
from pathlib import Path
import hashlib
import json
import os
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
    if not selected.is_dir() or not selected.is_relative_to(root):
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
        'excluded_count':len(skipped), 'excluded_paths':skipped[:200], 'direction':'host_project_to_owned_guest'}


def import_project(client, binding, cfg, *, relative_path='.'):
    if not binding.workspace_root:
        raise ValueError('host-bound project root required')
    verified = verify_guest(client, binding, cfg)
    if not verified.get('installed_os_verified'):
        raise ValueError('authenticated persistent guest required before importing project')
    folder = Path(cfg['base_folder']) / cfg['name'] / 'imports'
    effect_checkpoint()
    folder.mkdir(exist_ok=True)
    identity = uuid.uuid4().hex
    archive = folder/(identity + '.tar')
    result = snapshot_project(binding.workspace_root, archive, relative_path=relative_path)
    destination = '/home/sentra/Imports/' + identity
    def guest(command):
        return client.run('guestcontrol', binding.vm_id, 'run', '--exe', '/bin/sh', '--username', 'sentra',
            '--passwordfile', 'stdin', '--wait-stdout', '--wait-stderr', '--timeout', 120000,
            '--', '-c', command, password=cfg['password'], timeout=130)
    guest('mkdir -p ' + destination)
    client.run('guestcontrol', binding.vm_id, 'copyto', '--username', 'sentra', '--passwordfile', 'stdin',
        '--target-directory', destination, str(archive), password=cfg['password'], timeout=600)
    digest = result['sha256']
    # copyto --target-directory expects a directory. VirtualBox preserves the
    # local basename; verify/extract that exact file, not a nonexistent name.
    imported_name = archive.name  # generated UUID + '.tar', never user input
    output = guest(f'cd {destination} && echo "{digest}  {imported_name}" | sha256sum -c - && '
        f'mkdir project && tar --no-same-owner -xf {imported_name} -C project && '
        f'rm {imported_name} && echo SENTRA_IMPORT_COMPLETE')
    if 'SENTRA_IMPORT_COMPLETE' not in output:
        raise RuntimeError('guest import completion unconfirmed; do not retry automatically')
    effect_checkpoint()
    archive.unlink()
    return {**result, 'status':'project_imported', 'vm_id':binding.vm_id,
        'guest_path':destination + '/project', 'bidirectional_sync':False}
