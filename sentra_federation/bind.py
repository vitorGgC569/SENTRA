"""Bind policy for the peer gateway.

Loopback and private addresses are accepted. Any other address is accepted
only when the operator passes that network in ``documented_networks`` and the
prefix is at least /8. Unspecified, multicast and overly broad networks are
refused. This is a bind rule, not an authorization decision.
"""
from __future__ import annotations

import ipaddress


class BindRefused(PermissionError):
    pass


def documented_networks(values=()):
    if not isinstance(values, (tuple, list)) or len(values) > 8:
        raise BindRefused("documented networks must be a short list")
    parsed = []
    for value in values:
        try:
            network = ipaddress.ip_network(str(value), strict=False)
        except ValueError as exc:
            raise BindRefused("invalid documented network") from exc
        if network.prefixlen < 8 or network.is_unspecified or network.is_multicast:
            raise BindRefused("documented network is too broad")
        parsed.append(network)
    return tuple(parsed)


def _address(host):
    try:
        address = ipaddress.ip_address(str(host))
    except ValueError as exc:
        raise BindRefused("invalid bind address") from exc
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        raise BindRefused("public or unspecified bind refused")
    return address


def assert_private_bind(host, documented=()):
    """Return the address a listener may bind.

    Only loopback and private addresses bind. A documented global range is not
    a license to open a public port. ``documented`` is accepted so callers stay
    stable; it cannot widen the bind.
    """
    del documented
    address = _address(host)
    if address.is_loopback or address.is_private:
        return str(address)
    raise BindRefused("public bind refused")


def host_class(host, documented=()):
    address = ipaddress.ip_address(assert_private_bind(host, documented))
    if address.is_loopback:
        return "loopback"
    if address.is_private:
        return "private"
    return "documented-private"


def assert_destination(host, port, documented=()):
    """Return a dial or discovery address. This does not authorize execution."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise BindRefused("invalid peer port")
    address = _address(host)
    extras = documented_networks(documented)
    if address.is_loopback or address.is_private or any(address in network for network in extras):
        return str(address), port
    raise BindRefused("peer address is outside the documented private network")
