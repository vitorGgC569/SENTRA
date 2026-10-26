import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from sentra_quality.distribution_diagnosis import PACKAGE_FILES, diagnose_installer_text


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / 'installer/windows/install-next.ps1'


@pytest.mark.skipif(shutil.which('pwsh') is None, reason='PowerShell 7 is unavailable')
def test_wrapper_dry_run_maps_arguments_for_inno_and_keeps_paths_with_spaces(tmp_path):
    setup = tmp_path / 'setup.exe'
    setup.write_bytes(b'non-executable fixture; dry run must not launch it')
    destination = tmp_path / 'installation with spaces'
    result = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', str(WRAPPER),
        '-SetupPath', str(setup), '-InstallDir', str(destination), '-NoLaunch', '-DryRun'],
        check=True, capture_output=True, text=True, timeout=20)
    value = json.loads(result.stdout)
    assert value['package_verified'] is False
    assert value['arguments'] == ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
        '/DIR="' + str(destination.resolve()) + '"', '/NO-LAUNCH']
    assert not destination.exists()


def test_comments_are_not_evidence_of_packaged_files_or_version():
    script = '# product_version = "1.0.5"\n' + ''.join('# ' + name + '\n' for name in PACKAGE_FILES) + 'Write-Output hello\n'
    report = diagnose_installer_text(script, product_version='1.0.5')
    assert report['missing'] == list(PACKAGE_FILES)
    assert report['version_matches'] is False


def test_wrapper_propagates_a_real_inno_setup_failure_when_compiler_available(tmp_path):
    iscc = Path(os.environ.get('LOCALAPPDATA', '')) / 'SENTRA/Build/toolchains/InnoSetup-7.1.0/ISCC.exe'
    if not iscc.is_file() or not shutil.which('pwsh'):
        pytest.skip('Inno Setup compiler and PowerShell 7 are needed for the native fixture')
    output = tmp_path / 'output'
    output.mkdir()
    script = tmp_path / 'fixture.iss'
    script.write_text('''[Setup]\nAppId=SENTRA.Wrapper.Fixture\nAppName=Wrapper Fixture\nAppVersion=1.0.0\n'''
        + 'DefaultDirName={tmp}\\sentra-wrapper-fixture\nPrivilegesRequired=lowest\n'
        + 'Uninstallable=no\nCreateAppDir=no\nCompression=none\n'
        + f'OutputDir={output}\nOutputBaseFilename=setup\n'
        + 'VersionInfoOriginalFileName=SENTRA-Inno-Setup.exe\n'
        + '[Code]\nfunction InitializeSetup: Boolean;\nbegin\n  Result := False;\nend;\n', encoding='utf-8')
    subprocess.run([str(iscc), str(script)], check=True, capture_output=True, text=True, timeout=60)
    result = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', str(WRAPPER),
        '-SetupPath', str(output/'setup.exe'), '-InstallDir', str(tmp_path/'with spaces'), '-NoLaunch'],
        capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'Codigo:' in result.stderr
    assert 'SENTRA_INSTALL_COMPLETE' not in result.stdout
    assert not (tmp_path/'with spaces').exists()
