"""Public LAN metadata and durable host identity; no browser cookies or account tokens."""
import base64
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import tempfile
import urllib.request
from urllib.parse import urlsplit

from sentra_remote.secrets import protect_secret, unprotect_secret


def local_ipv4(value, *, loopback=True):
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError):
        return False
    return ((loopback and address.is_loopback) or any(address in network for network in
        (ipaddress.IPv4Network('10.0.0.0/8'), ipaddress.IPv4Network('172.16.0.0/12'),
         ipaddress.IPv4Network('192.168.0.0/16'))))


def atomic_json(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def host_secret(state):
    """A new pairing, IP or broker never rotates this key. Damaged storage fails closed."""
    path = Path(state) / 'mobile-key.protected'
    if not path.exists():
        protected = protect_secret(base64.b64encode(secrets.token_bytes(32)).decode())
        if not protected.startswith(('dpapi:', 'keyring:')):
            raise RuntimeError('OS protected mobile identity required')
        atomic_json(path, {'schema': 1, 'protected_key': protected})
    raw = path.read_text(encoding='utf-8')
    # Adopt the existing protected key in place; never mint a replacement identity.
    stored = json.loads(raw) if raw.startswith('{') else {'schema': 1, 'protected_key': raw}
    if stored.get('schema') != 1 or not stored.get('protected_key', '').startswith(('dpapi:', 'keyring:')):
        raise ValueError('Mobile host identity is invalid; recover its protected key')
    key = unprotect_secret(stored['protected_key'])
    if len(base64.b64decode(key, validate=True)) != 32:
        raise ValueError('Mobile host identity is invalid; recover its protected key')
    return key


def host_status(state):
    """Verify the advertised listener. No credential is sent during this probe."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        path = Path(state) / 'mobile-host.json'
        if path.stat().st_size > 16384:
            raise ValueError('descriptor too large')
        host = json.loads(path.read_text(encoding='utf-8'))
        if len(base64.b64decode(host['public_key'], validate=True)) != 32:
            raise ValueError('invalid host identity')
        endpoint = urlsplit(host['endpoint'])
        if (endpoint.scheme != 'ws' or not local_ipv4(endpoint.hostname) or not endpoint.port
                or endpoint.path != '/sentra/mobile/v1' or endpoint.username or endpoint.password
                or endpoint.query or endpoint.fragment):
            raise ValueError('invalid local endpoint')
        health_url = f'http://{endpoint.hostname}:{endpoint.port}/sentra/mobile/health'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(health_url, timeout=1) as response:
            health = json.loads(response.read(8192))
        if (health.get('ok') is not True or health.get('protocol_version') != 1
                or health.get('endpoint') != host['endpoint']
                or not hmac.compare_digest(health.get('public_key', ''), host['public_key'])):
            raise ValueError('listener identity changed')
        loopback = ipaddress.ip_address(endpoint.hostname).is_loopback
        return {'available': True, 'status': 'ready' if health.get('broker_available') else 'broker_restarting',
                'endpoint': host['endpoint'], 'public_key': host['public_key'],
                'addresses': [endpoint.hostname], 'lan': not loopback,
                'protocol_version': 1, 'reason': 'Loopback: acessível apenas neste computador.' if loopback else
                'Conecte o celular à mesma rede. A conexão Wi-Fi será conferida no aparelho.'}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return {'available': False, 'status': 'unavailable', 'lan': False,
                'reason': 'Gateway LAN indisponível ou identidade não confirmada.'}
