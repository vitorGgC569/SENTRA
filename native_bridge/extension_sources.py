"""One source-identity contract shared by the release builder and relay."""
import hashlib
import json
from pathlib import Path

EXTENSION_IDENTITY_FILES = (
    'service-worker.js', 'content-script.js', 'recovery-guard.js', 'selectors.js',
    'observer.js', 'conversation-evidence.js', 'native-image-guard.js',
    'options.js', 'options.html', 'COS-NOTICE.txt',
)


def extension_source_identity(root: Path) -> dict:
    root = Path(root).resolve(strict=True)
    files = {}
    for name in EXTENSION_IDENTITY_FILES:
        target = root / name
        if target.is_symlink() or not target.is_file():
            raise FileNotFoundError(f'extension identity file missing or linked: {target}')
        files[name] = {'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'source_hash': digest, 'files': files}
