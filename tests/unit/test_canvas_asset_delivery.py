import gzip
from http.client import HTTPResponse
import socket
import time
import urllib.request

from test_sentra_runtime_canvas_center_http import running_canvas
from sentra_canvas import __main__ as http


def test_local_assets_negotiate_gzip_with_exact_lengths_and_content(tmp_path,monkeypatch):
    static=tmp_path/'static';assets=static/'desktop-assets';assets.mkdir(parents=True)
    text=b'.opendots-shell{display:flex;color:#ddd}'*2000
    (assets/'desktop.css').write_bytes(text)
    monkeypatch.setattr(http,'STATIC',static)
    with running_canvas(tmp_path) as (_app,server):
        url=f'http://127.0.0.1:{server.server_port}/desktop-assets/desktop.css'
        for encoding in ['gzip','identity','gzip;q=0']:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'Accept-Encoding':encoding}),timeout=5) as response:
                body=response.read()
                assert int(response.headers['Content-Length'])==len(body)
                assert response.headers['Content-Type']=='text/css'
                assert response.headers['Vary']=='Accept-Encoding'
                if encoding=='gzip':
                    assert response.headers['Content-Encoding']=='gzip'
                    assert gzip.decompress(body)==text and len(body)<len(text)
                else:assert not response.headers.get('Content-Encoding') and body==text


def test_slow_chromium_reader_does_not_inherit_the_five_second_request_deadline(tmp_path,monkeypatch):
    assets=tmp_path/'static/desktop-assets';assets.mkdir(parents=True)
    payload=b'x'*(1024*1024);(assets/'desktop.js').write_bytes(payload)
    monkeypatch.setattr(http,'STATIC',assets.parent)
    original=http.CanvasServer.get_request
    def bounded_send(server):
        connection,address=original(server)
        connection.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,4096)
        return connection,address
    monkeypatch.setattr(http.CanvasServer,'get_request',bounded_send)
    with running_canvas(tmp_path) as (_app,server):
        with socket.socket() as connection:
            connection.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,65536)
            connection.settimeout(15);connection.connect(('127.0.0.1',server.server_port))
            connection.sendall(f'GET /desktop-assets/desktop.js HTTP/1.1\r\nHost: 127.0.0.1:{server.server_port}\r\nConnection: close\r\n\r\n'.encode())
            response=HTTPResponse(connection);response.begin()
            time.sleep(6.2)  # Deliberate receiver backpressure, beyond request parsing's deadline.
            assert response.status==200 and response.read()==payload
