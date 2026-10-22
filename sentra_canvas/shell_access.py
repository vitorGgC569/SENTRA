"""Owner-selected access profiles; execution still uses central task admission."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import time

from sentra_core.conversations import _encode, _decode
from sentra_runtime.contracts import PolicyDecision
from sentra_runtime.executor import AuthorizationRequired
from .shell_requests import ShellHostRequests

ACCESS_ACTIONS = frozenset({'access_status', 'access_set', 'access_approve', 'access_reject'})


class AccessStore:
    def __init__(self, control, owner):
        self.control, self.owner = control, owner
        with closing(control.store.connect('shell')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS shell_access_profiles(owner TEXT, conversation TEXT, body TEXT, PRIMARY KEY(owner,conversation))')
            db.execute('CREATE TABLE IF NOT EXISTS shell_access_requests(owner TEXT, operation TEXT, conversation TEXT, body TEXT, PRIMARY KEY(owner,operation))')

    def raw_profile(self, cid):
        with closing(self.control.store.connect('shell')) as db:
            row = db.execute('SELECT body FROM shell_access_profiles WHERE owner=? AND conversation=?', (self.owner, cid)).fetchone()
        return _decode(row['body']) if row else {'mode': 'ask', 'scope': 'workspace', 'approval': 'ask'}

    def profile(self, cid):
        profile = self.raw_profile(cid)
        if profile.get('full_source'):
            from .full_access import source
            if source(self.control, self.owner, cid) is None:
                return {**profile, 'mode': 'ask', 'approval': 'ask', 'scope': 'workspace', 'delegation_revoked': True}
        return profile

    def save(self, cid, value):
        with closing(self.control.store.connect('shell')) as db, db:
            db.execute('INSERT OR REPLACE INTO shell_access_profiles VALUES(?,?,?)', (self.owner, cid, _encode(value)))

    def requests(self, cid):
        with closing(self.control.store.connect('shell')) as db:
            rows = db.execute('SELECT body FROM shell_access_requests WHERE owner=? AND conversation=?', (self.owner, cid)).fetchall()
        return [_decode(row['body']) for row in rows]

    def save_request(self, cid, value):
        with closing(self.control.store.connect('shell')) as db, db:
            db.execute('INSERT OR REPLACE INTO shell_access_requests VALUES(?,?,?,?)', (self.owner, value['operation_id'], cid, _encode(value)))

    def policy(self, base, workspace_root):
        root = Path(workspace_root).resolve()
        def check(request):
            decision = base(request)
            if not decision.allowed:
                return decision
            item = self.control.work_item_info(request.work_item_id, self.owner)
            cid = item.get('metadata', {}).get('conversation_id')
            if not cid:
                return PolicyDecision(False, 'conversation access scope required')
            profile = self.profile(cid)
            if profile.get('delegation_revoked'):
                return PolicyDecision(False, 'full-access delegation was revoked')
            if profile.get('work_item_id') != request.work_item_id:
                return PolicyDecision(False, 'access profile changed')
            # Inventory reads reveal capabilities; they never authorize a physical action.
            if not request.arguments:
                return decision
            from .task_workspace import directory
            selected=directory(self.control,self.owner,request,root).resolve()
            args = dict(request.arguments)
            path = Path(args.get('path') or args.get('cwd') or selected)
            path = (selected / path).resolve() if not path.is_absolute() else path.resolve()
            inside = path.is_relative_to(selected)
            private = path.is_relative_to(Path(self.control.durable.root).resolve()) and not (selected!=root and inside)
            in_scope = (profile['scope'] == 'computer' or inside) and not private
            read = request.capability_id == 'computer:file.read'
            command = args.get('command', '')
            # Deliberately narrow: only single read-only commands bypass approval.
            import re
            safe_command = bool(re.fullmatch(r'(?:pwd|Get-Location|Get-ChildItem|git status|git diff)', command.strip(), re.I))
            if (profile['approval'] == 'never' and (profile['scope'] == 'computer' or (inside and not private))) or (profile['approval'] == 'auto' and in_scope and (read or (inside and (safe_command or request.capability_id == 'computer:file.write')))) or (profile['approval'] == 'ask' and in_scope and read):
                return decision
            fingerprint = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
            old = next((row for row in self.requests(cid) if row['operation_id'] == request.operation_id), None)
            if old and (old['fingerprint']!=fingerprint or old['work_item_id']!=request.work_item_id):
                return PolicyDecision(False,'approval operation identity changed')
            if old and (old['state'] in {'rejected','expired'} or old['state']=='pending' and time.time()>=old.get('expires_at',old['created_at']+300)):
                return PolicyDecision(False, 'approval request expired or rejected')
            if old and old['fingerprint'] == fingerprint and old['work_item_id'] == request.work_item_id and old['state'] in {'approved', 'SUCCEEDED', 'FAILED', 'UNCERTAIN'}:
                if old['state']=='approved' and time.time()>=old.get('expires_at',old['created_at']+300):return PolicyDecision(False,'approval expired before execution')
                return decision
            if old and old['state'] == 'rejected':
                return PolicyDecision(False, 'owner rejected this operation')
            if old and old['state']=='pending':return PolicyDecision(False,'approval_required: confira o pedido nesta conversa')
            self.save_request(cid, {'operation_id': request.operation_id, 'work_item_id': request.work_item_id,
                'machine_id': request.machine_id, 'capability_id': request.capability_id,
                'arguments': args, 'fingerprint': fingerprint, 'state': 'pending', 'created_at': time.time(),
                'expires_at':time.time()+300,'reason':str(args.get('reason') or item.get('objective') or 'Continuar o trabalho desta conversa')[:300]})
            return PolicyDecision(False, 'approval_required: confira o pedido nesta conversa')
        return check


def dispatch_access(canvas, pid, action, params, key, *, inherited_from=None, default_profile=False):
    fields = {'space_id', 'conversation_id'} | ({'mode', 'scope', 'approval', 'capabilities'} if action == 'access_set' else {'target_operation_id','expected_fingerprint'} if action in {'access_approve', 'access_reject'} else set())
    if set(params) - fields or not {'space_id', 'conversation_id'} <= params.keys():
        raise ValueError('canonical conversation access scope required')
    control, owner = canvas._shell_service(), canvas._runtime().owner
    with closing(control.store.connect('shell')) as db:
        convo = control.shell._entity(db, owner, pid, 'conversation', params['conversation_id'], space_id=params['space_id'])
        dot = control.shell._entity(db, owner, pid, 'dot', convo['dot_id'], space_id=params['space_id'])
    store = AccessStore(control, owner)
    cid = convo['conversation_id']
    def view():
        profile = store.profile(cid)
        if not profile.get('work_item_id') and any(job['authorized'] for job in canvas.center_file_work_items(pid, cid)['items']):
            profile = {**profile, 'mode': 'custom', 'legacy_authorization': True}
        from .permission_presentation import present_access_request
        root=Path(canvas.store.workspace(pid)['path']).resolve()
        requests=[present_access_request(r,root,dot) for r in store.requests(cid) if r['state']=='pending']
        return {**profile, 'requests': requests}
    if action == 'access_status':
        return view()
    def mutate():
        requests=ShellHostRequests(control,owner)
        requests.note_before_admission(pid,key)
        if action == 'access_set':
            mode = params.get('mode')
            if mode not in {'ask', 'auto', 'full', 'custom'}:
                raise ValueError('unsupported access profile')
            scope, approval = {'ask': ('workspace', 'ask'), 'auto': ('workspace', 'auto'), 'full': ('computer', 'never'), 'custom': (params.get('scope'), params.get('approval'))}[mode]
            if scope not in {'workspace', 'computer'} or approval not in {'ask', 'auto', 'never'}:
                raise ValueError('invalid custom access settings')
            from sentra_executors.local_computer import CAPABILITIES
            capabilities = params.get('capabilities', list(CAPABILITIES))
            if not isinstance(capabilities, list) or any(cap not in CAPABILITIES for cap in capabilities) or len(set(capabilities)) != len(capabilities) or (mode != 'custom' and set(capabilities) != set(CAPABILITIES)):
                raise ValueError('invalid custom capabilities')
            host = canvas._machine_service()
            requests.note_effect_possible(pid,key)
            machine = host.configure_computer(workspace_id=pid, workspace_root=canvas.store.workspace(pid)['path'], agent_id=dot['agent_id'])
            # Explicit owner selection replaces legacy authorizations, so a downgrade is effective.
            for job in canvas.center_file_work_items(pid, cid)['items']:
                if job['authorized']:
                    canvas.center_revoke_files(pid, job['work_item_id'], cid, approve=True)
            old = store.profile(cid)
            from .full_access import revoke_source, track
            if old.get('work_item_id'):
                revoke_source(control, owner, old['work_item_id'])
                revoke_source(control, owner, old['work_item_id'], cid)
            if old.get('work_item_id'):
                for grant in control.authorization.list_grants(owner, principal_type='agent', principal_id=dot['agent_id'])['items']:
                    if grant['scope_type'] == 'work_item' and grant['scope_id'] == old['work_item_id'] and not grant['revoked']:
                        control.authorization_revoke(grant['grant_id'], owner)
                previous = control.work_item_info(old['work_item_id'], owner)
                if previous['state'] in {'RUNNING', 'QUEUED', 'PENDING'}:
                    control.transition_work_item(old['work_item_id'], owner, 'CANCELLED')
            run = canvas._runtime().run(pid)
            if run['state'] == 'CREATED':
                canvas._runtime().durable.transition_run(run['run_id'], owner, 'RUNNING')
            elif run['state'] != 'RUNNING':
                raise AuthorizationRequired('resume the project before configuring access')
            item = control.create_work_item(run['run_id'], owner, work_item_id='access-' + hashlib.sha256((pid + key).encode()).hexdigest()[:24],
                objective='Acesso selecionado nesta conversa', assignee_agent_id=dot['agent_id'], required_capabilities=capabilities,
                metadata={'workspace_id': pid, 'machine_id': machine['machine_id'], 'conversation_id': cid,
                    'access_owner_selected':not default_profile and inherited_from is None,
                    **({'full_source_work_item':inherited_from['work_item_id']} if inherited_from else {})})
            for cap in capabilities:
                control.authorization_grant(owner, principal_type='agent', principal_id=dot['agent_id'], capability=cap, scope_type='work_item', scope_id=item['work_item_id'])
            control.transition_work_item(item['work_item_id'], owner, 'RUNNING')
            if inherited_from:
                track(control, owner, inherited_from, item['work_item_id'], dot['agent_id'], 'computer')
            store.save(cid, {'mode': mode, 'scope': scope, 'approval': approval, 'capabilities': capabilities, 'work_item_id': item['work_item_id'], 'machine_id': machine['machine_id'], 'owner_selected':not default_profile and inherited_from is None,
                **({'full_source':inherited_from} if inherited_from else {})})
            for row in store.requests(cid):
                if row['state'] == 'pending':
                    store.save_request(cid, {**row, 'state': 'rejected'})
        else:
            row = next((r for r in store.requests(cid) if r['operation_id'] == params['target_operation_id']), None)
            if not row or row['state'] != 'pending' or row['work_item_id'] != store.profile(cid).get('work_item_id'):
                raise AuthorizationRequired('approval request is stale or belongs to another conversation')
            if params.get('expected_fingerprint') is not None and params['expected_fingerprint']!=row['fingerprint']:
                raise AuthorizationRequired('reviewed action changed')
            if action=='access_approve' and time.time()>=row.get('expires_at',row['created_at']+300):
                raise AuthorizationRequired('approval request expired; request a new action')
            requests.note_effect_possible(pid,key)
            row['state'] = 'approved' if action == 'access_approve' else 'rejected'
            store.save_request(cid, row)
            if action == 'access_approve':
                result = canvas._machine_service().dispatch(workspace_id=pid, work_item_id=row['work_item_id'], machine_id=row['machine_id'], capability_id=row['capability_id'], operation_id=row['operation_id'], arguments=row['arguments'], idempotency_key=row['operation_id'])
                store.save_request(cid, {**row, 'state': result['state']})
                from .permission_presentation import panel_hint
                return {**view(), 'result': result,'panel_hint':panel_hint(row,Path(canvas.store.workspace(pid)['path']).resolve()) if result.get('state')=='SUCCEEDED' else None}
        return view()
    with canvas._lock:
        return ShellHostRequests(control, owner).invoke(pid, action, params, key, mutate)
