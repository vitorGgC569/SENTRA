"""Apply the approved integration in a disposable tree; never edit the upstream."""
from pathlib import Path
import io
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile


def prepare(root: Path) -> Path:
    upstream = root / 'third_party/codex-chatgpt-web'
    manifest = json.loads((root / 'integrations/codex_chatgpt_web/upstream.json').read_text())
    commit = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != manifest['commit']:
        raise RuntimeError('Upstream HEAD differs from the pinned integration commit')
    if subprocess.check_output(['git', '-C', str(upstream), 'status', '--porcelain'], text=True).strip():
        raise RuntimeError('Disposable QA requires the preserved pure upstream')
    patch = root / manifest['integration_patch']
    patched_files = re.findall(r'^diff --git a/(\S+) b/(\S+)$', patch.read_text(encoding='utf-8'), re.M)
    if any(a != b for a, b in patched_files) or [a for a, _ in patched_files] != manifest['patch_files']:
        raise RuntimeError('Patch paths differ from the existing upstream.json allowlist')
    archive = subprocess.check_output(['git', '-C', str(upstream), 'archive', '--format=zip', 'HEAD'])
    target = Path(tempfile.mkdtemp(prefix='sentra-browser-v2-'))
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        source.extractall(target)
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=target, check=True)
    subprocess.run(['git', 'apply', str(patch)],
                   cwd=target, check=True)
    (target / 'SENTRA_QA_PROVENANCE.json').write_text(json.dumps({
        'upstream_commit': commit, 'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
        'patch_files': manifest['patch_files'], 'production_activated': False,
    }, indent=2), encoding='utf-8')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-build', action='store_true', help='Use existing QA dependencies; runtime packaging stays disposable, never activation/global install')
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    target = prepare(root)
    print(target, flush=True)
    if options.verify_build:
        dependencies = root / 'third_party/codex-chatgpt-web/node_modules'
        if not dependencies.is_dir():
            raise RuntimeError('Existing local upstream dependencies required; nothing installed')
        for relative in ('node_modules', 'launcher/node_modules'):
            dependencies = root / 'third_party/codex-chatgpt-web' / relative
            if not dependencies.is_dir():
                raise RuntimeError(f'Existing local dependency directory required: {relative}')
            quoted_target = "'" + str(target / relative).replace("'", "''") + "'"
            quoted_dependencies = "'" + str(dependencies).replace("'", "''") + "'"
            subprocess.run(['powershell', '-NoProfile', '-Command',
                            f'New-Item -ItemType Junction -Path {quoted_target} -Target {quoted_dependencies} | Out-Null'], check=True)
        bun = root / '.sentra/toolchain/node_modules/bun/bin/bun.exe'
        host_sources = ('launcher/electron/browser-host.cjs', 'launcher/electron/control-server.cjs')
        for relative in host_sources:
            subprocess.run(['node', '--check', str(target / relative)], cwd=target, check=True)
        subprocess.run([str(bun), 'x', '--no-install', '--bun', 'tsc', '--noEmit'], cwd=target, check=True)
        output = (target / 'dist/runtime').resolve()
        if not output.is_relative_to(target.resolve()):
            raise RuntimeError('Build output escapes the disposable tree')
        subprocess.run([str(bun), 'run', 'scripts/build-runtime-bundle.ts', str(output)], cwd=target, check=True)
        provenance_path = target / 'SENTRA_QA_PROVENANCE.json'
        provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
        provenance.update(typecheck='passed', host_syntax='passed', runtime_build='passed', host_source_sha256={
            name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in host_sources
        }, artifact_sha256={
            name: hashlib.sha256((output / 'app' / name).read_bytes()).hexdigest()
            for name in ('cli.js', 'browser-helper.cjs')
        })
        provenance_path.write_text(json.dumps(provenance, indent=2), encoding='utf-8')
