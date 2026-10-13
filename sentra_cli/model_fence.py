"""Live model/tool admission against UsageLedger's selected central authority."""
from contextlib import closing
import json

from sentra_mcp.services.authorization import AuthorizationService
from sentra_runtime.provider_authority import load_provider_binding


class ModelInvocationFence:
    def __init__(self, ledger, *, state_root, shell_context=None):
        self.ledger, self.store = ledger, ledger.governance.store
        self.state_root, self.shell_context = state_root, shell_context
        self.authorization = AuthorizationService(state_root, store=self.store)
        self._anchors = {}
        self._model_required = set()

    def _state(self, context):
        owner = context['owner']
        self.store.assert_principal(owner)
        work = self.ledger.governance.work_item_info(context['work_item_id'], owner)
        with closing(self.store.connect('durable')) as db:
            run = db.execute('SELECT * FROM runs WHERE owner=? AND run_id=?', (owner, context['run_id'])).fetchone()
            actor = db.execute('SELECT * FROM agents WHERE owner=? AND agent_id=?', (owner, context['agent_id'])).fetchone()
            operation = db.execute('SELECT * FROM operations WHERE owner=? AND operation_id=?', (owner, context['operation_id'])).fetchone()
        if (run is None or actor is None or operation is None or
            run['state'] != 'RUNNING' or run['desired_state'] != 'RUNNING' or
            run['workspace'] != context['workspace'] or work['state'] != 'RUNNING' or
            work['run_id'] != context['run_id'] or work['assignee_agent_id'] != context['agent_id'] or
            actor['run_id'] != context['run_id'] or actor['desired_state'] in {'WAITING', 'DEAD', 'ORPHANED', 'RECOVERING'} or
            operation['run_id'] != context['run_id'] or operation['state'] not in {'STARTING', 'RUNNING'}):
            raise PermissionError('model/tool execution was paused, revoked, terminated or reassigned')
        progress = json.loads(operation['progress_json'])
        linked = progress.get('work_item_id') == context['work_item_id'] and progress.get('principal_id') == context['agent_id']
        legacy = (operation['kind'] == 'canvas.agent_task' and
            progress.get('canvas_task_id') == work['metadata'].get('canvas_task_id') and
            progress.get('agent_id') == context['agent_id'] and
            work['metadata'].get('operation_id') == context['operation_id'])
        if not linked and not legacy:
            raise PermissionError('model/tool Operation differs from the current WorkItem/assignee')
        return work

    def checkpoint(self, session_id, workspace, *, provider=None, expected=None):
        context = self.ledger.context(session_id, workspace)
        if expected is not None and context != expected:
            raise PermissionError('model authority changed after the submission admission')
        capsule = load_provider_binding(self.state_root)
        selected = getattr(self.store, 'provider_binding', None)
        if selected is not None and (capsule is None or any(capsule.get(k) != selected.get(k) for k in
            ('owner', 'tenant_id', 'principal_id', 'authority_revision', 'conversation_id', 'project_id', 'run_id', 'work_item_id', 'operation_id', 'agent_id'))):
            raise PermissionError('model authority capsule expired or was replaced')
        if not context.get('work_item_id'):
            if self.shell_context is not None or selected is not None:
                raise PermissionError('shell provider requires its canonical WorkItem')
            return context  # Existing standalone owner CLI; no child capability invented.
        fields = ('owner', 'workspace', 'run_id', 'work_item_id', 'operation_id', 'agent_id')
        if any(not context.get(k) for k in fields):
            raise PermissionError('model/tool execution requires a complete central binding')
        anchor = tuple(context[k] for k in fields)
        if self._anchors.setdefault(session_id, anchor) != anchor:
            raise PermissionError('model/tool execution binding changed within the session')
        if self.shell_context is not None:
            observed = self.shell_context()
            scope = observed.get('shell_scope') if isinstance(observed, dict) else None
            if (not isinstance(scope, dict) or scope.get('conversation_id') != session_id or
                any(scope.get(k) != context[k] for k in ('run_id', 'work_item_id', 'agent_id')) or
                scope.get('parent_operation_id') != context['operation_id']):
                raise PermissionError('shell actor token is no longer bound to the live model turn')
        work = self._state(context)
        if capsule is not None and work['metadata'].get('workspace_id') != capsule['project_id']:
            raise PermissionError('model WorkItem moved outside its native capsule project')
        required = work.get('required_capabilities')
        if not isinstance(required, (list, tuple)):
            raise PermissionError('canonical WorkItem model requirements unavailable')
        if 'model:invoke' in required:
            self._model_required.add(session_id)
        elif session_id in self._model_required:
            raise PermissionError('child model requirement changed after admission')
        if 'model:invoke' in required:
            decision = self.authorization.require(context['owner'], principal_type='agent',
                principal_id=work['assignee_agent_id'], capability='model:invoke',
                scope_type='work_item', scope_id=work['work_item_id'],
                context={'provider': provider or 'sentra-cli', 'actual_cost': float('inf')}, local_owner=False)
            if decision.get('source') != 'grant' or not decision.get('grant_id'):
                raise PermissionError('child model requires its own current agent Grant')
        if self.ledger.context(session_id, workspace) != context or self._state(context) != work:
            raise PermissionError('model/tool authority changed during the checkpoint')
        return context
