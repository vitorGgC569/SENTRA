"""Final-build SDK pins selected by the trusted packaging host, never guessed."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil


def require_wasmtime_pin():
    selector = os.environ.get('SENTRA_BUILD_RUNTIME_PINS_FILE')
    if not selector:
        raise RuntimeError('integral packaging requires a reviewed Wasmtime version/native-file pin record')
    path = Path(selector)
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
        raise PermissionError('unsafe packaging runtime pin record')
    spec = json.loads(path.read_text(encoding='utf-8'))['wasmtime']
    version = spec.get('version')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Wasmtime SDK requires an exact approved version')
    distribution = importlib.metadata.distribution('wasmtime')
    if distribution.version != version:
        raise RuntimeError('installed Wasmtime differs from the approved SDK pin')
    native = {str(f).replace('\\', '/'): f for f in distribution.files or ()
              if str(f).lower().endswith(('.dll', '.so', '.dylib'))}
    pins = spec.get('files')
    if not native or not isinstance(pins, dict) or set(pins) != set(native):
        raise ValueError('Wasmtime pin record must cover the actual native runtime files')
    for name, file in native.items():
        expected = pins[name]
        target = Path(distribution.locate_file(file))
        if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected) or target.is_symlink():
            raise PermissionError('invalid Wasmtime native-file pin')
        digest = hashlib.sha256()
        with target.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
        if digest.hexdigest() != expected:
            raise PermissionError('Wasmtime native runtime pin mismatch')
    license_id = spec.get('license')
    if not isinstance(license_id, str) or not license_id.strip():
        raise ValueError('reviewed Wasmtime SDK license record required')
    licenses = spec.get('license_files')
    known = {str(f).replace('\\', '/'): f for f in distribution.files or ()}
    if not isinstance(licenses, dict) or not licenses or not set(licenses) <= set(known):
        raise ValueError('Wasmtime SDK license file pins required')
    for name, expected in licenses.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or ':' in name or '\\' in name:
            raise PermissionError('SDK license path is not portable/confined')
        target = Path(distribution.locate_file(known[name]))
        if target.is_symlink() or target.stat().st_size > 1048576 or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise PermissionError('Wasmtime SDK license bytes differ from pin')
    return {'name': 'wasmtime', 'version': version, 'files': pins,
            'license': license_id, 'license_files': licenses, 'validated': False}


def stage_wasmtime_notices(destination):
    record = require_wasmtime_pin()
    distribution = importlib.metadata.distribution('wasmtime')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for name in record['license_files']:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(distribution.locate_file(name), target)
    (destination / 'provenance.json').write_text(json.dumps(record, sort_keys=True, indent=2), encoding='utf-8')
    return record
