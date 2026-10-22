"""Apply a backed-up local Canvas/display patch without touching running services.

This is a local development delivery, not a signed installer or a release.
The existing desktop/Web Models processes, runtime and user data stay in place.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from scripts.commander.stage_electron import SURFACE_REQUIRED, _inventory, validate_electron_payload


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def apply_patch(install: Path, payload: Path, backup: Path, state: Path, *, surface_only: bool = False):
    from sentra_canvas.broker import read_endpoint
    install, payload, backup = (Path(p).resolve() for p in (install, payload, backup))
    if not (install / 'sentra-desktop.exe').is_file() or not (install / '.sentra-install.json').is_file():
        raise ValueError('Select an existing SENTRA Commander installation')
    if backup.exists() or backup.is_relative_to(install) or backup == install:
        raise ValueError('Select a new backup directory outside the installation')
    if not surface_only and read_endpoint(state):
        raise RuntimeError('Canvas broker is active; stage this patch for its next explicit restart')
    validate_electron_payload(payload / 'sentra-electron')
    binary = payload / 'sentra-canvas.exe'
    if not surface_only and not binary.is_file():
        raise FileNotFoundError('Updated Canvas executable missing')
    names = ['sentra-canvas.exe', *('sentra-electron/' + name for name in SURFACE_REQUIRED)]
    if surface_only:
        names = [name for name in names if name != 'sentra-canvas.exe'
                 and (not (install / name).is_file() or sha(install / name) != sha(payload / name))]
    # The runtime is already pinned. Never replace DLLs in running Electron instances.
    old = json.loads((install / 'sentra-electron/sentra-surface-build.json').read_text(encoding='utf-8'))
    new = json.loads((payload / 'sentra-electron/sentra-surface-build.json').read_text(encoding='utf-8'))
    if old.get('source_version') != new.get('source_version'):
        raise ValueError('Electron runtime upgrade requires a staged full display update')
    backup.mkdir(parents=True)
    originals, applied = {}, []
    metadata = ['sentra-electron/sentra-surface-build.json', '.sentra-install.json']
    for name in names + metadata:
        target = install / name
        originals[name] = sha(target) if target.is_file() else None
        if target.is_file():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
    try:
        for name in names:
            target = install / name
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.with_name(target.name + '.local-update')
            try:
                shutil.copy2(payload / name, pending)
                os.replace(pending, target)
            finally:
                pending.unlink(missing_ok=True)
            applied.append(name)
            if sha(target) != sha(payload / name):
                raise ValueError('Installed display hash mismatch: ' + name)
        manifest = {**new, 'files': _inventory(install / 'sentra-electron')}
        (install / metadata[0]).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        applied.append(metadata[0])
        validate_electron_payload(install / 'sentra-electron')
        owned = json.loads((install / metadata[1]).read_text(encoding='utf-8'))
        owned['owned_files'] = sorted(set(owned['owned_files']) | set(names))
        (install / metadata[1]).write_text(json.dumps(owned, indent=2), encoding='utf-8')
        applied.append(metadata[1])
        proof = {'schema': 1, 'kind': 'local-display-patch', 'surface_only': surface_only, 'signed_release': False,
                 'created_at': time.time(), 'install_dir': str(install), 'backup_dir': str(backup),
                 'before': originals, 'after': {name: sha(install / name) for name in names + metadata}}
        (backup / 'patch.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
        return {'updated_files': len(names), 'backup': str(backup), 'surface_only': surface_only,
                'canvas_sha256': sha(install / 'sentra-canvas.exe')}
    except BaseException:
        for name in reversed(applied):
            if originals[name] is None:
                (install / name).unlink(missing_ok=True)
            else:
                shutil.copy2(backup / name, install / name)
        raise


def main():
    parser = argparse.ArgumentParser(__doc__)
    for name in ('install', 'payload', 'backup', 'state'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--surface-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(apply_patch(args.install, args.payload, args.backup, args.state, surface_only=args.surface_only)))


if __name__ == '__main__':
    main()
