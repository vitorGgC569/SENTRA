"""Execute an inert native Setup fixture, NEVER the real SENTRA worker.

Checks selected directories, argument quoting, successful/failed exit codes.
No registration, account, product process or preexisting installation is used.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.commander.inno_setup import build_inno

STUB = r'''
using System;
using System.IO;
class InertWorker {
  static string Value(string[] args, string name) {
    for (int i=0;i<args.Length-1;i++) if(args[i]==name) return args[i+1];
    throw new Exception("missing fixture argument");
  }
  static int Main(string[] args) {
    string state=Value(args,"--state-dir");
    Directory.CreateDirectory(state);
    File.WriteAllLines(Path.Combine(state,"inert-worker-arguments.txt"),args);
    return int.Parse(Environment.GetEnvironmentVariable("SENTRA_INNO_FIXTURE_EXIT") ?? "0");
  }
}'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    bundle = output / 'inert-bundle'; bundle.mkdir()
    stub = output / 'inert-worker.cs'; stub.write_text(STUB)
    csc = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    worker = bundle / 'sentra-installer.exe'
    subprocess.run([str(csc), '/nologo', '/target:exe', '/out:' + str(worker), str(stub)],
        check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    setup = build_inno(bundle, output / 'compiled', '1.0.3', compiler=args.compiler)
    cases = []
    for code in (0, 7):
        target = output / ('target with spaces ' + str(code))
        state = output / ('state ' + str(code))
        environment = dict(os.environ, SENTRA_INNO_FIXTURE_EXIT=str(code))
        result = subprocess.run([str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            '/NO-LAUNCH', '/SENTRA-NO-REGISTRATION', '/DIR=' + str(target),
            '/SENTRA-STATE-DIR=' + str(state), '/LOG=' + str(output / ('run-' + str(code) + '.log'))],
            env=environment, check=False, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        actual = (state / 'inert-worker-arguments.txt').read_text().splitlines()
        selected = Path(actual[actual.index('--install-dir') + 1])
        assert selected == target, (selected, target)
        assert result.returncode == code, (code, result.returncode)
        assert '--local-only' in actual and '--no-system-registration' in actual
        cases.append({'worker_exit': code, 'setup_exit': result.returncode, 'selected_directory_preserved': True})
    report = {'ok': True, 'scope': 'inert native envelope only', 'cases': cases,
        'real_product_installed': False, 'provider_login_tested': False}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
