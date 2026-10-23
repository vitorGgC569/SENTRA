"""Canvas must keep peer tasks attached to their still-open authority on shutdown."""
from types import SimpleNamespace

import pytest

from sentra_canvas.service import Canvas
from sentra_canvas import shell_federation
from sentra_federation.errors import FederationUncertain


def test_canvas_retains_databases_and_peer_registration_until_drain_completes(tmp_path):
    app = Canvas(tmp_path / 'root', state_dir=tmp_path / 'state', principal='owner')
    workspace = app.create_workspace('Drain')['id']
    control = app._shell_service()
    calls = []
    gateway = SimpleNamespace(refuse=True)
    def close():
        calls.append(app.store.workspace(workspace)['id'])
        assert control.durable.db.execute('SELECT 1').fetchone()[0] == 1
        if gateway.refuse:raise FederationUncertain('peer task still draining')
    gateway.close = close
    session = SimpleNamespace(gateway=gateway)
    app._federation_gateways = {workspace: session}
    try:
        with pytest.raises(FederationUncertain, match='still draining'):app.shutdown()
        assert not app._closed and app._closing
        assert app._federation_gateways[workspace] is session
        assert app.store.workspace(workspace)['id'] == workspace
        assert control.durable.db.execute('SELECT 1').fetchone()[0] == 1
        gateway.refuse = False
        app.shutdown()
        assert app._closed and not app._federation_gateways
        assert calls == [workspace, workspace]
    finally:
        gateway.refuse = False
        app.shutdown()


def test_network_disable_retains_session_when_drain_is_uncertain(tmp_path, monkeypatch):
    app = Canvas(tmp_path / 'root', state_dir=tmp_path / 'state', principal='owner')
    workspace = app.create_workspace('Disable')['id']
    gateway = SimpleNamespace(refuse=True)
    def close():
        if gateway.refuse:raise FederationUncertain('still draining')
    gateway.close = close
    session = SimpleNamespace(gateway=gateway)
    app._federation_gateways = {workspace: session}
    saves = []
    monkeypatch.setattr(shell_federation, '_remember', lambda *args, enabled: saves.append(enabled))
    try:
        with pytest.raises(FederationUncertain):shell_federation._disable(app, workspace)
        assert app._federation_gateways[workspace] is session
        gateway.refuse = False
        result = shell_federation._disable(app, workspace)
        assert result['enabled'] is False and not app._federation_gateways
        assert saves == [False, False]
    finally:
        gateway.refuse = False
        app.shutdown()


def test_network_enable_refuses_shutdown_before_identity_or_listener_creation(tmp_path, monkeypatch):
    app = Canvas(tmp_path / 'root', state_dir=tmp_path / 'state', principal='owner')
    try:
        app._closing = True
        monkeypatch.setattr(shell_federation, '_enable_locked', lambda *args: pytest.fail('listener created during shutdown'))
        with pytest.raises(RuntimeError, match='closing'):shell_federation._enable(app, 'unused', {}, {})
    finally:app.shutdown()
