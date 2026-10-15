"""Useful provider reads behind an existing WorkItem Grant and explicit consent."""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import quote, urlencode
from sentra_core.conversations import _encode, _decode
from sentra_marketplace.gate import HostBinding
from sentra_marketplace.policy import AllowPolicy
from sentra_marketplace.gate import PackagePin
from sentra_marketplace.packages import verify_pin
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.effect_boundary import CentralEffectContext,current_effect_context
from sentra_runtime.executor import _request_snapshot
from .http import ConnectorError, MAX_BYTES, PinnedConnectorHTTPS, require_success


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class ConnectorHost:
    def __init__(self, accounts, authorization, *, transport=None, control=None, package=None):
        self.accounts, self.authorization = accounts, authorization
        self.store = accounts.store
        self.transport = transport or PinnedConnectorHTTPS()
        self.control,self.package=control,package
        with self.store.connect('plugin_bundle') as db:
            db.execute('''CREATE TABLE IF NOT EXISTS connector_read_operations(
                owner TEXT, workspace TEXT, operation_id TEXT, idempotency_key TEXT,
                fingerprint TEXT NOT NULL, protected_receipt TEXT NOT NULL,
                PRIMARY KEY(owner,workspace,operation_id), UNIQUE(owner,workspace,idempotency_key))''')

    def _checkpoint(self,binding,account,action,arguments):
        """Existing host authority, never an approval flag from connector JSON."""
        control=self.control; context=current_effect_context.get()
        try:
            if (not isinstance(control,ControlPlaneService) or self.authorization is not control.authorization
                    or self.store is not control.store or not isinstance(context,CentralEffectContext)
                    or context.authority.durable is not control.durable
                    or context.receipt.owner!=binding.owner or context.receipt.run_id!=binding.run_id
                    or _request_snapshot(context.request)[1]!=_request_snapshot(binding.operation)[1]
                    or dict(binding.operation.arguments)!={'provider':account.provider,'account_id':account.account_id,
                                                          'action':action,'arguments':arguments}):
                raise ValueError()
            context.checkpoint()
            run=control.durable.run_status(binding.run_id,binding.owner,include_details=False)
            item=control.work_item_info(binding.work_item_id,binding.owner)
            operation=control.durable.operation_status(binding.operation.operation_id,binding.owner)
            if (run['state']!='RUNNING' or str(Path(run['workspace']).resolve(strict=True))!=account.key()[1]
                    or item['run_id']!=binding.run_id or item['state']!='RUNNING'
                    or item.get('assignee_agent_id')!=binding.operation.principal_id or binding.principal_type!='agent'
                    or operation['kind']!='sentra.machine' or operation['state']!='RUNNING'
                    or (operation.get('progress') or {}).get('effect_started') is not True
                    or not BoundWorkItemPolicy(owner=binding.owner,principal_type='agent',
                        authorization=control.authorization,governance=control.governance)(binding.operation).allowed):
                raise ValueError()
        except Exception:
            raise ConnectorError('CONNECTOR_ACTIVE_CENTRAL_EFFECT_REQUIRED') from None
        if (not isinstance(self.package,PackagePin) or self.package.kind!='connector'
                or self.package.package_id!=account.provider or not verify_pin(self.package).get('ok')):
            raise ConnectorError('CONNECTOR_PINNED_LOCAL_PACKAGE_REQUIRED')

    def _admit(self, binding, account, policy, network_allowed,action,arguments):
        if not isinstance(binding, HostBinding):
            raise ConnectorError('CONNECTOR_HOST_BINDING_REQUIRED')
        binding.validate()
        account.key()
        capability = 'connector:' + account.provider + ':invoke'
        if binding.owner != account.owner or binding.operation.capability_id != capability:
            raise ConnectorError('CONNECTOR_OWNER_OR_CAPABILITY_MISMATCH')
        if network_allowed is not True or not isinstance(policy, AllowPolicy) or not policy.decide(capability)[0]:
            raise ConnectorError('CONNECTOR_NETWORK_AND_OPT_IN_REQUIRED')
        try:
            value = self.authorization.authorize(binding.owner, principal_type=binding.principal_type,
                principal_id=binding.operation.principal_id, capability=capability,
                scope_type='work_item', scope_id=binding.work_item_id, local_owner=False)
        except Exception:
            raise ConnectorError('CONNECTOR_GRANT_CHECK_UNAVAILABLE') from None
        if not isinstance(value, dict) or not value.get('allowed') or value.get('source') != 'grant' or not value.get('grant_id'):
            raise ConnectorError('CONNECTOR_EXISTING_GRANT_REQUIRED')
        self._checkpoint(binding,account,action,arguments)
        return str(value['grant_id'])

    def _claim(self, binding, account, request):
        owner, workspace, _, _ = account.key()
        fingerprint = _digest({'account': account.key(), 'request': request,
            'run': binding.run_id, 'work_item': binding.work_item_id,
            'principal': binding.operation.principal_id, 'capability': binding.operation.capability_id,
            'package_sha256':getattr(self.package,'sha256',None),
            'superior_instruction_sha256':hashlib.sha256(binding.superior_instruction.encode()).hexdigest()})
        receipt = {'owner': owner, 'provider': account.provider, 'account_id': account.account_id,
            'run_id': binding.run_id, 'work_item_id': binding.work_item_id, 'operation_id': binding.operation.operation_id,
            'idempotency_key': binding.operation.idempotency_key, 'outcome': 'PENDING', 'reason': 'CONNECTOR_READ_CLAIMED',
            'result': None, 'account_contacted': False, 'network': False, 'homologated': False,
            'automatic_retry': False, 'resent': False, 'grants_created': False, 'instruction_authority': False}
        with self.store.connect('plugin_bundle') as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT * FROM connector_read_operations WHERE owner=? AND workspace=? AND (operation_id=? OR idempotency_key=?)',
                (owner, workspace, binding.operation.operation_id, binding.operation.idempotency_key)).fetchall()
            if rows:
                if len(rows) != 1 or rows[0]['fingerprint'] != fingerprint or rows[0]['operation_id'] != binding.operation.operation_id or rows[0]['idempotency_key'] != binding.operation.idempotency_key:
                    raise ConnectorError('CONNECTOR_OPERATION_IDENTITY_CONFLICT')
                prior = _decode(rows[0]['protected_receipt'])
                if prior['outcome'] == 'PENDING':
                    prior.update(outcome='UNCERTAIN', reason='CONNECTOR_READ_CAPTURE_UNCONFIRMED', result=None)
                    db.execute('UPDATE connector_read_operations SET protected_receipt=? WHERE owner=? AND workspace=? AND operation_id=?',
                        (_encode(prior), owner, workspace, binding.operation.operation_id))
                return prior, False
            db.execute('INSERT INTO connector_read_operations VALUES(?,?,?,?,?,?)',
                (owner, workspace, binding.operation.operation_id, binding.operation.idempotency_key, fingerprint, _encode(receipt)))
        return receipt, True

    def _finish(self, account, receipt,credential_revision):
        key = account.key()
        with self.store.connect('plugin_bundle') as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT protected_receipt FROM connector_read_operations WHERE owner=? AND workspace=? AND operation_id=?',
                             (key[0],key[1],receipt['operation_id'])).fetchone()
            if prior is None:
                raise ConnectorError('CONNECTOR_READ_CLAIM_MISSING')
            prior=_decode(prior['protected_receipt'])
            if prior['outcome']!='PENDING':
                return prior  # A concurrent observation made the capture uncertain: never promote it.
            if receipt['outcome']=='SUCCEEDED':
                live=db.execute('SELECT status,revision,expires_at FROM mcp_oauth_credentials WHERE owner=? AND workspace=? AND server_id=?',
                                (key[0],key[1],account.vault_id)).fetchone()
                if (not live or live['status']!='ACTIVE' or live['revision']!=credential_revision
                        or live['expires_at']<=time.time()+10):
                    receipt.update(outcome='FAILED',reason='CONNECTOR_ACCOUNT_CHANGED_DURING_READ',result=None)
                    receipt.pop('content_sha256',None)
            db.execute('UPDATE connector_read_operations SET protected_receipt=? WHERE owner=? AND workspace=? AND operation_id=?',
                (_encode(receipt), key[0], key[1], receipt['operation_id']))
        return receipt

    def invoke(self, binding, account, *, action, arguments, policy, network_allowed=False):
        grant = self._admit(binding, account, policy, network_allowed,action,arguments)
        metadata = self.accounts.metadata(account)
        request = self._request(account.provider, action, arguments, metadata['resources'])
        status = self.accounts.status(account)
        if status['status'] != 'ACTIVE':
            raise ConnectorError('CONNECTOR_ACCOUNT_EXPIRED_REVOKED_OR_UNCERTAIN')
        receipt, fresh = self._claim(binding, account, {'action': action, 'arguments': arguments})
        if not fresh:
            return receipt
        try:
            token = self.accounts.access(account)
            if self._admit(binding, account, policy, network_allowed,action,arguments) != grant:
                raise ConnectorError('CONNECTOR_GRANT_CHANGED')
            headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json' if account.provider == 'github' else 'application/json'}
            if account.provider == 'github':
                headers['X-GitHub-Api-Version'] = '2026-03-10'
            # Selecting the real transport is not evidence of network contact:
            # DNS or TLS can fail before any provider response exists.
            response = self.transport.request('GET', request['url'], headers=headers, max_bytes=MAX_BYTES)
            receipt['network'] = getattr(response, 'tls_response_verified', False) is True
            receipt['account_contacted'] = receipt['network']
            response = require_success(response)
            result = self._result(account.provider, action, response,arguments)
            # A revocation during the request prevents publishing its content.
            if self.accounts.status(account)['revision'] != status['revision'] or self.accounts.status(account)['status'] != 'ACTIVE':
                raise ConnectorError('CONNECTOR_ACCOUNT_CHANGED_DURING_READ')
            if self._admit(binding, account, policy, network_allowed,action,arguments) != grant:
                raise ConnectorError('CONNECTOR_GRANT_CHANGED_DURING_READ')
            receipt.update(outcome='SUCCEEDED', reason='CONNECTOR_READ_CAPTURED', result=result, content_sha256=_digest(result))
        except ConnectorError as exc:
            if str(exc)=='CONNECTOR_AUTHENTICATION_EXPIRED_OR_REVOKED':
                self.accounts.invalidate_rejected_token(account,expected_revision=status['revision'])
            receipt.update(outcome='UNCERTAIN' if str(exc) == 'CONNECTOR_TRANSPORT_UNCONFIRMED' else 'FAILED', reason=str(exc), result=None)
        except Exception:
            receipt.update(outcome='UNCERTAIN', reason='CONNECTOR_READ_CAPTURE_UNCONFIRMED', result=None)
        return self._finish(account, receipt,status['revision'])

    @staticmethod
    def _request(provider, action, arguments, resources):
        if not isinstance(arguments, dict):
            raise ConnectorError('CONNECTOR_ARGUMENTS_INVALID')
        if provider == 'github':
            allowed = {'repository'} if action == 'repository' else {'repository', 'path', 'ref'} if action == 'read_file' else set()
            if not allowed or not set(arguments) <= allowed or 'repository' not in arguments:
                raise ConnectorError('CONNECTOR_OPERATION_DENIED')
            repository = arguments['repository']
            if not isinstance(repository, str) or repository not in resources:
                raise ConnectorError('CONNECTOR_RESOURCE_NOT_CONSENTED')
            url = 'https://api.github.com/repos/' + repository
            if action == 'read_file':
                path = arguments.get('path')
                if (not isinstance(path, str) or not 1 <= len(path) <= 1024 or path.startswith('/')
                        or '\\' in path or any(part in {'', '.', '..'} for part in path.split('/'))
                        or any(ord(character) < 32 for character in path)):
                    raise ConnectorError('CONNECTOR_FILE_PATH_DENIED')
                url += '/contents/' + '/'.join(quote(part, safe='') for part in path.split('/'))
                if 'ref' in arguments:
                    ref = arguments['ref']
                    if not isinstance(ref, str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,200}', ref) or '..' in ref:
                        raise ConnectorError('CONNECTOR_REF_DENIED')
                    url += '?' + urlencode({'ref': ref})
            return {'url': url}
        if provider != 'google-drive' or action not in {'file_metadata', 'read_file', 'export_text'} or set(arguments) != {'file_id'}:
            raise ConnectorError('CONNECTOR_OPERATION_DENIED')
        file_id = arguments['file_id']
        if not isinstance(file_id, str) or file_id not in resources:
            raise ConnectorError('CONNECTOR_RESOURCE_NOT_CONSENTED')
        url = 'https://www.googleapis.com/drive/v3/files/' + quote(file_id, safe='')
        query = {'fields': 'id,name,mimeType,size,modifiedTime,version,capabilities(canDownload)', 'supportsAllDrives': 'true'} if action == 'file_metadata' else {'alt': 'media', 'supportsAllDrives': 'true'}
        if action == 'export_text':
            url += '/export'
            query = {'mimeType': 'text/plain'}
        return {'url': url + '?' + urlencode(query)}

    @staticmethod
    def _result(provider, action, response,arguments):
        if provider == 'github':
            payload = response.json()
            if not isinstance(payload, dict):
                raise ConnectorError('CONNECTOR_FILE_OR_REPOSITORY_REQUIRED')
            if action == 'repository':
                if (type(payload.get('id')) is not int or payload['id']<=0
                        or not isinstance(payload.get('full_name'),str)
                        or payload['full_name'].casefold()!=arguments['repository'].casefold()):
                    raise ConnectorError('CONNECTOR_REPOSITORY_IDENTITY_MISMATCH')
                return {key: payload[key] for key in ('id', 'full_name', 'private', 'description', 'default_branch', 'html_url') if key in payload}
            if payload.get('type') != 'file' or payload.get('encoding') != 'base64' or not isinstance(payload.get('content'), str):
                raise ConnectorError('CONNECTOR_FILE_CONTENT_UNAVAILABLE')
            try:
                content = base64.b64decode(''.join(payload['content'].split()), validate=True)
            except Exception:
                raise ConnectorError('CONNECTOR_FILE_ENCODING_INVALID') from None
            if len(content) > 1024 * 1024:
                raise ConnectorError('CONNECTOR_RESPONSE_UNBOUNDED')
            blob_sha=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
            if (payload.get('path')!=arguments['path'] or payload.get('sha')!=blob_sha
                    or type(payload.get('size')) is not int or payload['size']!=len(content)):
                raise ConnectorError('CONNECTOR_FILE_IDENTITY_OR_DIGEST_MISMATCH')
            return {'path': payload.get('path'), 'revision': payload.get('sha'), **ConnectorHost._content(content)}
        if action == 'file_metadata':
            payload = response.json()
            if not isinstance(payload, dict) or payload.get('id')!=arguments['file_id']:
                raise ConnectorError('CONNECTOR_FILE_METADATA_INVALID')
            return {key: payload[key] for key in ('id', 'name', 'mimeType', 'size', 'modifiedTime', 'version', 'capabilities') if key in payload}
        return ConnectorHost._content(response.body)

    @staticmethod
    def _content(content):
        if len(content) > 1024 * 1024:
            raise ConnectorError('CONNECTOR_RESPONSE_UNBOUNDED')
        try:
            text=content.decode('utf-8')
            if len(json.dumps(text,ensure_ascii=False).encode())>1_500_000:
                raise UnicodeError()
            return {'content': text, 'encoding': 'utf-8', 'bytes': len(content)}
        except UnicodeError:
            return {'content': base64.b64encode(content).decode('ascii'), 'encoding': 'base64', 'bytes': len(content)}

    def effect(self, binding, account, *, action, arguments, policy, network_allowed=False):
        """Adapter for the optional gate; host constructs/captures this closure.

        The legacy outer receipt still hardcodes network=False. Integration must
        preserve this nested connector receipt instead of claiming full account
        homologation from that legacy envelope.
        """
        def run(context):
            expected = {'operation_id': binding.operation.operation_id, 'work_item_id': binding.work_item_id,
                        'run_id': binding.run_id, 'capability': binding.operation.capability_id,
                        'subject_id': account.provider}
            if not isinstance(context, dict) or any(context.get(key) != value for key, value in expected.items()) or not context.get('grant_id'):
                raise ConnectorError('CONNECTOR_GATE_CONTEXT_MISMATCH')
            receipt=self.invoke(binding, account, action=action, arguments=arguments, policy=policy, network_allowed=network_allowed)
            from sentra_marketplace.gate import EffectUncertain
            if receipt['outcome']=='UNCERTAIN':
                raise EffectUncertain(receipt['reason'])
            if receipt['outcome']!='SUCCEEDED':
                raise ConnectorError(receipt['reason'])
            # OptionalCapabilityGate's legacy journal is plaintext. Publish
            # only this reference there; content stays in protected storage.
            return {'connector_operation_id':receipt['operation_id'],'content_sha256':receipt['content_sha256'],
                    'result_storage':'protected_connector_journal','homologated':False,
                    'account_contacted':False,'instruction_authority':False}
        return run

    def captured_result(self,binding,account,*,action,arguments,policy,network_allowed=False):
        self._admit(binding,account,policy,network_allowed,action,arguments)
        with self.store.connect('plugin_bundle') as db:
            row=db.execute('SELECT protected_receipt FROM connector_read_operations WHERE owner=? AND workspace=? AND operation_id=?',
                           (*account.key()[:2],binding.operation.operation_id)).fetchone()
        if row is None:
            raise ConnectorError('CONNECTOR_READ_CAPTURE_MISSING')
        receipt=_decode(row['protected_receipt'])
        if receipt.get('outcome')!='SUCCEEDED' or receipt.get('content_sha256')!=_digest(receipt.get('result')):
            raise ConnectorError('CONNECTOR_READ_CAPTURE_UNCONFIRMED')
        return receipt
