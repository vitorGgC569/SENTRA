"""Final-phase materialized runtime transport. Importing never builds/stages."""
import hashlib
import json
from pathlib import Path
import shutil
import re


def _file(root, name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise PermissionError('component requires portable relative paths')
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise PermissionError('component path escaped payload')
    target = root / relative
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
           for p in (target, *target.parents)) or not target.resolve().is_relative_to(root) or not target.is_file():
        raise PermissionError('linked or missing component payload')
    return target

COMPONENTS = ('quickjs', 'hcs', 'rustdesk')


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def stage_runtime_components(staging, sources):
    """sources are host/final-build selected directories with real manifests."""
    staging = Path(staging).resolve(strict=True)
    if set(sources) != set(COMPONENTS):
        raise ValueError('QuickJS/HCS/RustDesk artifacts required for integral release')
    result = {}
    for name in COMPONENTS:
        source = Path(sources[name]).resolve(strict=True)
        manifest_file = source / ('provenance.json' if name == 'quickjs' else 'manifest.json')
        if manifest_file.is_symlink() or not manifest_file.is_file() or manifest_file.stat().st_size > 1048576:
            raise FileNotFoundError('materialized component provenance missing: ' + name)
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        if name == 'quickjs':
            guest = _file(source, manifest['guest'])
            sbom_file = _file(source, manifest['sbom'])
            license_file = _file(source, 'LICENSE-QuickJS')
            items = [{'path': manifest['guest'], 'sha256': manifest['wasm_sha256']},
                     {'path': manifest['sbom'], 'sha256': _sha(sbom_file)},
                     {'path': 'LICENSE-QuickJS', 'sha256': _sha(license_file)},
                     {'path': 'provenance.json', 'sha256': _sha(manifest_file)}]
            with guest.open('rb') as stream:
                if stream.read(4) != b'\0asm': raise ValueError('QuickJS guest is not WASM')
            if sbom_file.stat().st_size > 1048576: raise ValueError('QuickJS SBOM exceeds bound')
            sbom = json.loads(sbom_file.read_text(encoding='utf-8'))
            if sbom.get('bomFormat') != 'CycloneDX': raise ValueError('QuickJS SBOM required')
            if manifest.get('wasi_imports') or manifest.get('host_imports') != ['env.sentra_host_call']:
                raise ValueError('QuickJS ABI import contract mismatch')
        else:
            items = manifest.get('files')
            if not isinstance(items, list) or not 1 <= len(items) <= 20000 or manifest.get('compiled') is not True:
                raise ValueError('native component build proof/files required: ' + name)
            if name == 'rustdesk' and manifest.get('control_extension') != 'sentra-desktop-control-v1':
                raise ValueError('RustDesk desktop control ABI missing')
            items = [*items, {'path': 'manifest.json', 'sha256': _sha(manifest_file)}]
        target = staging / 'runtime' / name
        if target.exists(): raise FileExistsError('runtime staging exists: ' + name)
        target.mkdir(parents=True)
        hashes, seen, total = [], set(), 0
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', item['sha256']):
                raise ValueError('component file manifest lacks exact SHA-256')
            relative = Path(item['path'])
            canonical = relative.as_posix().casefold()
            if canonical in seen: raise ValueError('duplicate component path on Windows')
            seen.add(canonical)
            origin = _file(source, item['path'])
            total += origin.stat().st_size
            if total > 4 * 1024 ** 3: raise ValueError('runtime payload quota exceeded')
            if _sha(origin) != item['sha256']:
                raise PermissionError('native component file digest mismatch')
            destination = target / relative; destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)
            hashes.append({'path': destination.relative_to(staging).as_posix(), 'sha256': _sha(destination)})
        result[name] = {'files': hashes, 'provenance_sha256': _sha(manifest_file),
                        'control_extension': manifest.get('control_extension'), 'license': manifest.get('upstream', {}).get('license', manifest.get('license')),
                        'materialized': True, 'validated': False}
    (staging / 'runtime-components.json').write_text(json.dumps(result, sort_keys=True, indent=2), encoding='utf-8')
    return result
