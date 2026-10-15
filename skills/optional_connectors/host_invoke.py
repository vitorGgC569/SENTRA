"""Explicit host adapter, separate from the offline legacy entry.

The native host supplies a ConnectorHost, HostBinding, AccountBinding and exact
AllowPolicy after opt-in. JSON/model content cannot construct those authorities.
No token, account service or enabled network is discovered from ambient state.
"""
from sentra_connectors import ConnectorHost


def run(context):
    if not isinstance(context, dict) or not isinstance(context.get('host'), ConnectorHost):
        raise PermissionError('CONNECTOR_TRUSTED_HOST_REQUIRED')
    return context['host'].invoke(context['binding'], context['account'],
        action=context['action'], arguments=context['arguments'], policy=context['policy'],
        network_allowed=context.get('network_allowed') is True)
