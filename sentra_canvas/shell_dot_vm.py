"""Exclusive per-root Dot VMs with durable host resource reservations.

Owner-selected local images configure authority; agents can then request the
same centrally admitted machine actions without acquiring owner identity.
"""
from contextlib import closing
from pathlib import Path
import ctypes
import hashlib
import os
import secrets
import time
import uuid

from sentra_core.conversations import _encode, _decode
from sentra_runtime.authority_bridge import BoundWorkItemPolicy
from sentra_runtime.contracts import OperationRequest, PolicyDecision
from .shell_dot_canvas import dots_for_root
from .shell_requests import ShellHostRequests
from .shell_access import AccessStore
from .store import Denied

DOT_VM_READS = frozenset({'dot_vm_status', 'dot_vm_frame', 'dot_vm_images'})
DOT_VM_ACTIONS = DOT_VM_READS | frozenset({'dot_vm_configure', 'dot_vm_execute', 'dot_vm_input', 'dot_vm_handoff'})


def host_resources():
    if os.name == 'nt':
        class Memory(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [(name, ctypes.c_ulonglong)
                for name in ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]
        memory = Memory(); memory.length = ctypes.sizeof(memory)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise RuntimeError('physical host memory unavailable')
        total = memory.total
    else:
        total = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    cpus = os.cpu_count() or 1
    return {'logical_cpus': cpus, 'physical_memory_mb': total // 1048576,
        'max_cpus': cpus // 2, 'max_memory_mb': total // 2 // 1048576,
        'resource_fraction': 0.5, 'limit_kind': 'configured_vcpu_and_ram'}


class VmStore:
    def __init__(self, control, owner):
        self.control, self.owner = control, owner
        with closing(control.store.connect('shell')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS shell_dot_vms(owner TEXT NOT NULL,project TEXT NOT NULL,root TEXT NOT NULL,'
                'cpus INTEGER NOT NULL,memory_mb INTEGER NOT NULL,body TEXT NOT NULL,PRIMARY KEY(owner,project,root))')

    def get(self, project, root):
        with closing(self.control.store.connect('shell')) as db:
            row = db.execute('SELECT body FROM shell_dot_vms WHERE owner=? AND project=? AND root=?',
                (self.owner, project, root)).fetchone()
        return _decode(row['body']) if row else None

    def budget(self):
        with closing(self.control.store.connect('shell')) as db:
            row = db.execute('SELECT COALESCE(SUM(cpus),0) cpus,COALESCE(SUM(memory_mb),0) memory_mb FROM shell_dot_vms').fetchone()
        return {**host_resources(), 'reserved_cpus': row['cpus'], 'reserved_memory_mb': row['memory_mb']}

    def reserve(self, project, root, value):
        limits = host_resources()
        with closing(self.control.store.connect('shell')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT COALESCE(SUM(cpus),0) cpus,COALESCE(SUM(memory_mb),0) memory_mb FROM shell_dot_vms '
                'WHERE NOT(owner=? AND project=? AND root=?)', (self.owner, project, root)).fetchone()
            if value['cpus'] + row['cpus'] > limits['max_cpus'] or value['memory_mb'] + row['memory_mb'] > limits['max_memory_mb']:
                raise ValueError('Dot VMs exceed the aggregate 50% configured CPU/RAM limit')
            current = db.execute('SELECT body FROM shell_dot_vms WHERE owner=? AND project=? AND root=?',
                (self.owner, project, root)).fetchone()
            if current:
                previous = _decode(current['body'])
                value = {**value, 'work_items': {**previous.get('work_items', {}), **value.get('work_items', {})}}
            db.execute('INSERT INTO shell_dot_vms VALUES(?,?,?,?,?,?) ON CONFLICT(owner,project,root) DO UPDATE '
                'SET cpus=excluded.cpus,memory_mb=excluded.memory_mb,body=excluded.body',
                (self.owner, project, root, value['cpus'], value['memory_mb'], _encode(value)))

    def patch(self, project, root, **updates):
        if {'cpus', 'memory_mb'} & updates.keys():
            raise ValueError('hardware changes require a resource reservation')
        with closing(self.control.store.connect('shell')) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM shell_dot_vms WHERE owner=? AND project=? AND root=?',
                (self.owner, project, root)).fetchone()
            if not row:
                raise Denied('Dot VM configuration required')
            value = _decode(row['body'])
            if 'work_items' in updates:
                updates['work_items'] = {**value.get('work_items', {}), **updates['work_items']}
            db.execute('UPDATE shell_dot_vms SET body=? WHERE owner=? AND project=? AND root=?',
                (_encode({**value, **updates}), self.owner, project, root))

    def policy(self, base, project, root):
        def check(request):
            decision = base(request)
            if not decision.allowed:
                return decision
            value = self.get(project, root)
            item = self.control.work_item_info(request.work_item_id, self.owner)
            metadata = item.get('metadata') or {}
            cid = metadata.get('conversation_id')
            bindings = (value or {}).get('work_items', {})
            if not value or bindings.get(cid) != request.work_item_id or value['machine_id'] != request.machine_id or metadata.get('machine_id') != value['machine_id'] or metadata.get('root_dot_id') != root or metadata.get('workspace_id') != project or item.get('assignee_agent_id') != value['agent_id']:
                return PolicyDecision(False, 'VM configuration replaced')
            if request.capability_id == 'vm:observe':
                return decision
            # Human-owned input is authorized by the enclosing InputBoundPolicy's
            # authenticated human_input_scope/epoch. Do not reject that scope
            # here: a second blanket vm:input check would break takeover.
            # Agent input while the human holds the lease is still denied by
            # InputBoundPolicy on every effect checkpoint.
            if request.capability_id in {'vm:manage', 'vm:guest'}:
                from sentra_executors.input_control import InputControl
                resource = hashlib.sha256(('virtualbox:' + value['vm_id']).encode()).hexdigest()
                possession = InputControl(self.control, owner=self.owner).status(resource_id=resource, workspace_id=project)
                if possession.get('holder') == 'human' and possession.get('live'):
                    return PolicyDecision(False, 'human controls this VM; agent guest and lifecycle effects are fenced')
            # VM WorkItem/Grants are separate from the host-file profile.
            # Restricting host files cannot revoke this Dot's own guest;
            # revoking a vm:* Grant still fails in the base policy above.
            budget = self.budget()
            if budget['reserved_cpus'] > budget['max_cpus'] or budget['reserved_memory_mb'] > budget['max_memory_mb']:
                return PolicyDecision(False, 'physical host resource limit changed')
            return decision
        return check


def configure_virtualbox_machine(host, *, workspace_id, workspace_root, agent_id, root_dot_id):
    from sentra_executors.central_integration import CentralExecutorFactory
    from sentra_executors.discovery import MachineDeclaration
    from sentra_executors.virtualbox_vm import VirtualBoxBinding, VirtualBoxExecutor, VM_CAPABILITIES, VM_ACTIONS
    from sentra_runtime.contracts import Capability, Machine
    async def configure():
        mid = host._machine_id(workspace_id, agent_id, 'virtualbox_vm')
        if mid in host._inventory:
            return dict(host._inventory[mid])
        store = VmStore(host.control, host.owner)
        value = store.get(workspace_id, root_dot_id)
        if not value or value['agent_id'] != agent_id or value['machine_id'] != mid:
            raise Denied('canonical Dot VM configuration required')
        factory = CentralExecutorFactory(control=host.control, owner=host.owner, agent_id=agent_id)
        factory.policy = store.policy(factory.policy, workspace_id, root_dot_id)
        binding = VirtualBoxBinding(value['vm_id'], value['marker'], lambda: store.get(workspace_id, root_dot_id),
            workspace_root=str(workspace_root))
        executor = VirtualBoxExecutor(machine_id=mid, owner_principal_id=agent_id,
            bindings={cap: binding for cap in VM_CAPABILITIES}, policy=factory.policy)
        factory.register_execution(MachineDeclaration(Machine(mid, 'virtualbox_vm', agent_id,
            tuple(Capability(cap, cap, 'high') for cap in VM_CAPABILITIES)), executor))
        inventory = {'machine_id': mid, 'kind': 'virtualbox_vm', 'agent_id': agent_id, 'workspace_id': workspace_id,
            'capabilities': list(VM_CAPABILITIES), 'actions': {cap: list(actions) for cap, actions in VM_ACTIONS.items()},
            'registered': True, 'root_dot_id': root_dot_id, 'vm_id': value['vm_id']}
        host._factories[mid], host._inventory[mid] = factory, inventory
        host.configurations.put(mid, {'kind': 'virtualbox_vm', 'workspace_id': workspace_id,
            'workspace_root': workspace_root, 'agent_id': agent_id, 'root_dot_id': root_dot_id})
        return dict(inventory)
    return host._call(configure())


class DotVmServices:
    def __init__(self, canvas):
        self.canvas, self.host = canvas, canvas._machine_service()
        self.store = VmStore(self.host.control, self.host.owner)
        self.requests = ShellHostRequests(self.host.control, self.host.owner)

    def scope(self, pid, params):
        root, dots = dots_for_root(self.host.control, self.host.owner, pid, params.get('dot_id'), params.get('space_id'))
        dot = next(item for item in dots if item['dot_id'] == params.get('dot_id'))
        cid = params.get('conversation_id')
        if not cid:
            raise ValueError('owning conversation required for VM authority')
        with closing(self.host.control.store.connect('shell')) as db:
            convo = self.host.control.shell._entity(db, self.host.owner, pid, 'conversation', cid, space_id=dot['space_id'])
        if convo['dot_id'] != dot['dot_id']:
            raise Denied('VM belongs exclusively to the selected Dot conversation')
        return dot['dot_id'], dot, convo

    def status(self, pid, root, conversation_id=None):
        from sentra_executors.virtualbox_vm import VirtualBoxClient, executable
        value = self.store.get(pid, root)
        path = executable()
        # Rebind the SAME canonical machine after a broker/UI restart. The
        # persisted VM UUID/work-item/grants belong to this Dot; registration
        # is host metadata only and never starts or replays a VM operation.
        rebind_error = None
        if value and path and value.get('agent_id') and value.get('machine_id'):
            try:
                configure_virtualbox_machine(self.host, workspace_id=pid,
                    workspace_root=self.canvas.store.workspace(pid)['path'],
                    agent_id=value['agent_id'], root_dot_id=root)
            except (ValueError, PermissionError, RuntimeError, OSError) as exc:
                rebind_error = type(exc).__name__
        public = {key: item for key, item in (value or {}).items() if key not in {'password', 'marker', 'base_folder', 'work_items', 'work_item_id', 'conversation_id'}}
        wid = (value or {}).get('work_items', {}).get(conversation_id)
        if value:
            public.update(conversation_id=conversation_id, work_item_id=wid, conversation_authorized=bool(wid))
        result = {'vm': public or None, 'host': self.store.budget(), 'hypervisor_available': bool(path),
            'image_required': not bool(value and value.get('iso_path')), 'live_view_transport': 'virtualbox-com-framebuffer',
            'os_ready_verified': False}
        if value and value.get('installation_verification'):
            result['installation'] = dict(value['installation_verification'])
        if rebind_error:
            result['provider_status'] = 'rebind_failed:' + rebind_error
        if value and path:
            try:
                client = VirtualBoxClient(path)
                if value['vm_id'] in client.run('list', 'vms', physical=False):
                    from sentra_executors.virtualbox_vm import VirtualBoxBinding
                    info = client.status(VirtualBoxBinding(value['vm_id'], value['marker'], None))
                    result['vm']['vm_state'] = info.get('VMState')
                    result['vm']['actual_cpus'] = info.get('cpus')
                    result['vm']['actual_memory_mb'] = info.get('memory')
                else:
                    result['vm']['vm_state'] = 'not_created'
            except Exception:
                result['provider_status'] = 'unavailable'
        if value and wid:
            try:
                result['input'] = self.host.input_status(workspace_id=pid, machine_id=value['machine_id'],
                    work_item_id=wid, capability_id='vm:input')
            except Exception:
                result['input'] = {'holder': 'none', 'live': False, 'epoch': 0}
        return result

    def dispatch(self, pid, action, params, key=None):
        fields = {'dot_id', 'space_id', 'conversation_id'} | {
            'dot_vm_configure': {'os_family', 'cpus', 'memory_mb', 'disk_gb', 'iso_path'},
            'dot_vm_execute': {'arguments'}, 'dot_vm_input': {'arguments', 'expected_epoch'},
            'dot_vm_handoff': {'holder', 'expected_epoch'}}.get(action, set())
        if action not in DOT_VM_ACTIONS or set(params) - fields:
            raise ValueError('unsupported Dot VM request')
        root, dot, convo = self.scope(pid, params)
        if action == 'dot_vm_status':
            return self.status(pid, root, convo['conversation_id'])
        if action == 'dot_vm_images':
            # Only two host-known roots: the selected workspace and the
            # installation root. Renderer input never chooses a search path.
            folders = [Path(self.canvas.store.workspace(pid)['path']) / 'Isos',
                self.canvas.project_dir / 'Isos']
            images, seen = [], set()
            for folder in folders:
                if not folder.is_dir() or folder.is_symlink():
                    continue
                base = folder.resolve(strict=True)
                for image in sorted(folder.iterdir(), key=lambda p:p.name.casefold()):
                    if len(images) >= 32:
                        break
                    if image.is_symlink() or not image.is_file() or image.suffix.lower() != '.iso':
                        continue
                    resolved = image.resolve(strict=True)
                    if resolved.parent != base or resolved in seen or not 128 * 1024 * 1024 <= resolved.stat().st_size <= 12 * 1024**3:
                        continue
                    seen.add(resolved)
                    images.append({'name':image.name, 'path':str(resolved),
                        'size_bytes':resolved.stat().st_size})
            return {'items':images, 'download_performed':False}
        if action == 'dot_vm_configure':
            return self.requests.invoke(pid, action, params, key,
                lambda: self._configure(pid, root, dot, convo, params, key))
        value = self.store.get(pid, root)
        wid = (value or {}).get('work_items', {}).get(convo['conversation_id'])
        if not value or not wid:
            raise Denied('configure this Dot VM in its owning conversation first')
        if action == 'dot_vm_frame':
            status = self.status(pid, root, convo['conversation_id'])
            if status['vm'].get('vm_state') not in {'running', 'paused'}:
                return {'status': 'unavailable', 'vm_state': status['vm'].get('vm_state'), 'image_base64': None}
            result = self.host.dispatch(workspace_id=pid, machine_id=value['machine_id'], work_item_id=wid,
                capability_id='vm:observe', operation_id='vm-frame-' + uuid.uuid4().hex,
                arguments={'action': 'frame'})
            if result['state'] != 'SUCCEEDED':
                return {'status': 'unavailable', 'state': result['state'], 'image_base64': None}
            return {'status': 'live', **result['evidence']}
        def execute():
            arguments = params.get('arguments')
            common = dict(workspace_id=pid, machine_id=value['machine_id'], work_item_id=wid,
                operation_id=self.requests.operation_id(pid, key, action), idempotency_key=key)
            if action == 'dot_vm_handoff':
                holder = params.get('holder')
                if holder not in {'human', 'agent'}:
                    raise ValueError('human or agent holder required')
                result = self.host.input_handoff(workspace_id=pid, machine_id=value['machine_id'],
                    work_item_id=wid, capability_id='vm:input', holder=holder,
                    expected_epoch=params.get('expected_epoch'), ttl_seconds=300,
                    operation_id=common['operation_id'], request_key=key,
                    arguments={'action': 'input.key', 'scancodes': [0xAA]})
                return {**result, 'input': self.status(pid, root, convo['conversation_id'])['input']}
            if not isinstance(arguments, dict):
                raise ValueError('VM action arguments required')
            if action == 'dot_vm_input':
                result = self.host.dispatch_human(**common, capability_id='vm:input', arguments=arguments,
                    expected_epoch=params.get('expected_epoch'))
            else:
                capability = 'vm:guest' if arguments.get('action') in {'guest.run', 'installation.verify', 'project.import'} else 'vm:manage'
                result = self.host.dispatch(**common, capability_id=capability, arguments=arguments)
            if result['state'] == 'SUCCEEDED':
                evidence = result.get('evidence', {})
                updates = {'provisioning_status':evidence.get('status', value.get('provisioning_status'))}
                if action == 'dot_vm_execute' and arguments.get('action') == 'installation.verify':
                    updates['installation_verification'] = {
                        key:evidence[key] for key in ('status','vm_id','disk_uuid','installed_os_verified',
                            'desktop_ready_verified','boot_mode','root_source','root_uuid') if key in evidence}
                    updates['installation_verification']['verified_at'] = time.time()
                if action == 'dot_vm_execute' and arguments.get('action') == 'project.import':
                    updates['last_project_import'] = {
                        key:evidence[key] for key in ('status','guest_path','files','source_bytes','sha256') if key in evidence}
                self.store.patch(pid, root, **updates)
            elif result['state'] == 'UNCERTAIN' and action == 'dot_vm_execute' and arguments.get('action') == 'provision':
                # Keep the reservation and the uncertain receipt; do not silently
                # retry a physical creation attempt or label it ready to create.
                self.store.patch(pid, root, provisioning_status='uncertain_requires_reconciliation')
            return result
        return self.requests.invoke(pid, action, params, key, execute)

    def _configure(self, pid, root, dot, convo, params, key):
        from sentra_executors.virtualbox_vm import VirtualBoxClient, VM_CAPABILITIES
        old = self.store.get(pid, root)
        family = params.get('os_family')
        cpus, memory, disk = params.get('cpus'), params.get('memory_mb'), params.get('disk_gb', 64)
        if family not in {'linux', 'windows'} or type(cpus) is not int or type(memory) is not int or type(disk) is not int or cpus < (2 if family == 'windows' else 1) or memory < (4096 if family == 'windows' else 1024) or not (64 if family == 'windows' else 16) <= disk <= 256:
            raise ValueError('valid Linux/Windows CPU, RAM and disk configuration required')
        iso = params.get('iso_path') or ''
        sha = None
        if iso:
            image = Path(iso).resolve(strict=True)
            if image.suffix.lower() != '.iso' or not image.is_file():
                raise ValueError('existing local ISO file required')
            with image.open('rb') as source:
                sha = hashlib.file_digest(source, 'sha256').hexdigest()
            iso = str(image)
        existing = bool(old and old['vm_id'] in VirtualBoxClient().run('list', 'vms', physical=False))
        if existing and any(old.get(field) != selected for field, selected in {
                'os_family':family, 'cpus':cpus, 'memory_mb':memory, 'disk_gb':disk, 'iso_path':iso, 'iso_sha256':sha}.items()):
            raise ValueError('existing VM hardware and OS are immutable; use unchanged settings to bind another conversation')
        mid = self.host._machine_id(pid, dot['agent_id'], 'virtualbox_vm')
        identity = uuid.uuid5(uuid.NAMESPACE_URL, '|'.join((self.host.owner, pid, root)))
        value = {**(old or {}), 'vm_id': str(identity), 'machine_id': mid, 'root_dot_id': root, 'agent_id': dot['agent_id'],
            'conversation_id': (old or {}).get('conversation_id', convo['conversation_id']), 'work_items': (old or {}).get('work_items', {}), 'os_family': family, 'cpus': cpus, 'memory_mb': memory,
            'disk_gb': disk, 'iso_path': iso, 'iso_sha256': sha, 'name': 'SENTRA-Dot-' + identity.hex[:16],
            'marker': 'SENTRA-DOT:' + str(identity), 'base_folder': str(Path(self.host.control.durable.root) / 'dot-vms'),
            'password': (old or {}).get('password') or secrets.token_urlsafe(24), 'provisioning_status': (old or {}).get('provisioning_status', 'ready_to_create' if iso else 'pending_image'),
            'configured_at': time.time()}
        control, owner = self.host.control, self.host.owner
        run = self.canvas._runtime().run(pid)
        if run['state'] != 'RUNNING':
            raise Denied('resume the project before reserving or authorizing a VM')
        self.store.reserve(pid, root, value)
        configure_virtualbox_machine(self.host, workspace_id=pid, workspace_root=self.canvas.store.workspace(pid)['path'],
            agent_id=dot['agent_id'], root_dot_id=root)
        if not value['work_items'].get(convo['conversation_id']):
            work_identity = uuid.uuid5(identity, convo['conversation_id'])
            item = control.create_work_item(run['run_id'], owner, work_item_id='vm-' + work_identity.hex,
                objective='Computador exclusivo deste Dot', assignee_agent_id=dot['agent_id'], required_capabilities=list(VM_CAPABILITIES),
                metadata={'workspace_id': pid, 'machine_id': mid, 'conversation_id': convo['conversation_id'], 'root_dot_id': root})
            for capability in VM_CAPABILITIES:
                control.authorization_grant(owner, principal_type='agent', principal_id=dot['agent_id'], capability=capability,
                    scope_type='work_item', scope_id=item['work_item_id'])
            control.transition_work_item(item['work_item_id'], owner, 'RUNNING')
            self.store.patch(pid, root, work_item_id=(old or {}).get('work_item_id', item['work_item_id']),
                work_items={**value['work_items'], convo['conversation_id']:item['work_item_id']})
        return self.status(pid, root, convo['conversation_id'])
