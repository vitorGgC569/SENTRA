"""Compile the real Inno script with inert fixture files; NEVER execute its EXE.

python tests/qa/inno_compile_smoke.py --compiler <ISCC.exe> --output <unused-dir>
This checks compiler compatibility and update dispatch, not product installation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.commander.inno_setup import build_inno
from sentra_remote.installer_engine import install_command, original_filename


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    bundle = output / 'inert-bundle'
    bundle.mkdir()
    (bundle / 'fixture.txt').write_text('Compiler fixture only. No SENTRA executable is included.')
    setup = build_inno(bundle, output / 'compiled', '1.0.3', compiler=args.compiler)
    identity = original_filename(setup)
    assert identity == 'SENTRA-Inno-Setup.exe', repr(identity)
    command = install_command(setup, ['--silent', '--no-launch', '--install-dir', 'C:/SENTRA fixture'])
    assert '/VERYSILENT' in command and '/DIR=C:/SENTRA fixture' in command
    report = {'ok': True, 'scope': 'inert compiler fixture only',
              'original_filename': identity, 'native_update_dispatch': True,
              'setup_script_sha256': hashlib.sha256((ROOT / 'scripts/commander/sentra_setup.iss').read_bytes()).hexdigest(),
              'installation_executed': False, 'product_installation_qualified': False}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
