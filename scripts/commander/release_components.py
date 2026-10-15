"""Final-phase materialized runtime transport. Importing never builds/stages."""
import hashlib
import json
from pathlib import Path
import shutil
import re
from sentra_remote.windows_paths import filesystem_path, resolved_path


def _file(root, name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise PermissionError('component requires portable relative paths')
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise PermissionError('component path escaped payload')
    target = root / relative
    candidates = [Path(filesystem_path(p, resolve=False)) for p in (target, *target.parents)]
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
           for p in candidates) or not resolved_path(target).is_relative_to(resolved_path(root)) or not Path(filesystem_path(target)).is_file():
        raise PermissionError('linked or missing component payload')
    return Path(filesystem_path(target))

COMPONENTS = ('quickjs', 'hcs', 'rustdesk')


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _native_payload(source, name, manifest):
    from scripts.commander.native_payload import inspect_pe
    executable = manifest.get('executable')
    if not isinstance(executable, str) or not executable.lower().endswith('.exe'):
        raise ValueError('native component executable proof required: ' + name)
    listed = {item.get('path'): item.get('sha256') for item in manifest['files'] if isinstance(item, dict)}
    if executable not in listed:
        raise ValueError('native executable absent from component file manifest')
    inspected = {'executable': inspect_pe(_file(source, executable), dll=False)}
    if name == 'rustdesk':
        if (manifest.get('extension') != 'sentra-peer-gate-v1' or
                manifest.get('stock_cli_supported') is not False or
                manifest.get('executable_sha256') != listed[executable]):
            raise ValueError('RustDesk instrumented launcher proof required')
        bundle = manifest.get('bundle_sha256')
        if not isinstance(bundle, dict) or not bundle or bundle.get(executable) != listed[executable]:
            raise ValueError('RustDesk exact bundle pins required')
        if any(listed.get(path) != digest for path, digest in bundle.items()):
            raise ValueError('RustDesk bundle pins differ from component manifest')
        if 'librustdesk.dll' not in bundle:
            raise ValueError('RustDesk native library proof required')
        inspected['library'] = inspect_pe(_file(source, 'librustdesk.dll'), dll=True,
                                         required_exports=('sentra_desktop_control_abi_v1',))
    return inspected


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
            # Metadata cannot turn a header-only or WASI-linked module into a
            # real guest. Inspect these exact bytes before packaging them.
            from sentra_code_mode.guest.inspect_wasm import inspect_abi
            with guest.open('rb') as stream:
                inspect_abi(stream.read(32 * 1024 * 1024 + 1))
            legal = manifest.get('legal_files')
            if not isinstance(legal, list) or not 1 <= len(legal) <= 64:
                raise ValueError('QuickJS static-runtime license proofs required')
            items.extend(legal)
        else:
            items = manifest.get('files')
            if not isinstance(items, list) or not 1 <= len(items) <= 20000 or manifest.get('compiled') is not True:
                raise ValueError('native component build proof/files required: ' + name)
            if name == 'rustdesk' and manifest.get('control_extension') != 'sentra-desktop-control-v1':
                raise ValueError('RustDesk desktop control ABI missing')
            _native_payload(source, name, manifest)
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
