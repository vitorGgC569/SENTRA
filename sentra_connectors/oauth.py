"""Google desktop PKCE and GitHub device flow; explicit host consent, no UI secrets."""
from __future__ import annotations
import base64
import hashlib
import json
import re
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit
from .accounts import AccountBinding,normalized_tokens,validate_consent,validate_returned_scopes
from .http import ConnectorError, PinnedConnectorHTTPS, require_success

GOOGLE_SCOPE = 'https://www.googleapis.com/auth/drive.file'


class ConnectorOAuth:
    def __init__(self, accounts, *, transport=None, clock=time.time):
        self.accounts = accounts
        self.transport = transport or PinnedConnectorHTTPS()
        self.clock, self.pending, self.lock = clock, {}, threading.RLock()

    def _post(self, url, fields):
        return self.transport.request('POST', url, headers={'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'}, body=urlencode(fields).encode('ascii'), max_bytes=16384)

    def begin(self, binding: AccountBinding, *, client_id, resources, redirect_uri=None, scopes=None, approved=False):
        if approved is not True:
            raise ConnectorError('CONNECTOR_HUMAN_CONSENT_REQUIRED')
        identity = binding.key()
        if not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}', client_id):
            raise ConnectorError('CONNECTOR_OAUTH_CLIENT_INVALID')
        scopes = (('public_repo',) if binding.provider == 'github' else (GOOGLE_SCOPE,)) if scopes is None else scopes
        validate_consent(binding.provider,resources,scopes)
        with self.lock:
            self.pending = {key: value for key, value in self.pending.items() if value['expires'] > self.clock()}
            if len(self.pending) >= 32:
                raise ConnectorError('CONNECTOR_OAUTH_CAPACITY')
            state = secrets.token_urlsafe(32)
            entry = {'identity': identity, 'client_id': client_id, 'resources': resources, 'scopes': scopes, 'expires': self.clock() + 300, 'state': 'PENDING'}
            if binding.provider == 'google-drive':
                part = urlsplit(redirect_uri or '')
                try:
                    valid_port = part.port is not None and 1 <= part.port <= 65535
                except ValueError:
                    valid_port = False
                if part.scheme != 'http' or part.hostname not in {'127.0.0.1', '::1'} or not valid_port or part.username or part.password or part.query or part.fragment or part.path != '/callback':
                    raise ConnectorError('CONNECTOR_LOOPBACK_CALLBACK_REQUIRED')
                verifier = secrets.token_urlsafe(64)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                entry.update(verifier=verifier, redirect_uri=redirect_uri)
                self.pending[state] = entry
                query = urlencode({'response_type': 'code', 'client_id': client_id, 'redirect_uri': redirect_uri, 'scope': ' '.join(scopes), 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256', 'access_type': 'offline', 'prompt': 'consent'})
                return {'flow_id': state, 'authorization_url': 'https://accounts.google.com/o/oauth2/v2/auth?' + query, 'expires_in': 300, 'credential_exposed': False}
            # Reserve before the non-idempotent device-code request. An ambiguous
            # response cannot trigger another request with the same flow identity.
            entry['state'] = 'STARTING'
            self.pending[state] = entry
        try:
            value = require_success(self._post('https://github.com/login/device/code', {'client_id': client_id, 'scope': ' '.join(scopes)})).json()
            if (not isinstance(value, dict) or not isinstance(value.get('device_code'), str) or not 1 <= len(value['device_code']) <= 2048
                    or not re.fullmatch(r'[A-Za-z0-9-]{1,32}', value.get('user_code', ''))
                    or value.get('verification_uri') != 'https://github.com/login/device'
                    or type(value.get('expires_in')) is not int or not 1 <= value['expires_in'] <= 1800
                    or type(value.get('interval', 5)) is not int or not 1 <= value.get('interval', 5) <= 60):
                raise ConnectorError('CONNECTOR_DEVICE_RESPONSE_INVALID')
            with self.lock:
                entry.update(device_code=value['device_code'], expires=self.clock() + value['expires_in'], interval=value.get('interval', 5), next_poll=self.clock() + value.get('interval', 5), state='PENDING')
            return {'flow_id': state, 'verification_uri': value['verification_uri'], 'user_code': value['user_code'], 'expires_in': value['expires_in'], 'poll_after': entry['interval'], 'credential_exposed': False}
        except Exception:
            entry['state'] = 'UNCERTAIN'
            raise ConnectorError('CONNECTOR_OAUTH_START_UNCONFIRMED') from None

    def _claim(self, binding, flow_id):
        with self.lock:
            entry = self.pending.get(flow_id) if isinstance(flow_id, str) else None
            if not entry or entry['identity'] != binding.key() or entry['expires'] <= self.clock() or entry['state'] != 'PENDING':
                raise ConnectorError('CONNECTOR_OAUTH_STATE_DENIED')
            return entry

    def _store(self, binding, entry, value):
        if not isinstance(value, dict) or not isinstance(value.get('access_token'), str):
            raise ConnectorError('CONNECTOR_OAUTH_TOKEN_INVALID')
        normalized_tokens(binding.provider,value)
        validate_returned_scopes(binding.provider,value,entry['scopes'],required=True)
        token = value['access_token']
        # The API proves which provider account authorized this session. Its
        # content never changes owner/workspace or the explicit resource list.
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
        identity_url = 'https://api.github.com/user' if binding.provider == 'github' else 'https://www.googleapis.com/drive/v3/about?fields=user(permissionId)'
        identity = require_success(self.transport.request('GET', identity_url, headers=headers, max_bytes=65536)).json()
        subject = identity.get('id') if binding.provider == 'github' and isinstance(identity,dict) else (identity.get('user') or {}).get('permissionId') if isinstance(identity,dict) and isinstance(identity.get('user'),dict) else None
        if binding.provider=='github':
            subject=str(subject) if type(subject) is int and subject>0 else None
        if not isinstance(subject,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',subject):
            raise ConnectorError('CONNECTOR_OAUTH_SUBJECT_INVALID')
        return self.accounts.install(binding, value, resources=entry['resources'], subject=subject, scopes=entry['scopes'], oauth_client_id=entry['client_id'], approved=True)

    def finish_google(self, binding, *, flow_id, code, approved=False):
        if approved is not True or binding.provider != 'google-drive':
            raise ConnectorError('CONNECTOR_HUMAN_CONSENT_REQUIRED')
        with self.lock:
            entry = self._claim(binding, flow_id)
            if not isinstance(code, str) or not re.fullmatch(r'[\x21-\x7e]{1,2048}', code):
                raise ConnectorError('CONNECTOR_OAUTH_CODE_INVALID')
            entry['state'] = 'EXCHANGING'
        try:
            value = require_success(self._post('https://oauth2.googleapis.com/token', {'client_id': entry['client_id'], 'code': code, 'code_verifier': entry['verifier'], 'redirect_uri': entry['redirect_uri'], 'grant_type': 'authorization_code'})).json()
            result = self._store(binding, entry, value)
            entry['state'] = 'COMPLETED'
            return result
        except Exception:
            entry['state'] = 'UNCERTAIN'
            raise ConnectorError('CONNECTOR_OAUTH_EXCHANGE_UNCONFIRMED') from None

    def poll_github(self, binding, *, flow_id, approved=False):
        if approved is not True or binding.provider != 'github':
            raise ConnectorError('CONNECTOR_HUMAN_CONSENT_REQUIRED')
        with self.lock:
            entry = self._claim(binding, flow_id)
            if self.clock() < entry['next_poll']:
                return {'status': 'WAITING', 'poll_after': entry['next_poll'] - self.clock()}
            entry['state'] = 'POLLING'
        try:
            value = require_success(self._post('https://github.com/login/oauth/access_token', {'client_id': entry['client_id'], 'device_code': entry['device_code'], 'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'})).json()
            if isinstance(value, dict) and value.get('error') in {'authorization_pending', 'slow_down'}:
                with self.lock:
                    if value['error'] == 'slow_down':
                        entry['interval'] = min(120, entry['interval'] + 5)
                    entry.update(state='PENDING', next_poll=self.clock() + entry['interval'])
                return {'status': 'WAITING', 'poll_after': entry['interval']}
            if isinstance(value, dict) and value.get('error') in {'access_denied', 'expired_token', 'incorrect_device_code', 'device_flow_disabled'}:
                entry['state'] = 'DENIED'
                raise ConnectorError('CONNECTOR_OAUTH_CONSENT_DENIED')
            result = self._store(binding, entry, value)
            entry['state'] = 'COMPLETED'
            return result
        except ConnectorError as exc:
            if entry['state'] != 'DENIED':
                entry['state'] = 'UNCERTAIN'
            raise ConnectorError(str(exc) if entry['state'] == 'DENIED' else 'CONNECTOR_OAUTH_POLL_UNCONFIRMED') from None
        except Exception:
            entry['state'] = 'UNCERTAIN'
            raise ConnectorError('CONNECTOR_OAUTH_POLL_UNCONFIRMED') from None

    def refresh(self, binding, *, client_id, approved=False):
        if approved is not True:
            raise ConnectorError('CONNECTOR_HUMAN_CONSENT_REQUIRED')
        metadata = self.accounts.metadata(binding)
        if metadata.get('oauth_client_id') != client_id:
            raise ConnectorError('CONNECTOR_OAUTH_CLIENT_MISMATCH')
        key = binding.key()
        def exchange(refresh_token):
            endpoint = 'https://github.com/login/oauth/access_token' if binding.provider == 'github' else 'https://oauth2.googleapis.com/token'
            value=require_success(self._post(endpoint, {'client_id': client_id, 'grant_type': 'refresh_token', 'refresh_token': refresh_token})).json()
            value=normalized_tokens(binding.provider,value)
            validate_returned_scopes(binding.provider,value,metadata['scopes'])
            return value
        try:
            return self.accounts.vault.refresh(key[0], key[1], binding.vault_id, exchange)
        except Exception:
            raise ConnectorError('CONNECTOR_REFRESH_UNCONFIRMED_NEW_CONSENT_REQUIRED') from None

    def revoke(self, binding, *, approved=False, github_app_credentials=None):
        if approved is not True:
            raise ConnectorError('CONNECTOR_HUMAN_CONSENT_REQUIRED')
        status=self.accounts.status(binding)['status']
        if status.startswith('REVOK'):
            raise ConnectorError('CONNECTOR_ALREADY_REVOKED_NO_REMOTE_RETRY')
        if binding.provider == 'github':
            # Public device clients have no distributable app secret. Delete the
            # local bearer immediately and give the explicit provider revocation
            # destination; never pretend local deletion revoked GitHub remotely.
            if github_app_credentials is None:
                return {**self.accounts.revoke_local(binding, approved=True), 'provider_revocation_url': 'https://github.com/settings/applications'}
            client_id, client_secret = github_app_credentials
            metadata = self.accounts.metadata(binding)
            if (client_id != metadata.get('oauth_client_id') or not isinstance(client_secret, str)
                    or not re.fullmatch(r'[\x21-\x7e]{1,2048}', client_secret)):
                raise ConnectorError('CONNECTOR_OAUTH_CLIENT_MISMATCH')
            try:
                access = self.accounts.access(binding)
            except ConnectorError:
                # Expired/uncertain access cannot be retrieved via the vault's
                # public access path. Still commit local revocation immediately.
                return {**self.accounts.revoke_local(binding,approved=True),
                        'provider_revocation_url':'https://github.com/settings/applications',
                        'reason':'CONNECTOR_REMOTE_REVOKE_UNCONFIRMED'}
            key = binding.key()
            def revoke_github(_token):
                basic = base64.b64encode((client_id + ':' + client_secret).encode()).decode()
                response = self.transport.request('DELETE', 'https://api.github.com/applications/' + client_id + '/token',
                    headers={'Authorization': 'Basic ' + basic, 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2026-03-10'},
                    body=json.dumps({'access_token': access}, separators=(',', ':')).encode(), max_bytes=16384)
                return response.status == 204
            return self.accounts.vault.revoke_remote(key[0], key[1], binding.vault_id, revoke_github, approved=True)
        key = binding.key()
        if status not in {'ACTIVE','EXPIRED'}:
            return {**self.accounts.revoke_local(binding,approved=True),'reason':'CONNECTOR_REMOTE_REVOKE_UNCONFIRMED'}
        def send(token):
            response = self._post('https://oauth2.googleapis.com/revoke', {'token': token})
            return response.status == 200
        return self.accounts.vault.revoke_remote(key[0], key[1], binding.vault_id, send, approved=True)
