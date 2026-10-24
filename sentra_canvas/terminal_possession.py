"""Central, physical-terminal input possession and exact effect correlation.

This uses the selected ControlStore. A client identity is an arbitration
identity, never a permission. Agent/mobile writes still require their live
terminal WorkItem and Grant. A claim or transport timeout never licenses replay.

The broker binds authenticated input origins; leases never replace WorkItems,
Grants, exact receipts or the daemon's generation check.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from contextvars import ContextVar
import hashlib
import json
import re
import time
import uuid

from sentra_runtime.executor import AuthorizationRequired

PROTOCOL = 2
_client = ContextVar('sentra_terminal_authenticated_client', default=None)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


@contextmanager
def client_scope(client_id):
    if not isinstance(client_id, str) or not 1 <= len(client_id) <= 160:
        raise ValueError('bounded trusted terminal client identity required')
    token = _client.set(client_id)
    try:
        yield
    finally:
        _client.reset(token)


def current_client():
    from sentra_runtime.effect_boundary import current_effect_context, CentralEffectContext
    effect=current_effect_context.get()
    return _client.get() or ('agent:'+effect.request.principal_id
        if isinstance(effect,CentralEffectContext) else 'owner:host')


class TerminalPossession:
    def __init__(self, control, owner, *, clock=time.time):
        self.control, self.owner, self.clock = control, owner, clock
        with closing(control.store.connect('machine_input_control')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS terminal_input_identity(id INTEGER PRIMARY KEY CHECK(id=1),identity TEXT NOT NULL,version INTEGER NOT NULL)')
            row = db.execute('SELECT * FROM terminal_input_identity WHERE id=1').fetchone()
            if row is not None and row['version'] != PROTOCOL:
                raise RuntimeError('terminal input authority version incompatible')
            db.execute('INSERT OR IGNORE INTO terminal_input_identity VALUES(1,?,?)', (uuid.uuid4().hex, PROTOCOL))
            self.identity = db.execute('SELECT identity FROM terminal_input_identity WHERE id=1').fetchone()['identity']
            db.execute('CREATE TABLE IF NOT EXISTS terminal_input_possession('
                       'resource TEXT PRIMARY KEY,owner TEXT NOT NULL,workspace TEXT NOT NULL,terminal TEXT NOT NULL,'
                       'generation TEXT NOT NULL,runtime TEXT NOT NULL,client TEXT NOT NULL,principal TEXT NOT NULL,'
                       'work_item TEXT NOT NULL,epoch INTEGER NOT NULL,expires REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS terminal_physical_input_effects('
                       'effect_key TEXT PRIMARY KEY,owner TEXT NOT NULL,resource TEXT NOT NULL,caller_key TEXT NOT NULL,'
                       'payload_sha256 TEXT NOT NULL,client TEXT NOT NULL,epoch INTEGER NOT NULL,state TEXT NOT NULL,'
                       'receipt TEXT,created REAL NOT NULL)')
            # Additive table: old reservations remain observable, but a missing
            # reference can never be reconstructed after a possible effect.
            db.execute('CREATE TABLE IF NOT EXISTS terminal_physical_input_refs('
                       'effect_key TEXT PRIMARY KEY,protected_reference TEXT NOT NULL)')

    def resource(self, workspace, terminal, generation, runtime):
        if not all(isinstance(s, str) and 0 < len(s) <= 256 for s in (workspace, terminal, runtime)) or not re.fullmatch(r'[0-9a-f]{32}', generation or ''):
            raise ValueError('exact physical terminal generation required')
        # Independent of aliases, Dots and machines pointing to the same PTY.
        return {'resource': digest([self.identity, runtime, generation]),
                'workspace': workspace, 'terminal': terminal, 'generation': generation, 'runtime': runtime}

    def _row(self, db, resource):
        row = db.execute('SELECT * FROM terminal_input_possession WHERE resource=?', (resource['resource'],)).fetchone()
        if row is not None:
            if row['owner'] != self.owner or any(row[key] != resource[key] for key in ('workspace', 'terminal', 'generation', 'runtime')):
                raise AuthorizationRequired('physical terminal belongs to another authority scope')
            return dict(row)
        return None

    def authorize(self, resource, principal='', work_item=''):
        self.control.store.assert_active()
        if not principal and not work_item:
            return  # Only the authenticated host installs this owner path.
        if not principal or not work_item:
            raise AuthorizationRequired('terminal input WorkItem binding incomplete')
        item = self.control.work_item_info(work_item, self.owner)
        run = self.control.durable.run_status(item['run_id'], self.owner, include_details=False)
        if (item['state'] != 'RUNNING' or run['state'] != 'RUNNING'
                or item.get('assignee_agent_id') != principal
                or item.get('metadata', {}).get('workspace_id') != resource['workspace']):
            raise AuthorizationRequired('terminal input task is no longer active')
        self.control.authorization.require(self.owner, principal_type='agent', principal_id=principal,
            capability='terminal:write', scope_type='work_item', scope_id=work_item, local_owner=False)

    def status(self, resource):
        with closing(self.control.store.connect('machine_input_control')) as db:
            row = self._row(db, resource)
            pending=db.execute("SELECT 1 FROM terminal_physical_input_effects WHERE resource=? AND state IN ('prepared','uncertain') LIMIT 1",
                               (resource['resource'],)).fetchone() is not None
        return {'input_protocol_version': PROTOCOL, 'resource_id': resource['resource'],
                'generation': resource['generation'], 'runtime_id': resource['runtime'],
                'epoch': row['epoch'] if row else 0, 'client_id': row['client'] if row else '',
                'live': bool(row and row['client'] and row['expires'] > self.clock()),
                'expires_at': row['expires'] if row else 0, 'pending_confirmation':pending,'grant_created': False}

    def acquire(self, resource, client, *, principal='', work_item='', expected_epoch=None, takeover=False, ttl=30):
        if not isinstance(client, str) or not 1 <= len(client) <= 160 or type(ttl) is not int or not 1 <= ttl <= 60:
            raise ValueError('bounded terminal possession required')
        if takeover and (principal or work_item or type(expected_epoch) is not int):
            raise AuthorizationRequired('only explicit authenticated owner handoff may replace a client')
        self.authorize(resource, principal, work_item)
        with closing(self.control.store.connect('machine_input_control')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = self._row(db, resource)
            epoch = old['epoch'] if old else 0
            if expected_epoch is not None and (type(expected_epoch) is not int or epoch != expected_epoch):
                raise ValueError('terminal possession epoch changed')
            live = old and old['client'] and old['expires'] > self.clock()
            same = old and (old['client'], old['principal'], old['work_item']) == (client, principal, work_item)
            if live and not same and not takeover:
                raise AuthorizationRequired('terminal input is owned by another client; explicit handoff required')
            pending = db.execute("SELECT 1 FROM terminal_physical_input_effects WHERE resource=? AND state IN ('prepared','uncertain') LIMIT 1", (resource['resource'],)).fetchone()
            if pending:
                raise AuthorizationRequired('terminal input outcome remains uncertain; observe before new input')
            if not same or not live:
                epoch += 1
            db.execute('INSERT INTO terminal_input_possession VALUES(?,?,?,?,?,?,?,?,?,?,?) '
                       'ON CONFLICT(resource) DO UPDATE SET client=excluded.client,principal=excluded.principal,'
                       'work_item=excluded.work_item,epoch=excluded.epoch,expires=excluded.expires',
                       (resource['resource'], self.owner, resource['workspace'], resource['terminal'], resource['generation'],
                        resource['runtime'], client, principal, work_item, epoch, self.clock() + ttl))
        return self.status(resource)

    def release(self, resource, client, expected_epoch):
        with closing(self.control.store.connect('machine_input_control')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, resource)
            if row is None or type(expected_epoch) is not int or row['epoch'] != expected_epoch:
                raise ValueError('terminal possession epoch changed')
            if row['client'] != client:
                raise AuthorizationRequired('cannot release another terminal client')
            db.execute("UPDATE terminal_input_possession SET client='',expires=0,epoch=epoch+1 WHERE resource=?", (resource['resource'],))
        return self.status(resource)

    def prepare(self, resource, client, key, data, *, principal='', work_item=''):
        if not isinstance(key, str) or not 1 <= len(key) <= 200 or not isinstance(data, bytes) or not 0 < len(data) <= 16384:
            raise ValueError('bounded correlated input required')
        effect = digest([self.owner, resource['resource'], key])
        payload = hashlib.sha256(data).hexdigest()
        # Existing effect identities are observation-only, even when no bytes
        # can be proven delivered. A different client cannot reuse the key.
        with closing(self.control.store.connect('machine_input_control')) as db:
            old = db.execute('SELECT * FROM terminal_physical_input_effects WHERE effect_key=?', (effect,)).fetchone()
        if old is not None:
            if old['owner'] != self.owner or old['payload_sha256'] != payload or old['client'] != client:
                raise ValueError('physical terminal input identity changed')
            raise AuthorizationRequired('terminal input already reserved; observe without replay')
        lease = self.acquire(resource, client, principal=principal, work_item=work_item)
        with closing(self.control.store.connect('machine_input_control')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = self._row(db, resource)
            if not row or row['epoch'] != lease['epoch'] or row['client'] != client:
                raise AuthorizationRequired('terminal input possession changed before reservation')
            if db.execute("SELECT 1 FROM terminal_physical_input_effects WHERE resource=? AND state IN ('prepared','uncertain')", (resource['resource'],)).fetchone():
                raise AuthorizationRequired('another terminal input remains unconfirmed')
            db.execute("INSERT INTO terminal_physical_input_effects VALUES(?,?,?,?,?,?,?,'prepared',NULL,?)",
                (effect, self.owner, resource['resource'], key, payload, client, lease['epoch'], self.clock()))
        return {'input_protocol_version': PROTOCOL, **resource, 'owner': self.owner, 'client_id': client,
                'epoch': lease['epoch'], 'effect_key': 'terminal-input:' + effect, 'payload_sha256': payload}

    def existing(self,resource,key,data):
        """Host-only recovery of a prior selector, never permission to retry it."""
        if not isinstance(key,str) or not 1<=len(key)<=200 or not isinstance(data,bytes):
            raise ValueError('exact existing terminal input identity required')
        effect=digest([self.owner,resource['resource'],key])
        with closing(self.control.store.connect('machine_input_control')) as db:
            self._row(db,resource)
            row=db.execute('SELECT * FROM terminal_physical_input_effects WHERE effect_key=?',(effect,)).fetchone()
        if row is None:return None
        if row['owner']!=self.owner or row['resource']!=resource['resource'] or row['payload_sha256']!=hashlib.sha256(data).hexdigest():
            raise AuthorizationRequired('terminal input key belongs to another physical intent')
        return {'input_protocol_version':PROTOCOL,**resource,'owner':self.owner,'client_id':row['client'],
                'epoch':row['epoch'],'effect_key':'terminal-input:'+effect,'payload_sha256':row['payload_sha256']}

    def pending(self,resource):
        with closing(self.control.store.connect('machine_input_control')) as db:
            self._row(db,resource)
            rows=db.execute("SELECT * FROM terminal_physical_input_effects WHERE owner=? AND resource=? AND state IN ('prepared','uncertain') LIMIT 16",
                            (self.owner,resource['resource'])).fetchall()
        return [{'input_protocol_version':PROTOCOL,**resource,'owner':self.owner,'client_id':row['client'],
                 'epoch':row['epoch'],'effect_key':'terminal-input:'+row['effect_key'],'payload_sha256':row['payload_sha256']}
                for row in rows]

    def abandon_prepared(self,proof):
        """Retire an unattempted selector; a possible effect cannot be undone."""
        with closing(self.control.store.connect('machine_input_control')) as db,db:
            db.execute('BEGIN IMMEDIATE')
            effect=self._effect(db,proof)
            if effect['state']!='prepared':
                raise AuthorizationRequired('physical input may already have started')
            db.execute("UPDATE terminal_physical_input_effects SET state='not_started' WHERE effect_key=?",(effect['effect_key'],))

    def _effect(self, db, proof):
        if proof.get('input_protocol_version') != PROTOCOL or proof.get('owner') != self.owner:
            raise AuthorizationRequired('versioned terminal input proof required')
        key = proof.get('effect_key', '')
        if not isinstance(key, str) or not re.fullmatch(r'terminal-input:[0-9a-f]{64}', key):
            raise ValueError('physical terminal effect identity required')
        row = db.execute('SELECT * FROM terminal_physical_input_effects WHERE effect_key=?', (key.split(':')[1],)).fetchone()
        if (row is None or row['owner'] != self.owner or row['resource'] != proof.get('resource')
                or row['payload_sha256'] != proof.get('payload_sha256') or row['epoch'] != proof.get('epoch')
                or row['client'] != proof.get('client_id')):
            raise AuthorizationRequired('physical input proof differs from its central reservation')
        return row

    def _reference(self, proof, reference):
        from .pty_input_effects import validate_reference
        value=validate_reference(reference)
        with closing(self.control.store.connect('machine_input_control')) as db:
            effect=self._effect(db,proof)
        # Existing owner receipt keys must survive broker changes and journal
        # restore. Accept only this exact deterministic legacy identity, never
        # an arbitrary key supplied by a renderer or another reservation.
        legacy='host-input:'+hashlib.sha256(json.dumps([self.owner,proof['workspace'],proof['terminal'],effect['caller_key']],separators=(',',':')).encode()).hexdigest()
        if value['effect_key'] not in {proof['effect_key'],legacy}:
            raise AuthorizationRequired('daemon selector differs from reserved terminal input')
        expected={'effect_key':value['effect_key'],'workspace_id':proof['workspace'],
                  'terminal_id':proof['terminal'],'runtime_id':proof['runtime'],
                  'generation':proof['generation'],'payload_sha256':proof['payload_sha256']}
        if value!=expected:
            raise AuthorizationRequired('daemon selector differs from reserved terminal input')
        return value

    def bind_reference(self, proof, reference):
        """Persist a content-free exact daemon selector before crossing I/O."""
        from sentra_core.conversations import _encode,_decode
        value=self._reference(proof,reference)
        with closing(self.control.store.connect('machine_input_control')) as db,db:
            db.execute('BEGIN IMMEDIATE')
            effect=self._effect(db,proof);self._row(db,proof)
            row=db.execute('SELECT protected_reference FROM terminal_physical_input_refs WHERE effect_key=?',
                           (effect['effect_key'],)).fetchone()
            if row:
                if _decode(row['protected_reference'])!=value:
                    raise AuthorizationRequired('reserved daemon input selector changed')
                return value
            if effect['state']!='prepared':
                raise AuthorizationRequired('daemon correlation must precede the physical input attempt')
            db.execute('INSERT INTO terminal_physical_input_refs VALUES(?,?)',
                       (effect['effect_key'],_encode(value)))
        return value

    def daemon_reference(self, proof):
        from sentra_core.conversations import _decode
        with closing(self.control.store.connect('machine_input_control')) as db:
            effect=self._effect(db,proof);self._row(db,proof)
            row=db.execute('SELECT protected_reference FROM terminal_physical_input_refs WHERE effect_key=?',
                           (effect['effect_key'],)).fetchone()
        return self._reference(proof,_decode(row['protected_reference'])) if row else None

    def confirm_daemon_observation(self, proof, observed):
        """Trusted host-only adoption of an exact, already delivered receipt.

        This method never writes to a terminal, renews possession, or creates a
        Grant. Caller obtains `observed` from the existing authenticated daemon.
        """
        reference=self.daemon_reference(proof)
        if reference is None:
            raise AuthorizationRequired('input has no pre-effect daemon correlation')
        receipt=observed.get('receipt') if isinstance(observed,dict) else None
        if (not isinstance(receipt,dict) or type(observed.get('input_receipt_protocol_version')) is not int
                or observed['input_receipt_protocol_version']!=1 or observed.get('found') is not True
                or observed.get('resolved') is not True or observed.get('state')!='done'
                or observed.get('automatic_retry') is not False or observed.get('may_resend') is not False
                or observed.get('task_completion_verified') is not False
                or type(receipt.get('input_receipt_protocol_version')) is not int
                or receipt['input_receipt_protocol_version']!=1
                or any(receipt.get(k)!=v for k,v in reference.items())
                or receipt.get('stage')!='delivered_to_process'
                or receipt.get('automatic_retry') is not False
                or receipt.get('task_completion_verified') is not False):
            raise AuthorizationRequired('exact delivered daemon input evidence required')
        with closing(self.control.store.connect('machine_input_control')) as db,db:
            db.execute('BEGIN IMMEDIATE')
            effect=self._effect(db,proof);self._row(db,proof)
            if effect['state'] not in {'prepared','uncertain','delivered'}:
                raise AuthorizationRequired('terminal input observation is not recoverable')
            if effect['state']!='delivered':
                result={'effect_key':proof['effect_key'],'resource_id':proof['resource'],
                        'generation':proof['generation'],'runtime_id':proof['runtime'],
                        'client_id':proof['client_id'],'epoch':proof['epoch'],
                        'payload_sha256':proof['payload_sha256'],'stage':'delivered_to_process',
                        'task_completion_verified':False,'automatic_retry':False,
                        'recovered_by_observation':True}
                db.execute("UPDATE terminal_physical_input_effects SET state='delivered',receipt=? WHERE effect_key=?",
                           (json.dumps(result,sort_keys=True),effect['effect_key']))
        return self.inspect(proof)

    @contextmanager
    def physical(self, proof, data):
        with closing(self.control.store.connect('machine_input_control')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            effect = self._effect(db, proof)
            lease = self._row(db, proof)
            if (effect['state'] != 'prepared' or not lease or lease['epoch'] != proof['epoch']
                    or lease['client'] != proof['client_id'] or lease['expires'] <= self.clock()
                    or hashlib.sha256(data).hexdigest() != proof['payload_sha256']):
                raise AuthorizationRequired('physical input possession expired, changed or already attempted')
            self.authorize(proof, lease['principal'], lease['work_item'])
            # Commit the possible-effect boundary before calling the process.
            # A failed/aborted write must never roll back to a reusable proof.
            db.execute("UPDATE terminal_physical_input_effects SET state='uncertain' WHERE effect_key=?",
                       (proof['effect_key'].split(':')[1],))
        with closing(self.control.store.connect('machine_input_control')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            effect = self._effect(db, proof)
            lease = self._row(db, proof)
            if (effect['state'] != 'uncertain' or not lease or lease['epoch'] != proof['epoch']
                    or lease['client'] != proof['client_id'] or lease['expires'] <= self.clock()):
                raise AuthorizationRequired('terminal possession changed after possible-effect reservation')
            self.authorize(proof, lease['principal'], lease['work_item'])
            # Hold the central possession transaction through the actual write.
            # A handoff cannot acknowledge itself while this frame is in flight.
            yield
            receipt = {'effect_key': proof['effect_key'], 'resource_id': proof['resource'],
                       'generation': proof['generation'], 'runtime_id': proof['runtime'],
                       'client_id': proof['client_id'], 'epoch': proof['epoch'],
                       'payload_sha256': proof['payload_sha256'], 'stage': 'delivered_to_process',
                       'task_completion_verified': False, 'automatic_retry': False}
            db.execute("UPDATE terminal_physical_input_effects SET state='delivered',receipt=? WHERE effect_key=?",
                       (json.dumps(receipt, sort_keys=True), proof['effect_key'].split(':')[1]))

    def inspect(self, proof):
        with closing(self.control.store.connect('machine_input_control')) as db:
            effect = self._effect(db, proof)
            self._row(db, proof)
        return {'found': True, 'state': effect['state'], 'resolved': effect['state'] == 'delivered',
                'receipt': json.loads(effect['receipt']) if effect['receipt'] else None,
                'automatic_retry': False, 'may_resend': False}


def authority(canvas):
    with canvas._lock:
        value = getattr(canvas, '_terminal_possession', None)
        if value is None:
            value = TerminalPossession(canvas._shell_service(), canvas._runtime().owner)
            canvas._terminal_possession = value
        return value


def terminal_resource(canvas, workspace, terminal):
    canvas.store.resource('terminals', terminal, workspace)
    session = canvas._sessions.get(terminal)
    pty = getattr(session, 'pty', None)
    if pty is None:
        raise AuthorizationRequired('terminal is no longer attached')
    from .pty_client import DaemonPTY
    if isinstance(pty, DaemonPTY):
        if not getattr(pty, 'input_generation', None):
            raise AuthorizationRequired('existing daemon lacks versioned possession; observation remains available')
        generation, runtime = pty.input_generation, pty.runtime_id
    else:
        generation, runtime = session.input_instance_id, 'local:' + str(canvas.state_dir.resolve())
    return authority(canvas).resource(workspace, terminal, generation, runtime)


def input_control(canvas,workspace,terminal,action='status',expected_epoch=None):
    from .terminal import TerminalError
    client=current_client()
    try:
        resource=terminal_resource(canvas,workspace,terminal)
    except (AuthorizationRequired,TerminalError):
        if action!='status':raise
        return {'available':False,'can_write':False,'reason':'terminal_input_control_unavailable'}
    possession=authority(canvas)
    if action=='acquire':
        possession.acquire(resource,client,expected_epoch=expected_epoch)
    elif action=='takeover':
        # This owner-only entry point is never selected from a machine prompt.
        from sentra_runtime.effect_boundary import current_effect_context,CentralEffectContext
        if isinstance(current_effect_context.get(),CentralEffectContext):
            raise AuthorizationRequired('agent cannot force terminal ownership')
        possession.acquire(resource,client,expected_epoch=expected_epoch,takeover=True)
    elif action=='release':possession.release(resource,client,expected_epoch)
    elif action=='observe':
        for proof in possession.pending(resource):observe_terminal_input(canvas,proof)
    elif action!='status':raise ValueError('unsupported terminal input control action')
    value=possession.status(resource)
    return {**value,'available':True,'viewer_client_id':client,
            'can_write':not value['live'] or value['client_id']==client}


def write_terminal(canvas, workspace, terminal, data, key, *, reference=None, before_write=None):
    from sentra_runtime.effect_boundary import current_effect_context, CentralEffectContext
    resource = terminal_resource(canvas, workspace, terminal)
    possession = authority(canvas)
    effect = current_effect_context.get()
    principal = work_item = ''
    if isinstance(effect, CentralEffectContext):
        effect.checkpoint()
        principal, work_item = effect.request.principal_id, effect.request.work_item_id
    client = current_client()
    prior=possession.existing(resource,key,data)
    if prior is not None:
        observed=observe_terminal_input(canvas,prior)
        if observed['state']!='delivered':
            raise AuthorizationRequired('terminal input already reserved; observe without replay')
        if before_write:before_write(prior,possession.daemon_reference(prior))
        return {'physical_input':prior,**observed}
    proof = possession.prepare(resource, client, key, data, principal=principal, work_item=work_item)
    process = canvas._sessions[terminal].pty
    from .pty_client import DaemonPTY
    try:
        if isinstance(process,DaemonPTY):
            reference=reference or process.input_reference(proof['effect_key'],data)
            if process.input_reference(reference['effect_key'],data)!=reference:
                raise AuthorizationRequired('terminal generation changed before dispatch')
            possession.bind_reference(proof,reference)
        if before_write:before_write(proof,reference)
        with possession.physical(proof, data):
            if isinstance(effect, CentralEffectContext):
                effect.checkpoint()
            if isinstance(process,DaemonPTY):process.write_correlated(data,reference)
            else:process.write(data)
    except BaseException:
        # Admission failures before the possible-effect mark must not leave a
        # prepared selector blocking every later key. Never undo uncertainty.
        try:possession.abandon_prepared(proof)
        except Exception:pass
        raise
    return {'physical_input': proof, **possession.inspect(proof)}


def observe_terminal_input(canvas, proof):
    """Read existing receipts only; never connect-or-start or replay input."""
    possession=authority(canvas)
    current=possession.inspect(proof)
    if current['resolved']:
        return current
    reference=possession.daemon_reference(proof)
    client=getattr(canvas,'_pty_client',None)
    if reference is None or client is None or client.capabilities.get('correlated_input_receipts')!=1:
        return {**current,'observation_available':False}
    observed=client.call('input_effect',reference)
    if observed.get('found') is True and observed.get('resolved') is True:
        return possession.confirm_daemon_observation(proof,observed)
    return {**current,'observation_available':True}
