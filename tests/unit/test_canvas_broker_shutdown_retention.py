"""Never retain an endpoint for an HTTP server that has already closed."""
import pytest

from sentra_canvas import __main__ as entry, broker


@pytest.mark.parametrize('fails', [False, True])
def test_closed_broker_endpoint_is_removed_even_when_shutdown_is_incomplete(tmp_path, monkeypatch, fails):
    calls = []
    class App:
        def __init__(self, *args, **kwargs):
            pass
        def shutdown(self):
            calls.append('shutdown')
            if fails:
                raise RuntimeError('catalog readers have not stopped; machine host retained')
    class Server:
        server_port = 12345
        def __init__(self, app, port):
            self.canvas = app
        def serve_forever(self, **kwargs):
            pass
        def server_close(self):
            calls.append('server_close')
    monkeypatch.setattr(entry, 'Canvas', App)
    monkeypatch.setattr(entry, 'CanvasServer', Server)
    monkeypatch.setattr(broker, 'publish_endpoint', lambda server: calls.append('publish'))
    monkeypatch.setattr(broker, 'remove_endpoint', lambda server: calls.append('remove'))
    args = ['--root', str(tmp_path), '--state-dir', str(tmp_path / 'state'), '--broker']
    if fails:
        with pytest.raises(RuntimeError, match='catalog readers'):
            entry.main(args)
        assert calls == ['publish', 'server_close', 'shutdown', 'remove']
    else:
        assert entry.main(args) == 0
        assert calls == ['publish', 'server_close', 'shutdown', 'remove']
