"""Production transport on real local TLS; fixture CA/DNS, never provider accounts."""
from datetime import datetime,timedelta,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import socket
import ssl
import threading
import time
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import sentra_connectors.http as http


@pytest.fixture
def wire(tmp_path,monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'api.github.com')])
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc)+timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('api.github.com')]),critical=False)
        .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256()))
    pem=tmp_path/'fixture-cert.pem';pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private=tmp_path/'fixture-key.pem';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    state={'mode':'normal','requests':[],'sni':[]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_GET(self):
            state['requests'].append({'path':self.path,'authorization':self.headers.get('Authorization'),'user_agent':self.headers.get('User-Agent')})
            mode=state['mode']
            try:
                self.send_response(302 if mode=='redirect' else 200)
                if mode=='redirect':self.send_header('Location','https://attacker.invalid/do-not-follow')
                if mode=='compressed':self.send_header('Content-Encoding','gzip')
                self.send_header('Content-Length','50' if mode in {'truncated','trickle'} else '5')
                if mode=='duplicate-length':self.send_header('Content-Length','6')
                self.end_headers()
                if mode=='trickle':
                    for _ in range(50):self.wfile.write(b'a');self.wfile.flush();time.sleep(.08)
                else:self.wfile.write(b'hello')
            except (OSError,ssl.SSLError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_context.load_cert_chain(pem,private)
    server_context.set_servername_callback(lambda _socket,name,_context:state['sni'].append(name))
    server.socket=server_context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    client_context=ssl.create_default_context(cafile=str(pem))
    resolve,connect=socket.getaddrinfo,socket.create_connection
    monkeypatch.setattr(http.socket,'getaddrinfo',lambda host,port,*args,**kwargs:
        [(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('1.1.1.1',443))] if host in http.HOSTS else resolve(host,port,*args,**kwargs))
    monkeypatch.setattr(http.socket,'create_connection',lambda address,*args,**kwargs:
        connect(('127.0.0.1',server.server_port) if address==('1.1.1.1',443) else address,*args,**kwargs))
    monkeypatch.setattr(http.ssl,'create_default_context',lambda:client_context)
    try:yield state
    finally:server.shutdown();server.server_close();thread.join(timeout=3)


def test_real_tls_verifies_sni_certificate_and_bounded_payload(wire):
    result=http.PinnedConnectorHTTPS(timeout=1).request('GET','https://api.github.com/repos/qa/repo',headers={'Authorization':'Bearer synthetic-wire-only'})
    assert result.body==b'hello' and result.tls_response_verified is True
    assert wire['sni']==['api.github.com']
    assert wire['requests']==[{'path':'/repos/qa/repo','authorization':'Bearer synthetic-wire-only','user_agent':'SENTRA-Connectors/1'}]


@pytest.mark.parametrize('mode,reason',[('redirect','REDIRECT_DENIED'),('compressed','ENCODING_DENIED'),
    ('duplicate-length','FRAMING_INVALID'),('truncated','TRANSPORT_UNCONFIRMED')])
def test_tls_failures_are_not_followed_or_retried(wire,mode,reason):
    wire['mode']=mode
    with pytest.raises(http.ConnectorError,match='CONNECTOR_'+reason):
        http.PinnedConnectorHTTPS(timeout=1).request('GET','https://api.github.com/repos/qa/repo')
    assert len(wire['requests'])==1


def test_trickled_tls_body_cannot_extend_absolute_deadline(wire):
    wire['mode']='trickle';started=time.monotonic()
    with pytest.raises(http.ConnectorError,match='TRANSPORT_UNCONFIRMED'):
        http.PinnedConnectorHTTPS(timeout=.3).request('GET','https://api.github.com/repos/qa/repo')
    assert time.monotonic()-started<1.0
    assert len(wire['requests'])==1


def test_blocked_dns_waiter_has_a_deadline_and_never_opens_socket(monkeypatch):
    release=threading.Event();calls=[]
    monkeypatch.setattr(http.socket,'getaddrinfo',lambda *args,**kwargs:release.wait(2) or [])
    monkeypatch.setattr(http.socket,'create_connection',lambda *args,**kwargs:calls.append(args))
    started=time.monotonic()
    try:
        with pytest.raises(http.ConnectorError,match='TRANSPORT_UNCONFIRMED'):
            http.PinnedConnectorHTTPS(timeout=.1).request('GET','https://api.github.com/repos/qa/repo')
        assert time.monotonic()-started<.7 and not calls
    finally:release.set()


def test_tls_hostname_mismatch_prevents_authorization_header_delivery(wire):
    with pytest.raises(http.ConnectorError,match='TRANSPORT_UNCONFIRMED'):
        http.PinnedConnectorHTTPS(timeout=1).request('GET','https://github.com/login/device',
                                                  headers={'Authorization':'Bearer synthetic-not-delivered'})
    assert wire['requests']==[] and wire['sni']==['github.com']


def test_untrusted_tls_certificate_prevents_http_request(wire,monkeypatch):
    untrusted=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    monkeypatch.setattr(http.ssl,'create_default_context',lambda:untrusted)
    with pytest.raises(http.ConnectorError,match='TRANSPORT_UNCONFIRMED'):
        http.PinnedConnectorHTTPS(timeout=1).request('GET','https://api.github.com/repos/qa/repo')
    assert wire['requests']==[]
