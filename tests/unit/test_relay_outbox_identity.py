import hashlib
from pathlib import Path

from native_bridge.job_store import JobStore
from native_bridge.settings import relay_settings
from native_bridge.relay import RelayState
from sentra_canvas.shell_optional import load_shell_configuration


def test_standalone_and_canvas_choose_same_outbox_and_pairing_secret(tmp_path, monkeypatch):
    monkeypatch.delenv('OMA_RELAY_TOKEN', raising=False)
    monkeypatch.delenv('SENTRA_SHELL_CONFIG_FILE', raising=False)
    legacy = tmp_path / '.oma'
    legacy.mkdir()
    (legacy / 'relay-token').write_text('l' * 40)
    (legacy / 'relay.sqlite3').write_bytes(b'legacy-history-must-remain')
    token, token_path, database = relay_settings(tmp_path)
    config = load_shell_configuration(root=tmp_path)['web_relay']
    assert token == 'l' * 40
    assert token_path == Path(config['token_file']) == tmp_path / '.sentra/browser/relay-token'
    assert database == tmp_path / '.sentra/browser/relay.sqlite3'
    assert (legacy / 'relay.sqlite3').read_bytes() == b'legacy-history-must-remain'
    assert not database.exists()


def test_existing_canonical_secret_wins_over_legacy(tmp_path, monkeypatch):
    monkeypatch.delenv('OMA_RELAY_TOKEN', raising=False)
    monkeypatch.delenv('SENTRA_SHELL_CONFIG_FILE', raising=False)
    canonical = tmp_path / '.sentra/browser'
    canonical.mkdir(parents=True)
    (canonical / 'relay-token').write_text('c' * 40)
    legacy = tmp_path / '.oma'
    legacy.mkdir()
    (legacy / 'relay-token').write_text('l' * 40)
    token, path, _ = relay_settings(tmp_path)
    assert token == 'c' * 40
    assert Path(load_shell_configuration(root=tmp_path)['web_relay']['token_file']) == path


def test_health_identity_distinguishes_real_outboxes_without_exposing_paths(tmp_path):
    first, second = JobStore(tmp_path / 'canvas.sqlite3'), JobStore(tmp_path / 'legacy.sqlite3')
    memory = JobStore()
    try:
        expected = hashlib.sha256(str((tmp_path / 'canvas.sqlite3').resolve()).casefold().encode()).hexdigest()
        assert first.namespace_identity() == expected
        assert first.namespace_identity() != second.namespace_identity()
        assert memory.namespace_identity() is None
    finally:
        first.close()
        second.close()
        memory.close()


def test_extension_identity_comes_from_authenticated_origin_not_status_payload():
    state = RelayState()
    try:
        state.mark_extension({'extension_id':'b'*32}, extension_id='a'*32)
        assert state.extension_status()['extension_id'] == 'a'*32
        state.mark_extension({'extension_id':'c'*32})
        assert state.extension_status()['extension_id'] == 'a'*32
    finally:
        state.close()
