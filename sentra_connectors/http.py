"""Bounded direct HTTPS with fixed provider origins; no redirects/proxies/retries."""
from __future__ import annotations
from dataclasses import dataclass
import http.client
import ipaddress
import json
import socket
import ssl
import queue
import threading
import time
from urllib.parse import urlsplit

HOSTS = frozenset({'api.github.com', 'github.com', 'oauth2.googleapis.com', 'www.googleapis.com'})
MAX_BYTES = 2 * 1024 * 1024
_DNS_SLOTS=threading.BoundedSemaphore(8)


def _resolve(host,timeout):
    # getaddrinfo has no portable deadline. Bound the waiter and the number of
    # outstanding daemon resolvers; an abandoned lookup never opens a socket.
    if not _DNS_SLOTS.acquire(blocking=False):
        raise ConnectorError('CONNECTOR_DNS_CAPACITY')
    result=queue.Queue(maxsize=1)
    def resolve():
        try:
            result.put((True,socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))
        except Exception:
            result.put((False,None))
        finally:
            _DNS_SLOTS.release()
    try:
        threading.Thread(target=resolve,daemon=True,name='sentra-connector-dns').start()
    except Exception:
        _DNS_SLOTS.release();raise ConnectorError('CONNECTOR_TRANSPORT_UNCONFIRMED') from None
    try:ok,value=result.get(timeout=timeout)
    except queue.Empty:raise ConnectorError('CONNECTOR_TRANSPORT_UNCONFIRMED') from None
    if not ok:raise ConnectorError('CONNECTOR_TRANSPORT_UNCONFIRMED')
    return value


class ConnectorError(RuntimeError):
    """Stable public reason; provider bodies and credentials never enter errors."""


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: dict
    body: bytes
    # Set only after this transport received a response over verified TLS.
    # Synthetic transports leave it false; no account homologation is implied.
    tls_response_verified: bool = False

    def json(self):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ConnectorError('CONNECTOR_AMBIGUOUS_JSON')
                result[key] = value
            return result
        try:
            return json.loads(self.body.decode('utf-8'), object_pairs_hook=unique,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except ConnectorError:
            raise
        except (UnicodeError, ValueError):
            raise ConnectorError('CONNECTOR_INVALID_JSON') from None


class PinnedConnectorHTTPS:

    def __init__(self, *, timeout=10):
        if type(timeout) not in (int, float) or not 0 < timeout <= 15:
            raise ValueError('invalid connector timeout')
        self.timeout = timeout

    def request(self, method, url, *, headers=None, body=None, max_bytes=MAX_BYTES):
        part = urlsplit(url)
        try:
            port = part.port
        except ValueError:
            raise ConnectorError('CONNECTOR_ORIGIN_DENIED') from None
        if (part.scheme != 'https' or part.hostname not in HOSTS or port not in (None, 443)
                or part.username or part.password or part.fragment or not part.path.startswith('/')
                or method not in {'GET', 'POST', 'DELETE'} or type(max_bytes) is not int
                or not 0 < max_bytes <= MAX_BYTES):
            raise ConnectorError('CONNECTOR_ORIGIN_DENIED')
        if body is not None and (not isinstance(body, bytes) or len(body) > 16384):
            raise ConnectorError('CONNECTOR_REQUEST_UNBOUNDED')
        connection = None; watchdog=None; active_socket=[None]
        deadline=time.monotonic()+self.timeout
        def remaining():
            value=deadline-time.monotonic()
            if value<=0:raise ConnectorError('CONNECTOR_TRANSPORT_UNCONFIRMED')
            return value
        def interrupt():
            sock=active_socket[0]
            if sock is not None:
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                try:sock.close()
                except OSError:pass
        try:
            addresses = _resolve(part.hostname,remaining())
            if not addresses or len(addresses) > 32 or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in addresses):
                raise ConnectorError('CONNECTOR_DNS_DENIED')
            connection = http.client.HTTPSConnection(part.hostname, 443, context=ssl.create_default_context(), timeout=remaining())
            watchdog=threading.Timer(remaining(),interrupt);watchdog.daemon=True;watchdog.start()
            sock = socket.create_connection((addresses[0][4][0], 443), timeout=remaining());active_socket[0]=sock
            try:
                connection.sock = connection._context.wrap_socket(sock, server_hostname=part.hostname)
                active_socket[0]=connection.sock
            except BaseException:
                sock.close()
                raise
            request_headers = {'Accept': 'application/json', 'User-Agent': 'SENTRA-Connectors/1', 'Cache-Control': 'no-store', **(headers or {})}
            connection.request(method, part.path + ('?' + part.query if part.query else ''), body=body, headers=request_headers)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ConnectorError('CONNECTOR_REDIRECT_DENIED')
            if response.getheader('Content-Encoding', 'identity').lower() not in {'identity', ''}:
                raise ConnectorError('CONNECTOR_ENCODING_DENIED')
            lengths=[value for key,value in response.getheaders() if key.lower()=='content-length']
            transfer=response.getheader('Transfer-Encoding','').strip().lower()
            if (len(lengths)>1 or transfer not in {'','chunked'} or transfer and lengths
                    or lengths and (not lengths[0].isascii() or not lengths[0].isdigit())):
                raise ConnectorError('CONNECTOR_FRAMING_INVALID')
            if lengths and int(lengths[0])>max_bytes:
                raise ConnectorError('CONNECTOR_RESPONSE_UNBOUNDED')
            chunks=[];size=0
            while True:
                remaining()
                piece=response.read1(min(65536,max_bytes+1-size))
                if not piece:break
                chunks.append(piece);size+=len(piece)
                if size>max_bytes:raise ConnectorError('CONNECTOR_RESPONSE_UNBOUNDED')
            payload=b''.join(chunks)
            remaining()
            if response.length not in (None,0):
                raise ConnectorError('CONNECTOR_TRANSPORT_UNCONFIRMED')
            if len(payload) > max_bytes:
                raise ConnectorError('CONNECTOR_RESPONSE_UNBOUNDED')
            return HTTPResponse(response.status, {key.lower(): value for key, value in response.getheaders()}, payload,
                                tls_response_verified=True)
        except ConnectorError:
            raise
        except Exception:
            raise ConnectorError('CONNECTOR_TRANSPORT_UNCONFIRMED') from None
        finally:
            if watchdog is not None:watchdog.cancel()
            if connection is not None:
                connection.close()


def require_success(response):
    if not isinstance(response, HTTPResponse) or len(response.body) > MAX_BYTES:
        raise ConnectorError('CONNECTOR_INVALID_RESPONSE')
    if response.status == 401:
        raise ConnectorError('CONNECTOR_AUTHENTICATION_EXPIRED_OR_REVOKED')
    if response.status == 403:
        raise ConnectorError('CONNECTOR_PERMISSION_DENIED')
    if response.status == 404:
        raise ConnectorError('CONNECTOR_RESOURCE_UNAVAILABLE')
    if response.status == 429:
        raise ConnectorError('CONNECTOR_RATE_LIMITED')
    if not 200 <= response.status < 300:
        raise ConnectorError('CONNECTOR_UPSTREAM_UNAVAILABLE')
    return response
