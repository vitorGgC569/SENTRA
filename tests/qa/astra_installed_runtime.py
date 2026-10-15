"""Run the real frozen byte-selection probe; no install, guest or native session."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staging', type=Path, required=True)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    staging = args.staging.resolve(strict=True)
    executable = staging / 'sentra-runtime-probe.exe'
    proof_file = staging / 'build-provenance-runtime-probe.json'
    proof = json.loads(proof_file.read_text(encoding='utf-8'))
    if (proof['executables'][executable.name]['sha256'] != digest(executable)
            or proof['runtime_pins_sha256'] != digest(args.pins)):
        raise RuntimeError('Probe executable or embedded runtime selection differs from build proof')
    pins = json.loads(args.pins.read_text(encoding='utf-8'))
    environment = os.environ.copy()
    for key in ('WASM_PATH', 'SBOM_PATH', 'WASM_SHA256', 'SBOM_SHA256'):
        environment.pop('SENTRA_QUICKJS_' + key, None)
    completed = subprocess.run([str(executable)], cwd=staging, env=environment, capture_output=True, timeout=90,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if completed.returncode:
        raise RuntimeError('Frozen probe failed: ' + completed.stderr.decode('utf-8', errors='replace')[-2000:])
    positive = json.loads(completed.stdout)
    if positive.get('frozen') is not True or positive.get('quickjs', {}).get('enabled') is not True:
        raise RuntimeError('Actual frozen readiness was not proven')
    # Isolate the negative test. Never mutate the original materialized tree.
    with tempfile.TemporaryDirectory(prefix='runtime-binding-negative-', dir=staging.parent) as temporary:
        negative_root = Path(temporary).resolve(strict=True)
        assert negative_root.parent == staging.parent and negative_root != staging
        shutil.copy2(executable, negative_root / executable.name)
        for component in pins['components'].values():
            for relative in set(component['entrypoints'].values()):
                source, target = staging / relative, negative_root / relative
                if not target.resolve().is_relative_to(negative_root):
                    raise RuntimeError('Unexpected negative-fixture path')
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
        wasm_relative = pins['components']['quickjs']['entrypoints']['wasm']
        (negative_root / wasm_relative).write_bytes(b'changed-not-a-WASM-module')
        # An adjacent, editable replacement checksum must not become its own
        # trust anchor or override the selection embedded inside the EXE.
        altered = json.loads(json.dumps(pins))
        altered['components']['quickjs']['files'][wasm_relative] = digest(negative_root / wasm_relative)
        (negative_root / 'runtime-components.json').write_text(json.dumps(altered), encoding='utf-8')
        (negative_root / 'sentra-runtime-pins.json').write_text(json.dumps(altered), encoding='utf-8')
        negative = subprocess.run([str(negative_root / executable.name)], cwd=negative_root, env=environment,
            capture_output=True, timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if negative.returncode == 0 or b'CodeModeUnavailable' not in negative.stderr:
            raise RuntimeError('Changed artifact unexpectedly selected by frozen runtime')
    report = {'frozen_probe': positive, 'build_proof_sha256': digest(proof_file), 'executable_sha256': digest(executable),
        'runtime_pins_sha256': digest(args.pins), 'source_snapshot_sha256': proof.get('source_snapshot_sha256'),
        'operator_artifact_env_required': False, 'changed_bytes_and_adjacent_repin_rejected': True,
        'original_staging_modified_by_negative_test': False,
        'signed_release_verified': False, 'clean_install_verified': False, 'success': True}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
