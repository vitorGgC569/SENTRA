"""Transport failures release the owned socket and admission slot without replay."""
import ssl
from types import SimpleNamespace

import pytest

from sentra_federation.errors import FederationUncertain
from sentra_federation.gateway import PeerGateway


class Client:
    def __init__(self):
        self.closed = 0
        self.timeout = None
    def close(self): self.closed += 1
    def setsockopt(self, *args): pass
    def settimeout(self, value): self.timeout = value


@pytest.mark.parametrize("failure", [ssl.SSLError("TLS rejected"), TimeoutError("handshake deadline"), ConnectionResetError("peer reset")])
def test_client_handshake_failure_closes_socket_without_retry(monkeypatch, failure):
    gateway = PeerGateway.__new__(PeerGateway)
    gateway.drop_before_receipt = False
    client, calls = Client(), []
    def connect(*args, **kwargs):
        calls.append((args, kwargs))
        return client
    def handshake(*args, **kwargs): raise failure
    gateway._client_context = lambda pem: SimpleNamespace(wrap_socket=handshake)
    monkeypatch.setattr("sentra_federation.gateway.socket.create_connection", connect)
    with pytest.raises(FederationUncertain, match="link lost before receipt"):
        gateway._request("127.0.0.1", 12345, {"kind":"hello"}, pinned_pem=None)
    assert client.closed == 1 and len(calls) == 1


@pytest.mark.parametrize("failure", [ssl.SSLError("TLS rejected"), TimeoutError("handshake deadline"), ConnectionResetError("peer reset")])
def test_server_handshake_failure_is_bounded_and_releases_slot(failure):
    gateway = PeerGateway.__new__(PeerGateway)
    released = []
    gateway._slots = SimpleNamespace(release=lambda: released.append(True))
    def handshake(*args, **kwargs): raise failure
    gateway._server_ctx = SimpleNamespace(wrap_socket=handshake)
    client = Client()
    gateway._handle(client)
    assert client.timeout == 5 and client.closed == 1 and released == [True]
