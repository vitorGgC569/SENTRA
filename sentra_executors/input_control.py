"""Durable desktop input possession subordinate to central WorkItem grants.

Human/agent handoff is explicit and CAS fenced. Possession grants no capability.
No clipboard data or keyboard content is stored in this table.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import time

from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import OperationRequest, PolicyDecision
from sentra_runtime.executor import AuthorizationRequired


@dataclass(frozen=True)
class _HumanInputScope:
    control: object
    owner: str
    workspace_id: str
    machine_id: str
    resource_id: str
    expected_epoch: int
    client_id: str = ''


_human_input = ContextVar('sentra_authenticated_human_input', default=None)


@contextmanager
def human_input_scope(control, *, owner, workspace_id, machine_id, resource_id, expected_epoch, client_id=''):
    """Trusted authenticated host only. Never create from an agent's boolean flag.

    Ordinary grants, WorkItem assignment and central effect admission remain
    mandatory. The scope binds human possession to one exact machine and epoch.
    """
    if type(expected_epoch) is not int or expected_epoch < 1:
        raise ValueError('live_human_input_epoch_required')
    possession = InputControl(control, owner=owner)
    status = possession.status(resource_id=resource_id, workspace_id=workspace_id)
    if (not status['live'] or status['holder'] != 'human' or
            status['epoch'] != expected_epoch or status.get('machine_id') != machine_id or
            status.get('client_id', '') != client_id):
        raise AuthorizationRequired('human input possession expired or handed off')
    token = _human_input.set(_HumanInputScope(control, owner, workspace_id,
                                            machine_id, resource_id, expected_epoch, client_id))
    try:
        yield
    finally:
        _human_input.reset(token)


def resource_for_declaration(declaration):
    """Canonical physical target, independent of machine alias and capability."""
    kind = declaration.machine.kind
    bindings = tuple(declaration.adapter.bindings.values())
    if kind == 'windows_uia' and any('invoke' in b.allowed_actions for b in bindings):
        raise AuthorizationRequired('legacy UIA input requires semantic process and desktop identity')
    if kind in {'windows_uia_semantic', 'windows_guest_uia'}:
        targets = {('desktop:' + b.desktop.machine_guid.lower() + ':' +
                    str(b.desktop.session_id) + ':' + b.desktop.input_desktop_name)
                   for b in bindings}
    elif kind == 'guacamole':
        targets = {'remote:' + b.protocol + ':' + dict(b.parameters)['hostname'] + ':' +
                   dict(b.parameters).get('port', '') for b in bindings}
    elif kind == 'playwright_browser':
        # Ephemeral contexts are shared only by this configured machine.
        targets = {'browser:' + declaration.machine.machine_id}
    elif kind == 'daytona_session':
        targets = {'daytona:' + b.connection.api_url + ':' + b.connection.target for b in bindings}
    elif kind == 'rustdesk':
        targets = {'rustdesk:' + b.rendezvous_server + ':' + b.peer_id for b in bindings}
    elif kind == 'virtualbox_vm':
        targets = {'virtualbox:' + b.vm_id for b in bindings}
    else:
        return None
    if len(targets) != 1:
        raise ValueError('one_physical_input_resource_per_declaration_required')
    return hashlib.sha256(next(iter(targets)).encode()).hexdigest()


def needs_input(request):
    action = request.arguments.get('action')
    return action in {'click', 'fill', 'invoke', 'set_value', 'toggle', 'select', 'input.key', 'input.mouse', 'input.tap', 'clipboard.write',
                      'computer.focus', 'computer.invoke', 'computer.set_value'} or (
        action == 'write' and request.arguments.get('opcode') in {'key', 'mouse', 'touch'})


class InputControl:
    """Use the existing ControlStore, never a provider-local permission database."""
    def __init__(self, control, *, owner, clock=time.time):
        self.control, self.owner, self.clock = control, owner, clock
        db = control.store.connect('machine_input_control')
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS machine_input_schema(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL)')
                version=db.execute('SELECT version FROM machine_input_schema WHERE id=1').fetchone()
                if version is not None and version['version']>2:raise RuntimeError('input schema newer than this host')
                db.execute('CREATE TABLE IF NOT EXISTS machine_input_leases('
                    'resource TEXT PRIMARY KEY, owner TEXT NOT NULL, workspace TEXT NOT NULL,'
                    'machine TEXT NOT NULL, holder TEXT NOT NULL, principal TEXT NOT NULL,'
                    'work_item TEXT NOT NULL, epoch INTEGER NOT NULL, expires REAL NOT NULL)')
                # Versioned additive migration: old desktop leases retain their
                # empty client identity; mobile identity is derived by the host.
                columns={r['name'] for r in db.execute('PRAGMA table_info(machine_input_leases)')}
                if 'client_id' not in columns:
                    db.execute("ALTER TABLE machine_input_leases ADD COLUMN client_id TEXT NOT NULL DEFAULT ''")
                db.execute('INSERT INTO machine_input_schema VALUES(1,2) ON CONFLICT(id) DO UPDATE SET version=2')
                db.execute('CREATE TABLE IF NOT EXISTS machine_input_handoffs('
                    'owner TEXT NOT NULL, request_key TEXT NOT NULL, digest TEXT NOT NULL, result TEXT NOT NULL,'
                    'created REAL NOT NULL, PRIMARY KEY(owner,request_key))')
                db.execute('CREATE TABLE IF NOT EXISTS machine_input_uncertain('
                    'owner TEXT NOT NULL, digest TEXT NOT NULL, work_item TEXT NOT NULL,'
                    'kind TEXT NOT NULL, selector_key TEXT NOT NULL, operation_id TEXT NOT NULL,'
                    'created REAL NOT NULL, PRIMARY KEY(owner,digest))')
        finally:
            db.close()

    def status(self, *, resource_id, workspace_id):
        db = self.control.store.connect('machine_input_control')
        try:
            row = db.execute('SELECT * FROM machine_input_leases WHERE resource=?',
                             (resource_id,)).fetchone()
        finally:
            db.close()
        if row is None:
            return {'resource_id': resource_id, 'holder': 'none', 'epoch': 0, 'live': False}
        row = dict(row)
        if row['owner'] != self.owner:
            raise AuthorizationRequired('input resource belongs to another workspace')
        if row['workspace'] != workspace_id:
            live=row['expires']>self.clock() and row['holder']!='none'
            return {'resource_id':resource_id,'holder':'busy' if live else 'none','epoch':row['epoch'],
                    'live':live,'scope_visible':False,'grant_created':False}
        return {'resource_id': resource_id, 'holder': row['holder'], 'epoch': row['epoch'],
                'principal_id': row['principal'], 'machine_id': row['machine'],
                'work_item_id': row['work_item'], 'expires_at': row['expires'],
                'live': row['expires'] > self.clock() and row['holder'] != 'none',
                'grant_created': False, 'client_id': row['client_id']}

    def handoff(self, *, resource_id, workspace_id, machine_id, holder,
                expected_epoch, request_key, ttl_seconds=60, request=None, only_if_available=False, client_id=''):
        """Authenticated owner host call; browser identity must be derived upstream.

        Agent possession requires a bound live request and capability grant. Human
        possession immediately fences agent input, including in-flight checkpoints.
        Handoff cannot reverse a dispatched OS input event.
        """
        if (holder not in {'human', 'agent', 'none'} or type(expected_epoch) is not int or
                expected_epoch < 0 or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 300 or
                not resource_id or not workspace_id or not machine_id or
                not isinstance(request_key,str) or not 1<=len(request_key)<=128
                or type(only_if_available) is not bool or only_if_available and holder != 'agent'
                or not isinstance(client_id,str) or len(client_id)>128):
            raise ValueError('bounded_input_handoff_required')
        principal, work_item = self.owner, ''
        if holder == 'agent':
            if not isinstance(request, OperationRequest) or request.machine_id != machine_id:
                raise AuthorizationRequired('input possession requires a machine request')
            item = self.control.work_item_info(request.work_item_id, self.owner)
            if (item['state'] != 'RUNNING' or item.get('assignee_agent_id') != request.principal_id or
                    item.get('metadata', {}).get('workspace_id') != workspace_id or
                    item.get('metadata', {}).get('machine_id') != machine_id or
                    self.control.durable.run_status(item['run_id'], self.owner,
                        include_details=False)['state'] != 'RUNNING'):
                raise AuthorizationRequired('input request outside active machine task')
            policy = BoundWorkItemPolicy(owner=self.owner, principal_type='agent',
                authorization=self.control.authorization, governance=self.control.governance)
            if policy(request).allowed is not True:
                raise AuthorizationRequired('input possession requires a live central grant')
            principal, work_item = request.principal_id, request.work_item_id
        db = self.control.store.connect('machine_input_control')
        intent=hashlib.sha256(json.dumps([resource_id,workspace_id,machine_id,holder,expected_epoch,
            ttl_seconds,principal,work_item] + (['only_if_available'] if only_if_available else []) + ([client_id] if client_id else []),separators=(',',':')).encode()).hexdigest()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                prior=db.execute('SELECT digest,result FROM machine_input_handoffs WHERE owner=? AND request_key=?',
                                 (self.owner,request_key)).fetchone()
                if prior is not None:
                    if prior['digest']!=intent:raise ValueError('input_handoff_idempotency_conflict')
                    return json.loads(prior['result'])
                row = db.execute('SELECT * FROM machine_input_leases WHERE resource=?',
                                 (resource_id,)).fetchone()
                if row is not None and (row['owner'] != self.owner or
                        row['workspace'] != workspace_id and row['holder']!='none' and row['expires']>self.clock()):
                    raise AuthorizationRequired('input resource outside authenticated workspace')
                if (row['epoch'] if row else 0) != expected_epoch:
                    raise ValueError('input_handoff_revision_conflict')
                if holder != 'human' and client_id and (row is None or row['client_id']!=client_id):
                    raise AuthorizationRequired('device cannot release another client input possession')
                if only_if_available and row is not None and row['holder'] != 'none' and row['expires'] > self.clock():
                    raise AuthorizationRequired('active input possession cannot be acquired automatically')
                epoch = expected_epoch + 1
                db.execute('INSERT INTO machine_input_leases(resource,owner,workspace,machine,holder,principal,work_item,epoch,expires,client_id) VALUES(?,?,?,?,?,?,?,?,?,?) '
                    'ON CONFLICT(resource) DO UPDATE SET workspace=excluded.workspace,machine=excluded.machine, holder=excluded.holder,'
                    'principal=excluded.principal,work_item=excluded.work_item,epoch=excluded.epoch,expires=excluded.expires,client_id=excluded.client_id',
                    (resource_id, self.owner, workspace_id, machine_id, holder, principal,
                     work_item, epoch, self.clock() + ttl_seconds if holder != 'none' else 0,client_id if holder=='human' else ''))
                result={'resource_id':resource_id,'machine_id':machine_id,'work_item_id':work_item,
                    'principal_id':principal,'holder':holder,'epoch':epoch,'request_key':request_key,
                    'grant_created':False,'handoff_recorded':True,'status_requires_fresh_read':True}
                db.execute('INSERT INTO machine_input_handoffs VALUES(?,?,?,?,?)',
                           (self.owner,request_key,intent,json.dumps(result),self.clock()))
        finally:
            db.close()
        return result

    def check(self, request, resource_id, *, expected_epoch=None):
        item = self.control.work_item_info(request.work_item_id, self.owner)
        status = self.status(resource_id=resource_id,
                             workspace_id=item.get('metadata', {}).get('workspace_id'))
        if (not status['live'] or status['holder'] != 'agent' or
                status['machine_id'] != request.machine_id or
                status['principal_id'] != request.principal_id or
                status['work_item_id'] != request.work_item_id or
                expected_epoch is not None and status['epoch'] != expected_epoch):
            raise AuthorizationRequired('agent input possession expired or handed to human')
        return status['epoch']

    def check_human(self, request, resource_id, scope):
        if (not isinstance(scope, _HumanInputScope) or scope.control is not self.control or
                scope.owner != self.owner or scope.machine_id != request.machine_id or
                scope.resource_id != resource_id):
            raise AuthorizationRequired('authenticated human input scope mismatch')
        item = self.control.work_item_info(request.work_item_id, self.owner)
        if (item.get('metadata', {}).get('workspace_id') != scope.workspace_id or
                item.get('metadata', {}).get('machine_id') != request.machine_id):
            raise AuthorizationRequired('human input WorkItem scope mismatch')
        status = self.status(resource_id=resource_id, workspace_id=scope.workspace_id)
        if (not status['live'] or status['holder'] != 'human' or
                status.get('principal_id') != self.owner or
                status.get('machine_id') != request.machine_id or status['epoch'] != scope.expected_epoch or
                status.get('client_id','') != scope.client_id):
            raise AuthorizationRequired('human input possession expired or handed off')
        return status['epoch']

    def effect_digest(self, *, work_item_id, kind, selector_key, text=None):
        """Identity of one mouse click or one keyboard payload. The text is not stored."""
        if kind not in {'mouse', 'keyboard'}:
            raise ValueError('uncertain_input_kind_required')
        if not isinstance(work_item_id, str) or not 1 <= len(work_item_id) <= 128:
            raise ValueError('bounded_work_item_required')
        if not isinstance(selector_key, str) or not 1 <= len(selector_key) <= 200:
            raise ValueError('bounded_selector_required')
        material = [work_item_id, kind, selector_key]
        if kind == 'keyboard':
            if not isinstance(text, str) or not text or len(text) > 65536:
                raise ValueError('keyboard_fence_requires_text')
            material.append(hashlib.sha256(text.encode()).hexdigest())
        elif text is not None:
            raise ValueError('mouse_fence_has_no_text')
        return hashlib.sha256(json.dumps(material, separators=(',', ':')).encode()).hexdigest()

    def note_uncertain(self, *, work_item_id, kind, selector_key, operation_id, text=None):
        """Record an input effect whose outcome cannot be retried. Does not send input."""
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
            raise ValueError('bounded_operation_required')
        digest = self.effect_digest(work_item_id=work_item_id, kind=kind,
                                    selector_key=selector_key, text=text)
        db = self.control.store.connect('machine_input_control')
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                prior = db.execute('SELECT operation_id FROM machine_input_uncertain '
                                   'WHERE owner=? AND digest=?', (self.owner, digest)).fetchone()
                if prior is not None:
                    return {'digest': digest, 'operation_id': prior['operation_id'],
                            'already_fenced': True, 'automatic_resend': False}
                db.execute('INSERT INTO machine_input_uncertain VALUES(?,?,?,?,?,?,?)',
                           (self.owner, digest, work_item_id, kind, selector_key,
                            operation_id, self.clock()))
        finally:
            db.close()
        return {'digest': digest, 'operation_id': operation_id,
                'already_fenced': False, 'automatic_resend': False}

    def uncertain_effect(self, *, work_item_id, kind, selector_key, text=None):
        digest = self.effect_digest(work_item_id=work_item_id, kind=kind,
                                    selector_key=selector_key, text=text)
        db = self.control.store.connect('machine_input_control')
        try:
            row = db.execute('SELECT operation_id,kind,selector_key,work_item FROM machine_input_uncertain '
                             'WHERE owner=? AND digest=?', (self.owner, digest)).fetchone()
        finally:
            db.close()
        if row is None:
            return None
        return {'digest': digest, 'operation_id': row['operation_id'], 'kind': row['kind'],
                'selector_key': row['selector_key'], 'work_item_id': row['work_item'],
                'automatic_resend': False}


class InputBoundPolicy:
    def __init__(self, policy, *, control, owner, resources):
        self.policy = policy
        self.input = InputControl(control, owner=owner)
        self.resources = resources
        self._epoch = ContextVar('sentra_input_epoch', default=None)

    @contextmanager
    def scope(self, request):
        resource = self.resources.get(request.machine_id)
        human = _human_input.get()
        epoch = (self.input.check_human(request, resource, human) if human is not None
                 else self.input.check(request, resource)) if resource and needs_input(request) else None
        token = self._epoch.set(epoch)
        try:
            yield
        finally:
            self._epoch.reset(token)

    def __call__(self, request):
        decision = self.policy(request)
        if not isinstance(decision, PolicyDecision) or decision.allowed is not True:
            return decision
        resource = self.resources.get(request.machine_id)
        if resource and needs_input(request):
            try:
                human = _human_input.get()
                if human is not None:
                    epoch = self.input.check_human(request, resource, human)
                    if self._epoch.get() is not None and epoch != self._epoch.get():
                        raise AuthorizationRequired('human input epoch changed during effect')
                else:
                    self.input.check(request, resource, expected_epoch=self._epoch.get())
            except (PermissionError, ValueError, KeyError):
                return PolicyDecision(False, 'explicit live agent input possession required')
        return decision
