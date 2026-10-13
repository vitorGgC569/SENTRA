"""Host-only composition of real machine providers into the existing MachineHost.

No HTTP handler, scheduler, grants or alternative dispatch authority lives here.
Configuration contains secret references; callbacks resolve them only at runtime.
"""
from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path

from .central_integration import CentralExecutorFactory
from .identity_sessions import SessionJournal, SessionScope
from .rpa import AuthorizedPaths, ExecutorFailure

EXECUTOR_KINDS = frozenset({
    'windows_uia_semantic', 'windows_guest_uia', 'windows_guest_lifecycle',
    'windows_guest_artifact', 'windows_hcs_native', 'gvisor_workload',
})


def bind_shared_resource(declaration, *, state_root, resource_id):
    """Serialize aliases of one physical resource in the same central installation.

    The worker owns this lock until I/O returns, including after caller timeout.
    This lock supplies exclusion only; central admission still supplies authority.
    """
    from sentra_runtime.effect_boundary import _ResourceLock, ResourceEffectBusy
    if not isinstance(resource_id, str) or not resource_id:
        raise ValueError('explicit_physical_resource_required')
    adapter = declaration.adapter
    if getattr(adapter, '_shared_resource', None) is not None:
        raise ValueError('physical_resource_already_bound')
    execute = adapter._execute

    def guarded(binding, arguments):
        lock = _ResourceLock(Path(state_root) / 'input-resource-locks', resource_id)
        try:
            lock.acquire(0)
        except ResourceEffectBusy as exc:
            raise ExecutorFailure('physical_resource_owned_by_another_operation') from exc
        try:
            return execute(binding, arguments)
        finally:
            lock.release()

    adapter._execute = guarded
    adapter._shared_resource = resource_id
    return declaration


def _lease_reader(resource_id, lease_type):
    """Project the active central fence; never manufacture a second lease."""
    from sentra_runtime.effect_boundary import current_effect_context

    def read(expected_resource, scope):
        context = current_effect_context.get()
        if (context is None or expected_resource != resource_id or
                SessionScope.from_request(context.request).key != scope):
            raise ExecutorFailure('central_resource_effect_context_required')
        context.checkpoint()
        return lease_type(resource_id, scope, context.receipt.fencing_token,
                          time.monotonic() + context.authority.ttl_s)
    return read


def _secret(host, agent_id, ref, purpose):
    if not isinstance(ref, str) or not ref:
        raise ValueError('configured_secret_reference_required')
    host.control.secret_info(ref, host.owner)
    host.control.bind_secret(ref, host.owner, target_type='agent',
                             target_id=agent_id, purpose=purpose)
    return lambda: host.control.governance.resolve_secret_for_runtime(
        ref, host.owner, actor_type='agent', actor_id=agent_id, purpose=purpose)


def _guest(host, agent_id, machine_id, values):
    from .windows_guest import HyperVGuestConfig
    config = dict(values)
    username = config.pop('username_ref')
    password = config.pop('password_ref')
    user = _secret(host, agent_id, username, 'guest:' + machine_id + ':username')
    secret = _secret(host, agent_id, password, 'guest:' + machine_id + ':password')
    if 'credential' in config:
        raise ValueError('guest_credentials_must_use_secret_references')
    config['credential'] = lambda: (user(), secret())
    config['guest_source_pins'] = tuple(tuple(pin) for pin in config['guest_source_pins'])
    if 'allowed_switch_ids' in config:
        config['allowed_switch_ids'] = tuple(config['allowed_switch_ids'])
    return HyperVGuestConfig(**config)


def _uia_bindings(values, paths):
    from .uia_semantic import DesktopIdentity, UIASelector, SemanticUIABinding
    from .windows_identity import ProcessIdentity
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise ValueError('bounded_uia_bindings_required')
    bindings = []
    for value in values:
        config = dict(value)
        if 'paths' in config:
            raise ValueError('host_owns_uia_output_paths')
        config['identity'] = ProcessIdentity(**config['identity'])
        config['desktop'] = DesktopIdentity(**config['desktop'])
        selectors = []
        for selector in config['selectors']:
            item = dict(selector)
            if 'actions' in item:
                item['actions'] = tuple(item['actions'])
            selectors.append(UIASelector(**item))
        config['selectors'] = tuple(selectors)
        if 'actions' in config:
            config['actions'] = tuple(config['actions'])
        bindings.append(SemanticUIABinding(paths=paths, **config))
    if len({b.capability_id for b in bindings}) != len(bindings):
        raise ValueError('duplicate_uia_capability')
    # One declaration cannot conflate independent interactive desktops.
    if len({b.desktop for b in bindings}) != 1:
        raise ValueError('one_interactive_desktop_per_machine_required')
    return tuple(bindings)


