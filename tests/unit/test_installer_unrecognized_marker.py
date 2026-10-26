import pytest

from sentra_remote import installer_recovery as recovery


@pytest.mark.parametrize('payload_collision', [False, True])
@pytest.mark.parametrize('content', ['{"product":"another-app","note":"user data"}', '{broken'])
def test_clean_never_moves_an_unrecognized_marker(tmp_path, monkeypatch, content, payload_collision):
    from sentra_remote import app_exit_update
    monkeypatch.setattr(app_exit_update, 'assert_installation_offline', lambda _: None)
    app = tmp_path / 'app'; app.mkdir()
    marker = app / '.sentra-install.json'; marker.write_text(content)
    if payload_collision:
        (app / 'sentra-canvas.exe').write_bytes(b'unowned executable')
    with pytest.raises(recovery.InstallationRecoveryError, match='unowned_clean_conflict'):
        recovery.prepare_clean_install(app, tmp_path / 'state', ('sentra-canvas.exe',),
                                       incoming=['sentra-canvas.exe'])
    assert marker.read_text() == content
    if payload_collision:
        assert (app / 'sentra-canvas.exe').read_bytes() == b'unowned executable'
    assert not list(tmp_path.glob('.sentra-clean-*'))
