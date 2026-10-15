"""Verify the SENTRA loopback SSE socket disables Nagle in actual TCP."""
from http.server import ThreadingHTTPServer
from threading import Thread
import http.client
import socket

from sentra_model_gateway.gateway import GatewayHandler


def test_loopback_gateway_disables_nagle_on_real_client_socket():
    class NagleProbe(GatewayHandler):
        def do_GET(self):
            enabled = self.connection.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
            body = str(enabled).encode("ascii")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), NagleProbe)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
        try:
            client.request("GET", "/")
            response = client.getresponse()
            assert response.status == 200
            assert response.read() == b"1"
        finally:
            client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