def configure_executor(host, *, workspace_id, workspace_root, agent_id, kind, provider_config):
    """Synchronous MachineHost extension. Caller must validate owner/workspace/agent.

    The wrapper uses the host's existing loop; registration does not run a provider.
    Missing optional services remain errors on actual admitted operations.
    """
    return host._call(_configure_executor(host, workspace_id=workspace_id,
        workspace_root=workspace_root, agent_id=agent_id, kind=kind,
        provider_config=provider_config))


async def _configure_executor(host, *, workspace_id, workspace_root, agent_id, kind, provider_config):
    from sentra_runtime.workspace_paths import workspace_paths
    if kind not in EXECUTOR_KINDS or not isinstance(provider_config, dict):
        raise ValueError('supported_explicit_executor_configuration_required')
    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir() or not workspace_id or not agent_id:
        raise ValueError('trusted_workspace_and_agent_required')
    persisted = json.loads(json.dumps(provider_config, allow_nan=False))
    if len(json.dumps(persisted).encode()) > 256 * 1024:
        raise ValueError('executor_configuration_byte_limit')
    config = json.loads(json.dumps(persisted))
    if config.pop('enabled', None) is not True:
        raise ValueError('executor_must_be_explicitly_enabled')
    machine_id = host._machine_id(workspace_id, agent_id, kind)
    if machine_id in host._inventory:
        raise ValueError('executor_configuration_is_immutable')
    paths = workspace_paths(root, host.control.durable.root)
    private = host.control.durable.root / 'provider-state' / machine_id
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    journal = SessionJournal(str(private / 'sessions.sqlite3'),
                             AuthorizedPaths((str(private),), (str(private),)))
    factory = CentralExecutorFactory(control=host.control, owner=host.owner, agent_id=agent_id)
    common = dict(machine_id=machine_id, owner_principal_id=agent_id, policy=factory.policy)

    if kind in {'windows_uia_semantic', 'windows_guest_uia'}:
        bindings = _uia_bindings(config.pop('bindings'), paths)
        if kind == 'windows_uia_semantic':
            from .uia_semantic import declare_semantic_windows_machine
            declaration = declare_semantic_windows_machine(bindings=bindings, **common)
            desktop = bindings[0].desktop
            resource = 'desktop:' + desktop.machine_guid.lower() + ':' + str(desktop.session_id)
        else:
            from .windows_guest import GuestLease, declare_windows_guest_uia_machine
            guest = _guest(host, agent_id, machine_id, config.pop('guest'))
            declaration = declare_windows_guest_uia_machine(bindings=bindings, guest_config=guest,
                lease_reader=_lease_reader(guest.vm_id, GuestLease), **common)
            resource = 'hyperv:' + guest.vm_id
    elif kind in {'windows_guest_lifecycle', 'windows_guest_artifact'}:
        from .windows_guest import (GuestLease, HyperVFixtureBinding, GuestArtifactBinding,
            declare_hyperv_fixture_machine, declare_guest_artifact_machine)
        guest = _guest(host, agent_id, machine_id, config.pop('guest'))
        reader = _lease_reader(guest.vm_id, GuestLease)
        if kind == 'windows_guest_lifecycle':
            binding = HyperVFixtureBinding('guest:lifecycle', guest,
                actions=tuple(config.pop('actions', ('status',))))
            bindings = (binding,)
            declaration = declare_hyperv_fixture_machine(bindings=bindings, lease_reader=reader, **common)
        else:
            inventory = config.pop('artifacts')
            if not isinstance(inventory, dict) or len(inventory) > 256:
                raise ValueError('bounded_guest_artifact_inventory_required')
            binding = GuestArtifactBinding('guest:artifact', guest, tuple(sorted(inventory.items())), paths)
            bindings = (binding,)
            declaration = declare_guest_artifact_machine(bindings=bindings, lease_reader=reader, **common)
        resource = 'hyperv:' + guest.vm_id
    elif kind == 'windows_hcs_native':
        from .hcs_provider import HCSCommand, NativeHCSBinding, declare_native_hcs_machine
        profile = config.pop('binding')
        if set(profile) & {'capability_id', 'host_paths', 'paths'}:
            raise ValueError('host_owns_hcs_paths_and_capability')
        profile = dict(profile)
        host_roots = config.pop('host_read_roots')
        host_paths = AuthorizedPaths(tuple(host_roots), ())
        profile['commands'] = tuple(HCSCommand(**value) for value in profile.get('commands', []))
        if 'actions' in profile:
            profile['actions'] = tuple(profile['actions'])
        binding = NativeHCSBinding('hcs:workload', host_paths=host_paths, paths=paths, **profile)
        bindings = (binding,)
        declaration = declare_native_hcs_machine(bindings=bindings, journal=journal, **common)
        resource = 'hcs:' + binding.container_id
    else:
        from .gvisor_workload import RunscWorkloadBinding, WorkloadLease, declare_runsc_workload_machine
        profile = dict(config.pop('binding'))
        if set(profile) & {'capability_id', 'paths', 'state_root', 'checkpoint_root'}:
            raise ValueError('host_owns_runsc_paths_and_capability')
        state = private / 'runsc'; checkpoints = private / 'checkpoints'
        state.mkdir(mode=0o700, exist_ok=True); checkpoints.mkdir(mode=0o700, exist_ok=True)
        for key in ('actions', 'allowed_readonly_mounts'):
            if key in profile:
                profile[key] = tuple(profile[key])
        binding = RunscWorkloadBinding('gvisor:workload', paths=paths,
            state_root=str(state), checkpoint_root=str(checkpoints), **profile)
        bindings = (binding,)
        declaration = declare_runsc_workload_machine(bindings=bindings, journal=journal,
            lease_reader=_lease_reader(binding.container_id, WorkloadLease), **common)
        resource = 'runsc:' + binding.container_id
    if config:
        raise ValueError('unsupported_executor_configuration_fields')
    bind_shared_resource(declaration, state_root=host.control.durable.root, resource_id=resource)
    factory.register_execution(declaration)
    inventory = dict(machine_id=machine_id, kind=kind, workspace_id=workspace_id,
        agent_id=agent_id, capabilities=[b.capability_id for b in bindings],
        actions={b.capability_id: list(getattr(b, 'actions', ('collect',))) for b in bindings},
        registered=True, grant_created=False, transport_ready='unverified',
        provider_verified=False, physical_resource_sha256=hashlib.sha256(resource.encode()).hexdigest())
    host.configurations.put(machine_id, dict(kind=kind, workspace_id=workspace_id,
        workspace_root=str(root), agent_id=agent_id, provider_config=persisted))
    host._factories[machine_id] = factory
    host._inventory[machine_id] = inventory
    return dict(inventory)


def suggest_machines(candidates, *, required_capabilities, load_by_machine=None, limit=5):
    """Rank the host's already-authorized catalog; this never creates permission.

    Unknown load sorts after observed idle/busy load, rather than pretending idle.
    The caller supplies central scheduler observations, never renderer estimates.
    """
    required = set(required_capabilities)
    if (not required or any(not isinstance(c, str) or not c for c in required) or
            type(limit) is not int or not 1 <= limit <= 20):
        raise ValueError('bounded_required_capabilities_and_limit_required')
    loads = load_by_machine or {}
    result = []
    for candidate in candidates:
        if not required <= set(candidate.get('capabilities', ())):
            continue
        ident = candidate['machine_id']; load = loads.get(ident)
        if load is not None and (type(load) is not int or load < 0):
            raise ValueError('nonnegative_observed_machine_load_required')
        result.append({**candidate, 'observed_active_operations': load,
                       'suggestion_only': True, 'grant_created': False})
    result.sort(key=lambda item: (item['observed_active_operations'] is None,
        item['observed_active_operations'] or 0, item['machine_id']))
    return result[:limit]
