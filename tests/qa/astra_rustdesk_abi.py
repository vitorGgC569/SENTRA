"""Probe the compiled SENTRA RustDesk ABI in an isolated, bounded process.

No GUI, peer connection, input, install, service or desktop action is started.
The probe does not stand in for an authenticated remote desktop acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.commander.build_rustdesk import source_inputs, validate_native_sources
from scripts.commander.native_payload import inspect_pe


def probe(source: Path, proof_file: Path) -> dict:
    if os.name != 'nt':
        raise RuntimeError('Windows native ABI probe required')
    source = source.resolve(strict=True)
    proof = json.loads(proof_file.read_text(encoding='utf-8'))
    native = validate_native_sources(source)
    if proof.get('phase') != 'native' or proof.get('source_revision') != native['source_revision']:
        raise ValueError('native compilation proof required')
    if proof.get('inputs') != source_inputs(source) or proof.get('native_sources') != native['native_sources']:
        raise ValueError('native proof no longer matches its sources')
    name = 'target/release/librustdesk.dll'
    library = source / name
    actual = hashlib.sha256(library.read_bytes()).hexdigest()
    if proof.get('outputs', {}).get(name) != actual:
        raise ValueError('native library differs from its compilation proof')
    inspection = inspect_pe(library, dll=True, required_exports=('sentra_desktop_control_abi_v1',))
    child = '''import ctypes,json,os,sys
path=os.path.abspath(sys.argv[1])
with os.add_dll_directory(os.path.dirname(path)):
    library=ctypes.CDLL(path,winmode=0x1100)
    probe=library.sentra_desktop_control_abi_v1
    probe.argtypes=[]
    probe.restype=ctypes.c_uint32
    result=probe()
    if result!=1: raise RuntimeError("unexpected SENTRA ABI version")
    print(json.dumps({"symbol":"sentra_desktop_control_abi_v1","version":result}))
'''
    started = time.monotonic()
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith('SENTRA_')}
    result = subprocess.run([sys.executable, '-I', '-c', child, str(library)], env=env,
                            cwd=library.parent, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, check=True, timeout=15,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    received = json.loads(result.stdout)
    if received != {'symbol': 'sentra_desktop_control_abi_v1', 'version': 1}:
        raise ValueError('unexpected native ABI receipt')
    if hashlib.sha256(library.read_bytes()).hexdigest() != actual:
        raise RuntimeError('native library changed during ABI probe')
    return {'schema_version': 1, 'library_sha256': actual, 'source_revision': native['source_revision'],
            'native_build_proof_sha256': hashlib.sha256(proof_file.read_bytes()).hexdigest(),
            'inspection': inspection, 'probe': received, 'duration_ms': round((time.monotonic()-started)*1000),
            'native_symbol_executed': True, 'peer_authenticated': False,
            'desktop_session_verified': False, 'installed_release_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.source, args.proof)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
