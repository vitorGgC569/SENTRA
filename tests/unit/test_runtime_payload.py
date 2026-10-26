"""Byte selection/trust-boundary tests. Synthetic native files never execute."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.commander.runtime_bindings import runtime_pins, write_runtime_pins
from sentra_remote.runtime_payload import (PIN_RESOURCE, InstalledRuntimeUnavailable,
    load_installed_component, validate_runtime_pins)
from sentra_code_mode.artifact_config import load_artifact, load_artifact_from_env
from sentra_code_mode import CodeModeUnavailable


def fixture_staging(root):
    records = {}
    for name in ('quickjs', 'hcs', 'rustdesk'):
        directory = root / 'runtime' / name; directory.mkdir(parents=True)
        if name == 'quickjs':
            assets = {'quickjs.wasm': b'\0asm-synthetic-not-executed', 'sbom.json': b'{"bomFormat":"CycloneDX"}'}
            manifest = {'guest': 'quickjs.wasm', 'sbom': 'sbom.json'}
            filename = 'provenance.json'
        else:
            assets = {'component.exe': b'synthetic-not-PE-not-executed'}
            manifest = {'executable': 'component.exe'}; filename = 'manifest.json'
            if name == 'rustdesk':
                manifest['bundle_manifest'] = 'bundle-manifest.json'
                assets['librustdesk.dll'] = b'synthetic-DLL-not-executed'
                assets['data/' + 'nested-plugin-segment/' * 3 + 'payload.bin'] = b'synthetic-nested-asset'
                gate = {'extension': 'sentra-peer-gate-v1', 'stock_cli_supported': False,
                    'source_revision': 'a' * 40, 'executable_sha256': hashlib.sha256(assets['component.exe']).hexdigest(),
                    'bundle_sha256': {key: hashlib.sha256(raw).hexdigest() for key, raw in assets.items()}}
                assets['bundle-manifest.json'] = json.dumps(gate).encode()
        assets[filename] = json.dumps(manifest).encode()
        files = []
        for relative, raw in assets.items():
            path = directory / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            files.append({'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest()})
        records[name] = {'materialized': True, 'validated': False, 'files': files}
    (root / 'runtime-components.json').write_text(json.dumps(records), encoding='utf-8')
    return root


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = fixture_staging(tmp_path / 'installed')
    resource = tmp_path / 'extracted'
    write_runtime_pins(root, resource)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(resource), raising=False)
    monkeypatch.setattr(sys, 'executable', str(root / 'sentra-canvas.exe'))
    for key in ('WASM_PATH', 'SBOM_PATH', 'WASM_SHA256', 'SBOM_SHA256'):
        monkeypatch.delenv('SENTRA_QUICKJS_' + key, raising=False)
    return root, resource


def test_source_mode_cannot_select_workspace_or_sibling_pins(installed, monkeypatch):
    root, resource = installed
    monkeypatch.setattr(sys, 'frozen', False)
    monkeypatch.chdir(resource)
    with pytest.raises(InstalledRuntimeUnavailable, match='source mode'):
        load_installed_component('quickjs')
    with pytest.raises(CodeModeUnavailable):
        load_artifact()


def test_frozen_quickjs_uses_installed_bytes_and_embedded_pins(installed):
    root, _ = installed
    artifact = load_artifact()
    assert artifact.wasm_path == str(root / 'runtime/quickjs/quickjs.wasm')
    assert artifact.wasm_sha256 == hashlib.sha256(Path(artifact.wasm_path).read_bytes()).hexdigest()
    assert artifact.sbom_sha256 == hashlib.sha256(Path(artifact.sbom_path).read_bytes()).hexdigest()
    # Adjacent editable metadata cannot re-pin changed bytes.
    Path(artifact.wasm_path).write_bytes(b'changed')
    records = json.loads((root / 'runtime-components.json').read_text())
    for row in records['quickjs']['files']:
        if row['path'].endswith('.wasm'):
            row['sha256'] = hashlib.sha256(b'changed').hexdigest()
    (root / 'runtime-components.json').write_text(json.dumps(records))
    with pytest.raises(CodeModeUnavailable):
        load_artifact()


def test_known_roles_are_readonly_and_bound_to_executable_directory(installed, tmp_path, monkeypatch):
    root, _ = installed
    selected = load_installed_component('rustdesk')
    assert selected.file('build_manifest').name == 'bundle-manifest.json'
    with pytest.raises(TypeError):
        selected.entrypoints['executable'] = 'outside.exe'
    with pytest.raises(ValueError):
        selected.file('../outside')
    other = tmp_path / 'another'; other.mkdir()
    monkeypatch.chdir(other)
    assert selected.file('executable') == root / 'runtime/rustdesk/component.exe'
    with pytest.raises(ValueError, match='bound'):
        selected.file('executable', maximum=1)


def test_explicit_operator_env_wins_and_partial_env_never_falls_back(installed, monkeypatch):
    monkeypatch.setenv('SENTRA_QUICKJS_WASM_PATH', 'operator-selected.wasm')
    with pytest.raises(CodeModeUnavailable, match='missing'):
        load_artifact()
    monkeypatch.setenv('SENTRA_QUICKJS_SBOM_PATH', 'operator-selected.json')
    monkeypatch.setenv('SENTRA_QUICKJS_WASM_SHA256', 'a' * 64)
    monkeypatch.setenv('SENTRA_QUICKJS_SBOM_SHA256', 'b' * 64)
    assert load_artifact() == load_artifact_from_env()
    assert load_artifact().wasm_path == 'operator-selected.wasm'


@pytest.mark.parametrize('replacement', ['runtime/quickjs/../escape', 'runtime/hcs/foreign.wasm',
    'runtime/quickjs//alias', 'runtime/quickjs/./alias', 'C:/outside', 'runtime/quickjs/file:stream',
    'runtime\\quickjs\\file', 'runtime/quickjs/file.'])
def test_portable_paths_cannot_escape_or_alias(installed, replacement):
    root, _ = installed
    pins = runtime_pins(root)
    pins['components']['quickjs']['files'][replacement] = 'a' * 64
    with pytest.raises(ValueError):
        validate_runtime_pins(pins)


def test_missing_components_duplicate_case_and_unlisted_entrypoints_fail(installed):
    root, _ = installed
    original = runtime_pins(root)
    missing = copy.deepcopy(original); del missing['components']['hcs']
    with pytest.raises(ValueError): validate_runtime_pins(missing)
    duplicate = copy.deepcopy(original)
    duplicate['components']['quickjs']['files']['runtime/quickjs/QUICKJS.WASM'] = 'a' * 64
    with pytest.raises(ValueError): validate_runtime_pins(duplicate)
    unlisted = copy.deepcopy(original)
    unlisted['components']['quickjs']['entrypoints']['wasm'] = 'runtime/quickjs/not-listed.wasm'
    with pytest.raises(ValueError): validate_runtime_pins(unlisted)


def test_builder_rejects_tampered_staging_without_writing_output(installed, tmp_path):
    root, _ = installed
    (root / 'runtime/hcs/component.exe').write_bytes(b'changed')
    output = tmp_path / 'uncreated'
    with pytest.raises(PermissionError, match='changed'):
        write_runtime_pins(root, output)
    assert not output.exists()


def test_missing_or_oversized_embedded_record_fails(installed):
    _, resource = installed
    path = resource / PIN_RESOURCE
    path.unlink()
    with pytest.raises(InstalledRuntimeUnavailable): load_installed_component('hcs')
    path.write_bytes(b' ' * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match='bound'): load_installed_component('hcs')


@pytest.mark.skipif(os.name != 'nt', reason='Windows junction behavior')
def test_installed_parent_junction_is_rejected(installed, tmp_path):
    root, _ = installed
    directory = root / 'runtime/hcs'
    outside = tmp_path / 'outside'
    directory.rename(outside)
    result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(directory), str(outside)],
        capture_output=True, timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr
    try:
        with pytest.raises(PermissionError, match='linked'):
            load_installed_component('hcs').file('executable')
    finally:
        directory.rmdir()


def test_packaging_context_embeds_pins_and_records_same_selection(installed, tmp_path, monkeypatch):
    from scripts.commander import build_windows as build
    root, _ = installed
    monkeypatch.setattr(build, 'LOCAL_BUILD_ROOT', tmp_path / 'build')
    monkeypatch.setattr(build, 'ROOT', tmp_path)
    monkeypatch.setattr(build, '_source_fingerprint', lambda: {'source': 'stable'})
    calls = []
    def fake_build(args, **kwargs):
        calls.append(args)
        name = args[args.index('--name') + 1]
        bundle = Path(args[args.index('--distpath') + 1]) / name
        runtime = bundle / ('_runtime_' + name)
        runtime.mkdir(parents=True)
        (bundle / (name + '.exe')).write_bytes(b'synthetic-not-run')
        (runtime / 'python312.dll').write_bytes(b'synthetic-runtime')
    monkeypatch.setattr(build, '_run', fake_build)
    dist = tmp_path / 'dist'; dist.mkdir()
    with build._RuntimeBinding(root, required=True):
        build._build('synthetic-component', 'synthetic.py', dist, tmp_path / 'work', tmp_path / 'spec')
        assert (dist / 'synthetic-component.exe').is_file()
        assert (dist / '_runtime_synthetic-component' / 'python312.dll').is_file()
        binding = dict(build._RUNTIME_BINDING.get())
        assert any(PIN_RESOURCE in arg for arg in calls[0])
        (dist / 'component.exe').write_bytes(b'synthetic-not-run')
        build._write_build_provenance(dist, 'test', ('component.exe',), {'source': 'stable'})
        proof = json.loads((dist / 'build-provenance-test.json').read_text())
        assert proof['runtime_pins_sha256'] == binding['sha256']
        (root / 'runtime/hcs/component.exe').write_bytes(b'changed-after-build')
        with pytest.raises(PermissionError):
            build._write_build_provenance(dist, 'changed', ('component.exe',), {'source': 'stable'})
        assert not (dist / 'build-provenance-changed.json').exists()
    assert build._RUNTIME_BINDING.get() is None
    assert not Path(binding['path']).exists()


def test_host_registers_installed_native_components_without_grants_or_execution(installed, tmp_path, monkeypatch):
    from sentra_mcp.services.control_plane import ControlPlaneService
    from sentra_mcp.services.context import ContextBusService
    from sentra_mcp.services.durable import DurableRunService
    from sentra_runtime.machine_host import MachineHost
    root, _ = installed
    state = tmp_path / 'central'; workspace = tmp_path / 'workspace'; workspace.mkdir()
    durable = DurableRunService(state)
    control = ControlPlaneService(durable, ContextBusService(state))
    host = MachineHost(control, owner='owner-native-installed')
    def no_grant(*args, **kwargs): raise AssertionError('Registration cannot create execution grants')
    monkeypatch.setattr(control.authorization, 'grant', no_grant)
    try:
        peer = {'enabled': True, 'runtime': 'installed', 'peer_alias': 'Fixture peer', 'peer_id': 'peer-123',
            'peer_key_sha256': 'b' * 64, 'rendezvous_server': 'fixture.invalid:21116',
            'rendezvous_public_key': 'synthetic-server-key', 'actions': ['session.list']}
        registered = host.configure_session(workspace_id='ws-native', workspace_root=str(workspace),
            agent_id='agent-rustdesk', kind='rustdesk', provider_config=peer)
        assert registered['registered'] is True and registered['grant_created'] is False
        assert registered['native_execution_verified'] is False
        record = next(row['configuration'] for row in host.configurations.entries() if row['machine_id'] == registered['machine_id'])
        persisted = record['provider_config']
        assert 'runtime' not in persisted
        assert persisted['executable_sha256'] == hashlib.sha256(b'synthetic-not-PE-not-executed').hexdigest()
        assert Path(persisted['executable']).is_relative_to(state)
        assert Path(persisted['build_manifest']).is_relative_to(state)
        from sentra_executors.remote_rustdesk import RustDeskPeerBinding, RustDeskNativeBackend
        from sentra_executors.identity_sessions import SessionJournal
        from sentra_executors.rpa import AuthorizedPaths
        private = Path(persisted['build_manifest']).parent
        runtime = tmp_path / 'probe-runtime'; runtime.mkdir()
        binding_fields = {key: value for key, value in persisted.items() if key not in {'enabled', 'source_revision'}}
        binding = RustDeskPeerBinding(capability_id='rustdesk:session', runtime_root=str(runtime),
            paths=AuthorizedPaths((str(workspace),), (str(workspace),)),
            manifest_paths=AuthorizedPaths((str(private),)), **binding_fields)
        journal = SessionJournal(str(runtime / 'sessions.sqlite3'), AuthorizedPaths((str(runtime),), (str(runtime),)))
        gate = RustDeskNativeBackend(journal)._build(binding)
        assert gate['source_revision'] == 'a' * 40
        if os.name == 'nt':
            assert max(len(str(private / relative)) for relative in gate['bundle_sha256']) > 260
        # Supporting internal Win32 long paths must not admit raw device/ADS input.
        for untrusted in ('\\\\?\\' + str(private / 'component.exe'), str(private / 'component.exe') + ':stream'):
            with pytest.raises(ValueError):
                binding.build_paths.resolve(untrusted)
        prepared = workspace / 'prepared.json'; prepared.write_text('{}')
        hcs = {'enabled': True, 'runtime': 'installed', 'host_read_roots': [str(workspace)], 'binding': {
            'container_id': 'sentra-lab-fixture', 'prepared_config': str(prepared),
            'config_sha256': hashlib.sha256(prepared.read_bytes()).hexdigest(), 'actions': ['session.list']}}
        registered_hcs = host.configure_executor(workspace_id='ws-native', workspace_root=str(workspace),
            agent_id='agent-hcs', kind='windows_hcs_native', provider_config=hcs)
        assert registered_hcs['registered'] is True and registered_hcs['grant_created'] is False
        persisted_hcs = next(row['configuration']['provider_config'] for row in host.configurations.entries()
            if row['machine_id'] == registered_hcs['machine_id'])
        assert 'runtime' not in persisted_hcs
        assert persisted_hcs['binding']['bridge_executable'] == str(root / 'runtime/hcs/component.exe')
        with control.store.connect('durable') as db:
            assert db.execute('SELECT COUNT(*) FROM operations').fetchone()[0] == 0
    finally:
        host.close(); durable.close()


@pytest.mark.parametrize('runtime', ['installed', {}, True])
def test_installed_native_selection_rejects_pin_override_or_unknown_mode(installed, tmp_path, runtime):
    from sentra_mcp.services.control_plane import ControlPlaneService
    from sentra_mcp.services.context import ContextBusService
    from sentra_mcp.services.durable import DurableRunService
    from sentra_runtime.machine_host import MachineHost
    state = tmp_path / 'central'; workspace = tmp_path / 'workspace'; workspace.mkdir()
    durable = DurableRunService(state); control = ControlPlaneService(durable, ContextBusService(state))
    host = MachineHost(control, owner='owner-native-installed')
    try:
        with pytest.raises(ValueError):
            host.configure_session(workspace_id='ws', workspace_root=str(workspace), agent_id='agent', kind='rustdesk',
                provider_config={'enabled': True, 'runtime': runtime, 'executable': 'arbitrary.exe'})
        with pytest.raises(ValueError):
            host.configure_executor(workspace_id='ws', workspace_root=str(workspace), agent_id='agent', kind='windows_hcs_native',
                provider_config={'enabled': True, 'runtime': runtime, 'binding': {'bridge_executable': 'arbitrary.exe'}})
    finally:
        host.close(); durable.close()
