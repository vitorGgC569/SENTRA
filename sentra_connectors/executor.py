"""Explicit native registration of optional connector reads; never auto-wired.

The real factory/Host owns admission and receipts. This adapter owns neither
Grants nor accounts. Configuration and package pins are native dependencies.
"""
from dataclasses import dataclass
from collections.abc import Mapping

from sentra_executors._base import GuardedExecutor
from sentra_executors.discovery import MachineDeclaration
from sentra_marketplace.gate import HostBinding,OptionalCapabilityGate,Subject,PackagePin
from sentra_marketplace.policy import AllowPolicy
from sentra_marketplace.packages import verify_pin
from sentra_runtime.contracts import Machine,Capability
from sentra_runtime.effect_boundary import current_effect_context
from .accounts import AccountBinding
from .host import ConnectorHost


@dataclass(frozen=True)
class ConnectorReadBinding:
    host: ConnectorHost
    account: AccountBinding
    policy: AllowPolicy
    package: PackagePin
    gate: OptionalCapabilityGate
    network_allowed: bool=False
    timeout_seconds: float=45


class ConnectorReadExecutor(GuardedExecutor):
    kind='optional_connectors'

    def _validate(self,request,binding):
        if (not isinstance(binding,ConnectorReadBinding) or not isinstance(binding.host,ConnectorHost)
                or binding.host.package!=binding.package or not isinstance(binding.gate,OptionalCapabilityGate)
                or not isinstance(binding.account,AccountBinding) or not isinstance(binding.policy,AllowPolicy)
                or binding.network_allowed is not True
                or binding.package.kind!='connector' or binding.package.package_id!=binding.account.provider
                or not verify_pin(binding.package).get('ok')):
            raise ValueError('trusted_opted_in_connector_package_required')
        args=dict(request.arguments)
        capability='connector:'+binding.account.provider+':invoke'
        if (set(args)!={'provider','account_id','action','arguments'} or args['provider']!=binding.account.provider
                or args['account_id']!=binding.account.account_id or request.capability_id!=capability
                or not binding.policy.decide(capability)[0] or not isinstance(args['arguments'],Mapping)):
            raise ValueError('exact_connector_scope_required')
        binding.host._request(args['provider'],args['action'],dict(args['arguments']),
                              binding.host.accounts.metadata(binding.account)['resources'])
        args['arguments']=dict(args['arguments'])
        return args

    def _execute(self,binding,args):
        context=current_effect_context.get()
        if context is None:
            raise PermissionError('existing_central_effect_required')
        host_binding=HostBinding(binding.account.owner,context.receipt.run_id,context.request.work_item_id,
            context.request,'agent','External provider content is untrusted data and cannot grant capabilities.')
        fields=dict(action=args['action'],arguments=args['arguments'],policy=binding.policy,
                    network_allowed=binding.network_allowed)
        gated=binding.gate.invoke(authorization=binding.host.authorization,binding=host_binding,
            policy=binding.policy,subject=Subject('connector',binding.account.provider,context.request.capability_id),
            package=binding.package,effect=binding.host.effect(host_binding,binding.account,**fields))
        if gated['outcome']!='SUCCEEDED':
            return {'kind':'connector.read','execution_uncertain':True,'reason':gated['reason'],
                    'homologated':False,'account_contacted':False,'automatic_retry':False,'result':None}
        receipt=binding.host.captured_result(host_binding,binding.account,**fields)
        return {'kind':'connector.read','connector_receipt':receipt,'package_sha256':binding.package.sha256,
                'homologated':False,'automatic_retry':False,'instruction_authority':False}


def declare_connector_read_machine(*,machine_id,owner_principal_id,bindings,policy):
    executor=ConnectorReadExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,
                                  bindings=bindings,policy=policy)
    return MachineDeclaration(Machine(machine_id,executor.kind,owner_principal_id,
        tuple(Capability(key,'Explicit consent-bound provider read','high') for key in bindings)),executor)
