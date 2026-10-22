"""The external serializer must be the exact post-patch input in every mode."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.commander import stage_terminal as stage
from sentra_canvas import terminal_snapshots as backend

ROOT = Path(__file__).resolve().parents[2]
SERIALIZER = 'node_modules/@xterm/addon-serialize/lib/addon-serialize.js'


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    source = ROOT / 'integrations/orca-terminal'
    seal = stage.validate_terminal_engine(source)
    target = tmp_path / 'checkout/integrations/orca-terminal'
    names = set(seal['sources']) | set(seal['runtime_dependencies']) | {'dist/engine.cjs', 'dist/manifest.json'}
    for name in names:
        file = target / name
        file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, file)
    monkeypatch.setattr(stage, 'ROOT', target.parents[1])
    return target


def test_staging_copies_exact_post_patch_dependencies_and_licenses(checkout, tmp_path):
    target = tmp_path / 'installed/sentra-terminal'
    seal = stage.validate_terminal_engine(checkout)
    manifest = stage.stage_terminal_runtime(target)
    assert manifest['schema'] == 2 and manifest['read_only'] is True
    assert manifest['engine_build_id'] == seal['build_id']
    assert manifest['files'] == stage.inventory(target)
    assert set(manifest['files']) == set(seal['sources']) | set(seal['runtime_dependencies']) | {'dist/engine.cjs', 'dist/manifest.json'}
    assert any(name.endswith('/LICENSE') for name in seal['runtime_dependencies'])
    assert stage.stage_terminal_runtime(target) == manifest


@pytest.mark.parametrize('mutation', ['changed', 'missing', 'extra', 'extra_runtime_manifest', 'legacy'])
def test_staging_refuses_invalid_dependencies_before_creating_output(checkout, tmp_path, mutation):
    if mutation == 'changed':
        (checkout / SERIALIZER).write_text('unsealed serializer', encoding='utf-8')
    elif mutation == 'missing':
        (checkout / SERIALIZER).unlink()
    elif mutation.startswith('extra'):
        name = 'runtime.json' if mutation == 'extra_runtime_manifest' else 'unexpected.js'
        (checkout / 'node_modules/@xterm' / name).write_text('{}', encoding='utf-8')
    else:
        file = checkout / 'dist/manifest.json'
        seal = json.loads(file.read_text(encoding='utf-8'))
        seal['version'] = 1
        file.write_text(json.dumps(seal), encoding='utf-8')
    target = tmp_path / 'must-not-exist'
    with pytest.raises(ValueError):
        stage.stage_terminal_runtime(target)
    assert not target.exists()


def test_actual_pristine_serializer_is_rejected_without_reapplying_patch(checkout, tmp_path):
    patch = checkout / 'vendor/orca/config/patches/@xterm__addon-serialize@0.15.0-beta.301.patch'
    # A nested basetemp must not inherit the product repository's apply prefix.
    subprocess.run(['git', 'init', '--quiet'], cwd=checkout.parents[1], check=True, capture_output=True)
    patched = stage.sha(checkout / SERIALIZER)
    command = ['git', 'apply', '--reverse', '--directory=integrations/orca-terminal/node_modules/@xterm/addon-serialize', '--', str(patch)]
    subprocess.run(command, cwd=checkout.parents[1], check=True, capture_output=True)
    assert stage.sha(checkout / SERIALIZER) != patched
    with pytest.raises(ValueError, match='dependency seal stale'):
        stage.stage_terminal_runtime(tmp_path / 'pristine-refused')


def test_source_backend_refuses_changed_dependency_before_spawning(checkout, monkeypatch):
    (checkout / SERIALIZER).write_text('changed', encoding='utf-8')
    monkeypatch.setattr(backend, '__file__', str(checkout.parents[1] / 'sentra_canvas/terminal_snapshots.py'))
    monkeypatch.setattr(backend.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Unvalidated worker spawned'))
    mirror = backend.TerminalSnapshots()
    assert not mirror.available and mirror.error == 'snapshot_runtime_unconfirmed'


def test_worker_itself_refuses_changed_dependency_before_ready(checkout):
    (checkout / SERIALIZER).write_text('changed', encoding='utf-8')
    result = subprocess.run([shutil.which('node'), str(checkout / 'src/worker.mjs')],
                            input='', capture_output=True, text=True, encoding='utf-8', timeout=10)
    assert result.returncode != 0
    assert not result.stdout
    assert 'Terminal dependency seal stale' in result.stderr


def assert_real_snapshot(mirror):
    try:
        assert mirror.available, mirror.error
        mirror.call('create', 'sealed', cols=80, rows=24)
        text = 'sealed 🐋\r\n\x1b[?1049h\x1b[2J\x1b[3;4HTUI'
        mirror.call('apply', 'sealed', event={'kind': 'output', 'sequence': 1, 'start': 0, 'text': text})
        frame = mirror.call('capture', 'sealed')
        assert frame['engine_version'] == 1 and frame['sequence'] == 1
        assert frame['cursor'] == len(text)
        assert frame['modes']['alternateScreen']
        assert 'TUI' in frame['snapshotAnsi'] and 'sealed 🐋' in frame['scrollbackAnsi']
    finally:
        mirror.close()


def test_real_source_backend_uses_manifest_two_and_protocol_one():
    assert_real_snapshot(backend.TerminalSnapshots())


def test_real_installed_path_backend_uses_sealed_node_and_terminal(tmp_path, monkeypatch):
    # Exercise frozen path selection with actual staged files/Node; no claim of a new frozen EXE.
    from scripts.commander.stage_mobile import stage_mobile_runtime
    stage_mobile_runtime(tmp_path / 'sentra-mobile', Path(shutil.which('node')))
    stage.stage_terminal_runtime(tmp_path / 'sentra-terminal')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'sentra-canvas.exe'))
    assert_real_snapshot(backend.TerminalSnapshots())
    (tmp_path / 'sentra-terminal' / SERIALIZER).write_text('changed after staging', encoding='utf-8')
    monkeypatch.setattr(backend.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Unvalidated installed worker spawned'))
    mirror = backend.TerminalSnapshots()
    assert not mirror.available and mirror.error == 'snapshot_runtime_integrity_unconfirmed'
