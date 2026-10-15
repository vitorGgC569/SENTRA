"""Bind final-build selected component bytes into the frozen executable.

This consumes materialized staging, not downloads or operator credentials. It
does not certify licenses, signatures or runtime QA of those components.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.commander.release_components import COMPONENTS, _file, _sha
from sentra_remote.runtime_payload import PIN_RESOURCE, validate_runtime_pins


def runtime_pins(staging: Path) -> dict:
    staging = Path(staging).absolute()
    record_file = _file(staging.resolve(strict=True), 'runtime-components.json')
    if record_file.stat().st_size > 1024 * 1024:
        raise ValueError('runtime component record exceeds bound')
    records = json.loads(record_file.read_text(encoding='utf-8'))
    if not isinstance(records, dict) or set(records) != set(COMPONENTS):
        raise ValueError('complete materialized runtime components required')
    descriptors = {}
    for name in COMPONENTS:
        record = records[name]
        if not isinstance(record, dict) or record.get('materialized') is not True or not isinstance(record.get('files'), list):
            raise ValueError('materialized runtime file pins required')
        files = {}
        for item in record['files']:
            if not isinstance(item, dict) or set(item) != {'path', 'sha256'} or item['path'] in files:
                raise ValueError('invalid runtime file record')
            files[item['path']] = item['sha256']
        manifest_relative = f'runtime/{name}/' + ('provenance.json' if name == 'quickjs' else 'manifest.json')
        manifest_file = _file(staging.resolve(strict=True), manifest_relative)
        if manifest_file.stat().st_size > 1024 * 1024 or manifest_relative not in files or _sha(manifest_file) != files[manifest_relative]:
            raise PermissionError('component provenance differs from staged pins')
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        entries = {'manifest': manifest_relative}
        fields = {'wasm': 'guest', 'sbom': 'sbom'} if name == 'quickjs' else {'executable': 'executable'}
        for role, field in fields.items():
            entries[role] = f'runtime/{name}/{manifest[field]}'
        if name == 'rustdesk':
            entries['build_manifest'] = f'runtime/rustdesk/{manifest["bundle_manifest"]}'
        descriptors[name] = {'files': files, 'entrypoints': entries}
    value = validate_runtime_pins({'schema': 1, 'components': descriptors})
    # Recheck every materialized byte: a matching manifest by itself cannot
    # attest an altered or incomplete staging tree.
    total = 0
    for descriptor in descriptors.values():
        for relative, expected in descriptor['files'].items():
            path = _file(staging.resolve(strict=True), relative)
            total += path.stat().st_size
            if total > 4 * 1024 ** 3:
                raise ValueError('runtime binding payload quota exceeded')
            if _sha(path) != expected:
                raise PermissionError('materialized runtime changed before binding')
    return value


def write_runtime_pins(staging: Path, destination: Path) -> dict:
    value = runtime_pins(staging)
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    if len(raw) > 1024 * 1024:
        raise ValueError('embedded runtime pins exceed bound')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / PIN_RESOURCE
    if target.is_symlink() or getattr(target, 'is_junction', lambda: False)():
        raise PermissionError('linked runtime pin output')
    with target.open('wb') as stream:
        stream.write(raw)
    return {'path': str(target.resolve()), 'sha256': _sha(target)}
