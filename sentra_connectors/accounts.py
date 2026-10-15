"""Reuse the host DPAPI vault; connector consent is separate from a host Grant."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time
from sentra_core.conversations import _encode, _decode
from sentra_mcp.services.mcpb_oauth import OAuthDPAPIVault, OAuthAdmissionError, _token_response
from .http import ConnectorError

ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
PROVIDERS = frozenset({'github', 'google-drive'})


def validate_consent(provider, resources, scopes):
    if (provider not in PROVIDERS or not isinstance(resources, tuple) or not 1 <= len(resources) <= 100
            or any(not isinstance(value, str) or not 1 <= len(value) <= 256 for value in resources)
            or len(set(resources)) != len(resources)
            or not isinstance(scopes, tuple) or not scopes or len(scopes) > 16
            or any(not isinstance(value, str) or not 1 <= len(value) <= 100 for value in scopes)
            or len(set(scopes))!=len(scopes)):
        raise ConnectorError('CONNECTOR_CONSENT_INVALID')
    allowed = {'public_repo', 'repo', 'read:user'} if provider == 'github' else {'https://www.googleapis.com/auth/drive.file'}
    if any(value not in allowed for value in scopes):
        raise ConnectorError('CONNECTOR_OAUTH_SCOPE_DENIED')
    pattern = r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}' if provider == 'github' else r'[A-Za-z0-9_-]{1,200}'
    if any(not re.fullmatch(pattern, value) or '..' in value for value in resources):
        raise ConnectorError('CONNECTOR_CONSENT_INVALID')


def normalized_tokens(provider, tokens):
    if provider not in PROVIDERS or not isinstance(tokens, dict):
        raise ConnectorError('CONNECTOR_OAUTH_TOKEN_INVALID')
    normalized = dict(tokens)
    # A local lease on GitHub non-expiring tokens is not provider expiration.
    if provider == 'github' and 'expires_in' not in normalized:
        normalized['expires_in'] = 86400
    try:
        _token_response(normalized)
    except Exception:
        raise ConnectorError('CONNECTOR_OAUTH_TOKEN_INVALID') from None
    return normalized


def validate_returned_scopes(provider,tokens,requested,*,required=False):
    raw=tokens.get('scope')
    if raw is None and not required:
        return
    if not isinstance(raw,str) or len(raw)>4096:
        raise ConnectorError('CONNECTOR_GRANTED_SCOPE_UNVERIFIED')
    actual=tuple(raw.replace(',', ' ').split()) if provider=='github' else tuple(raw.split())
    if not actual or set(actual)!=set(requested):
        raise ConnectorError('CONNECTOR_GRANTED_SCOPE_MISMATCH')


@dataclass(frozen=True)
class AccountBinding:
    owner: str
    workspace: str
    provider: str
    account_id: str

    def key(self):
        if (not isinstance(self.provider, str) or self.provider not in PROVIDERS
                or not isinstance(self.account_id, str) or not ID.fullmatch(self.account_id)
                or not isinstance(self.owner, str) or not self.owner or len(self.owner) > 256):
            raise ConnectorError('CONNECTOR_ACCOUNT_BINDING_INVALID')
        root = str(Path(self.workspace).resolve(strict=True))
        if not Path(root).is_dir():
            raise ConnectorError('CONNECTOR_WORKSPACE_REQUIRED')
        return self.owner, root, self.provider, self.account_id

    @property
    def vault_id(self):
        return 'connector-' + hashlib.sha256(json.dumps(self.key(), separators=(',', ':')).encode()).hexdigest()


class ConnectorAccounts:
    def __init__(self, store):
        self.store = store
        self.vault = OAuthDPAPIVault(store)
        with store.connect('plugin_bundle') as db:
            db.execute('''CREATE TABLE IF NOT EXISTS connector_accounts(
                owner TEXT, workspace TEXT, provider TEXT, account_id TEXT,
                protected_metadata TEXT NOT NULL,
                PRIMARY KEY(owner,workspace,provider,account_id))''')

    def install(self, binding, tokens, *, resources, subject, scopes, oauth_client_id=None, approved=False):
        if approved is not True:
            raise ConnectorError('CONNECTOR_HUMAN_CONSENT_REQUIRED')
        key = binding.key()
        validate_consent(binding.provider, resources, scopes)
        normalized = normalized_tokens(binding.provider, tokens)
        if (not isinstance(subject, str) or not 1 <= len(subject) <= 256
                or oauth_client_id is not None and (not isinstance(oauth_client_id, str)
                    or not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}', oauth_client_id))):
            raise ConnectorError('CONNECTOR_CONSENT_INVALID')
        metadata = {'resources': list(dict.fromkeys(resources)), 'subject': subject, 'scopes': list(scopes), 'created': time.time(),
                    'provider_expiry_known': type(tokens.get('expires_in')) is int, 'ready': False,
                    'oauth_client_id': oauth_client_id}
        with self.store.connect('plugin_bundle') as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM connector_accounts WHERE owner=? AND workspace=? AND provider=? AND account_id=?', key).fetchone():
                raise ConnectorError('CONNECTOR_NEW_CONSENT_IDENTITY_REQUIRED')
            db.execute('INSERT INTO connector_accounts VALUES(?,?,?,?,?)', (*key, _encode(metadata)))
        self.vault.put(key[0], key[1], binding.vault_id, normalized, approved=True)
        metadata['ready'] = True
        with self.store.connect('plugin_bundle') as db:
            db.execute('UPDATE connector_accounts SET protected_metadata=? WHERE owner=? AND workspace=? AND provider=? AND account_id=?', (_encode(metadata), *key))
        return self.status(binding)

    def metadata(self, binding):
        key = binding.key()
        with self.store.connect('plugin_bundle') as db:
            row = db.execute('SELECT protected_metadata FROM connector_accounts WHERE owner=? AND workspace=? AND provider=? AND account_id=?', key).fetchone()
        if not row:
            raise ConnectorError('CONNECTOR_ACCOUNT_UNAVAILABLE')
        value = _decode(row['protected_metadata'])
        if not value.get('ready'):
            raise ConnectorError('CONNECTOR_ACCOUNT_CONSENT_INCOMPLETE')
        return value

    def status(self, binding):
        metadata = self.metadata(binding)
        key = binding.key()
        status = self.vault.status(key[0], key[1], binding.vault_id)
        effective = 'EXPIRED' if status['status'] == 'ACTIVE' and status['expires_at'] <= time.time() + 10 else status['status']
        return {'provider': binding.provider, 'account_id': binding.account_id, 'status': effective,
                'expires_at': status['expires_at'], 'revision': status['revision'],
                'resources': metadata['resources'], 'scopes': metadata['scopes'],
                'provider_expiry_known': metadata['provider_expiry_known'], 'credential_exposed': False}

    def access(self, binding):
        key = binding.key()
        try:
            return self.vault.access(key[0], key[1], binding.vault_id)
        except OAuthAdmissionError:
            raise ConnectorError('CONNECTOR_ACCOUNT_EXPIRED_REVOKED_OR_UNCERTAIN') from None

    def revoke_local(self, binding, *, approved=False):
        key = binding.key()
        self.vault.revoke(key[0], key[1], binding.vault_id, approved=approved)
        return {'local_revoked': True, 'remote_confirmed': False, 'retry_permitted': False}

    def invalidate_rejected_token(self,binding,*,expected_revision):
        """A provider 401 cannot keep a rejected local bearer active for new reads."""
        key=binding.key()
        with self.store.connect('plugin_bundle') as db:
            db.execute("UPDATE mcp_oauth_credentials SET ciphertext=NULL,status='UNCERTAIN',revision=revision+1,updated=? "
                       "WHERE owner=? AND workspace=? AND server_id=? AND status='ACTIVE' AND revision=?",
                       (time.time(),key[0],key[1],binding.vault_id,expected_revision))
