"""Persist Playwright session identity and evidence without replaying a browser.

An ephemeral browser cannot reattach across process death. Recovery exposes LOST
and retained evidence; it never restores cookies or repeats navigation/input.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import asdict

from .identity_sessions import SessionJournal
from .rpa import AuthorizedPaths, ExecutorFailure


class PersistentPlaywrightBackend:
    def __init__(self, backend, journal):
        self.backend, self.journal = backend, journal
        self.instance = uuid.uuid4().hex
        self.lock = threading.RLock()

    @classmethod
    def for_control(cls, backend, control, machine_id):
        directory = control.durable.root / 'provider-state' / machine_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        journal = SessionJournal(str(directory / 'browser.sqlite3'),
            AuthorizedPaths((str(directory),), (str(directory),)))
        return cls(backend, journal)

    @staticmethod
    def identity(binding):
        config = asdict(binding)
        return hashlib.sha256(json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def run(self, binding, arguments):
        with self.lock:
            action, scope = arguments['action'], arguments['_scope']
            identity = self.identity(binding)
            if action == 'session.list':
                return self.journal.list(scope, 'playwright', identity,
                                         limit=arguments.get('limit', 64))
            if action == 'diagnostics' and 'session_id' not in arguments:
                return self.backend.run(binding, arguments)
            row = None
            if action == 'open':
                prior = self.journal.reserve_effect(arguments['_operation_id'], scope, arguments)
                if prior is not None:
                    return prior
                row = self.journal.create(scope, 'playwright', identity, 'pending',
                    {'backend_instance': self.instance, 'profile': arguments['profile']},
                    state='CONNECTING', max_sessions=binding.max_sessions)
                try:
                    result = self.backend.run(binding, arguments)
                    metadata = dict(row['metadata'], page_id=result['page_id'])
                    self.journal.update(row, remote_id=result['session_id'], state='CONNECTED', metadata=metadata)
                    result = dict(result, session_id=row['id'], recovery='ephemeral_no_process_reattach')
                    self.journal.append(row, 'open', json.dumps(result).encode())
                    self.journal.complete_effect(arguments['_operation_id'], result)
                    return result
                except Exception as exc:
                    self.journal.update(row, state='UNCERTAIN')
                    raise ExecutorFailure('browser_open_requires_reconciliation', uncertain=True,
                        evidence={'session_id': row['id'], 'replay_allowed': False}) from exc
            row = self.journal.get(arguments['session_id'], scope, 'playwright', identity)
            alive = (row['metadata'].get('backend_instance') == self.instance and
                     row['remote_id'] in getattr(self.backend, '_sessions', {}))
            if not alive and row['state'] not in {'CLOSED', 'LOST'}:
                self.journal.update(row, state='LOST', new_epoch=True)
            if action in {'session.status', 'diagnostics'} and not alive:
                return {'session_id': row['id'], 'state': row['state'], 'epoch': row['epoch'],
                        'live': False, 'reattach_supported': False, 'replay_allowed': False,
                        'evidence_retained': True, 'reason': 'ephemeral_browser_process_unavailable'}
            if action == 'session.status':
                return {'session_id': row['id'], 'state': row['state'], 'live': alive,
                        'epoch': row['epoch'], 'replay_allowed': False}
            if action == 'session.events':
                return self.journal.read(row, after=arguments.get('after', 0),
                                         max_bytes=binding.max_evidence_bytes)
            if action == 'session.export':
                return {'artifact': self.journal.export(row, binding.artifact_paths, arguments['output'])}
            if not alive:
                # Closing a dead session only closes the journal identity.
                if action == 'close':
                    self.journal.update(row, state='CLOSED')
                    return {'session_id': row['id'], 'closed': True, 'provider_accessed': False}
                raise ExecutorFailure('browser_process_lost_no_automatic_replay',
                                      evidence={'session_id': row['id'], 'state': row['state']})
            mutating = action in {'close', 'navigate', 'click', 'fill', 'network', 'capture.start', 'capture.stop'}
            if mutating:
                prior = self.journal.reserve_effect(arguments['_operation_id'], scope, arguments)
                if prior is not None:
                    return prior
            translated = dict(arguments, session_id=row['remote_id'])
            try:
                result = self.backend.run(binding, translated)
                if 'session_id' in result:
                    result = dict(result, session_id=row['id'])
                event = json.dumps({'operation_id': arguments['_operation_id'], 'action': action,
                                    'value': result}, allow_nan=False).encode()
                if len(event) > self.journal.max_bytes:
                    event = json.dumps({'operation_id': arguments['_operation_id'], 'action': action,
                        'value_sha256': hashlib.sha256(event).hexdigest(), 'omitted': 'byte_limit'}).encode()
                self.journal.append(row, 'browser_result', event)
                if action == 'close':
                    self.journal.update(row, state='CLOSED')
                if mutating:
                    self.journal.complete_effect(arguments['_operation_id'], result)
                return result
            except Exception as exc:
                self.journal.append(row, 'failure', json.dumps({
                    'operation_id': arguments['_operation_id'], 'action': action,
                    'error': exc.code if isinstance(exc, ExecutorFailure) else 'browser_provider_error',
                    'replay_allowed': False}).encode())
                raise

    def shutdown(self):
        # Journal remains available to the next host. Do not report recovery of
        # cookies/pages/processes; the real backend shuts down only what it owns.
        self.backend.shutdown()
