"""Stage the read-only terminal mirror with exact post-patch external files."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES = 'node_modules/@xterm/'
MAX_FILES = 512
MAX_BYTES = 64 * 1024 * 1024


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file(root, name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or PurePosixPath(name).is_absolute() or PurePosixPath(name).as_posix() != name
            or any(part in {'.', '..'} for part in PurePosixPath(name).parts)):
        raise ValueError('Invalid terminal runtime path')
    path = root / name
    for candidate in (path, *path.parents):
        if candidate == root:
            break
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError('Linked terminal runtime file')
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Missing terminal runtime file: ' + name)
    return path


def inventory(root, *, exclude_runtime_manifest=True):
    root = Path(root).absolute()
    result, pending, total = {}, [root], 0
    while pending:
        folder = pending.pop()
        if folder.is_symlink() or folder.is_junction():
            raise ValueError('Linked terminal runtime file')
        for path in folder.iterdir():
            if path.is_symlink() or path.is_junction():
                raise ValueError('Linked terminal runtime file')
            if path.is_dir():
                pending.append(path)
            elif path.is_file() and (not exclude_runtime_manifest or path.relative_to(root).as_posix() != 'runtime.json'):
                total += path.stat().st_size
                if total > MAX_BYTES:
                    raise ValueError('Terminal runtime byte limit exceeded')
                result[path.relative_to(root).as_posix()] = sha(path)
            if len(result) + len(pending) > MAX_FILES:
                raise ValueError('Terminal runtime inventory exceeded')
    return dict(sorted(result.items()))


def _pins(root, pins, *, dependencies=False):
    if not isinstance(pins, dict) or not 1 <= len(pins) <= MAX_FILES:
        raise ValueError('Bounded terminal file seal required')
    total, seen = 0, set()
    for name, digest in pins.items():
        if (not isinstance(name, str) or name.casefold() in seen
                or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)
                or dependencies and not name.startswith(DEPENDENCIES)
                or not dependencies and name.startswith(('node_modules/', 'dist/'))):
            raise ValueError('Invalid terminal file seal')
        seen.add(name.casefold())
        path = _file(root, name)
        total += path.stat().st_size
        if total > MAX_BYTES or sha(path) != digest:
            raise ValueError('Terminal dependency seal stale' if dependencies else 'Terminal engine source seal stale')


def validate_terminal_engine(root):
    """Source and installed consumers require the same dependency-aware seal."""
    root = Path(root).absolute()
    manifest_file = _file(root, 'dist/manifest.json')
    if manifest_file.stat().st_size > 256000:
        raise ValueError('Terminal engine manifest exceeded limit')
    seal = json.loads(manifest_file.read_text(encoding='utf-8'))
    if not isinstance(seal, dict) or seal.get('version') != 2:
        raise ValueError('Terminal dependency seal missing; rebuild legacy engine')
    _pins(root, seal.get('sources'))
    _pins(root, seal.get('runtime_dependencies'), dependencies=True)
    expected = seal['runtime_dependencies']
    actual = {DEPENDENCIES + name: digest for name, digest in inventory(root / DEPENDENCIES, exclude_runtime_manifest=False).items()}
    if expected != actual:
        raise ValueError('Terminal dependency inventory differs from sealed files')
    for name in ('headless/lib-headless/xterm-headless.js', 'addon-serialize/lib/addon-serialize.js',
                 'addon-unicode11/lib/addon-unicode11.js'):
        if DEPENDENCIES + name not in expected:
            raise ValueError('Required terminal dependency missing: ' + name)
    payload = {key: seal[key] for key in ('sources', 'runtime_dependencies', 'output')}
    build_id = hashlib.sha256(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    if seal.get('build_id') != build_id or sha(_file(root, 'dist/engine.cjs')) != seal['output']:
        raise ValueError('Terminal engine build unavailable or stale')
    return seal


def validate_terminal_runtime(root):
    root = Path(root).absolute()
    path = _file(root, 'runtime.json')
    if path.stat().st_size > 256000:
        raise ValueError('Invalid terminal runtime manifest')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('schema') != 2:
        raise ValueError('Terminal runtime dependency seal missing; rebuild legacy payload')
    if manifest.get('files') != inventory(root):
        raise ValueError('Terminal runtime integrity failure')
    seal = validate_terminal_engine(root)
    expected = set(seal['sources']) | set(seal['runtime_dependencies']) | {'dist/engine.cjs', 'dist/manifest.json'}
    if (set(manifest['files']) != expected or manifest.get('engine_build_id') != seal['build_id']
            or not {'src/worker.mjs', 'vendor/orca/LICENSE'} <= expected):
        raise ValueError('Incomplete terminal runtime or mismatched build')
    return manifest


def stage_terminal_runtime(destination):
    destination = Path(destination).absolute()
    source = ROOT / 'integrations/orca-terminal'
    if destination.is_symlink() or destination.is_junction():
        raise ValueError('Linked terminal staging directory')
    if destination == ROOT or destination.resolve().is_relative_to(ROOT / 'integrations'):
        raise ValueError('Choose a packaging directory')
    seal = validate_terminal_engine(source)
    if destination.exists() and any(destination.iterdir()):
        current = validate_terminal_runtime(destination)
        if current['engine_build_id'] != seal['build_id']:
            raise ValueError('Choose a fresh terminal staging directory')
        return current
    files = {**seal['sources'], **seal['runtime_dependencies'],
             'dist/engine.cjs': seal['output'], 'dist/manifest.json': sha(source / 'dist/manifest.json')}
    for name, digest in files.items():
        original = _file(source, name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        if sha(target) != digest:
            raise ValueError('Terminal input changed during staging')
    record = {'schema': 2, 'read_only': True, 'engine_build_id': seal['build_id'], 'files': inventory(destination)}
    (destination / 'runtime.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return validate_terminal_runtime(destination)
