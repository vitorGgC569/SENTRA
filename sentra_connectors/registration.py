"""Native authenticated-owner composition helper; never called by import/JSON.

Root must explicitly wire this at the trusted host boundary. No discovery of
accounts/credentials, OAuth, Grant creation, provider I/O or automatic opt-in.
"""
import hashlib
from pathlib import Path
from sentra_executors.central_integration import CentralExecutorFactory
from sentra_marketplace.gate import OptionalCapabilityGate,PackagePin
from sentra_marketplace.packages import verify_pin
from sentra_marketplace.policy import AllowPolicy
from sentra_runtime.machine_host import MachineHost
from .accounts import AccountBinding,ConnectorAccounts
from .executor import ConnectorReadBinding,declare_connector_read_machine
from .host import ConnectorHost


def connector_identity_kind(account):
    return 'optional_connectors-'+hashlib.sha256((account.provider+'\0'+account.account_id).encode()).hexdigest()[:16]


def connector_machine_id(workspace_id,agent_id,account):
    account.key()
    return MachineHost._machine_id(workspace_id,agent_id,connector_identity_kind(account))


def configure_connector_read(host,*,workspace_id,workspace_root,agent_id,account,package,policy,
                             network_allowed=False,transport=None):
    if (not isinstance(host,MachineHost) or not isinstance(account,AccountBinding)
            or account.owner!=host.owner or account.key()[1]!=str(Path(workspace_root).resolve(strict=True))
            or not isinstance(workspace_id,str) or not workspace_id or not isinstance(agent_id,str) or not agent_id
            or not isinstance(package,PackagePin) or package.kind!='connector' or package.package_id!=account.provider
            or not verify_pin(package).get('ok') or not isinstance(policy,AllowPolicy) or network_allowed is not True):
        raise ValueError('native_owner_scoped_connector_configuration_required')
    capability='connector:'+account.provider+':invoke'
    if not policy.decide(capability)[0]:
        raise PermissionError('explicit_connector_policy_required')
    machine=connector_machine_id(workspace_id,agent_id,account)
    config={'kind':connector_identity_kind(account),'workspace_id':workspace_id,'workspace_root':account.key()[1],
        'agent_id':agent_id,'provider':account.provider,'account_id':account.account_id,
        'package':{'package_id':package.package_id,'kind':package.kind,'path':package.path,'sha256':package.sha256},
        'allowed_capabilities':[capability],'network_allowed':True}
    async def configure():
        if machine in host._factories:
            prior=next((value['configuration'] for value in host.configurations.entries() if value['machine_id']==machine),None)
            if prior!=config:raise ValueError('connector_reconfiguration_requires_explicit_replacement')
            return dict(host._inventory[machine])
        accounts=ConnectorAccounts(host.control.store)
        accounts.metadata(account)  # Consent exists; no secret or network read.
        connector=ConnectorHost(accounts,host.control.authorization,control=host.control,package=package,transport=transport)
        owner_key=hashlib.sha256(host.owner.encode()).hexdigest()
        gate=OptionalCapabilityGate(host.control.durable.root/'optional-connectors'/owner_key)
        binding=ConnectorReadBinding(connector,account,policy,package,gate,network_allowed=True)
        factory=CentralExecutorFactory(control=host.control,owner=host.owner,agent_id=agent_id)
        declaration=declare_connector_read_machine(machine_id=machine,owner_principal_id=agent_id,
                                                   bindings={capability:binding},policy=factory.policy)
        factory.register_execution(declaration)
        inventory={'machine_id':machine,'kind':declaration.machine.kind,'workspace_id':workspace_id,'agent_id':agent_id,
                   'provider':account.provider,'account_id':account.account_id,'capabilities':[capability],
                   'account_contacted':False,'homologated':False}
        host.configurations.put(machine,config)
        host._factories[machine]=factory;host._inventory[machine]=inventory
        return dict(inventory)
    return host._call(configure())


def restore_connector_read(host,config,*,transport=None):
    """Call only after MachineHost.restore's native validate_scope succeeds."""
    keys={'kind','workspace_id','workspace_root','agent_id','provider','account_id','package','allowed_capabilities','network_allowed'}
    if not isinstance(config,dict) or set(config)!=keys:
        raise ValueError('exact_protected_connector_configuration_required')
    account=AccountBinding(host.owner,config['workspace_root'],config['provider'],config['account_id'])
    if (config['kind']!=connector_identity_kind(account)
            or config['allowed_capabilities']!=['connector:'+account.provider+':invoke']
            or not isinstance(config['package'],dict)
            or set(config['package'])!={'package_id','kind','path','sha256'}):
        raise ValueError('protected_connector_identity_changed')
    return configure_connector_read(host,workspace_id=config['workspace_id'],workspace_root=config['workspace_root'],
        agent_id=config['agent_id'],account=account,package=PackagePin(**config['package']),
        policy=AllowPolicy(tuple(config['allowed_capabilities'])),network_allowed=config['network_allowed'],transport=transport)
