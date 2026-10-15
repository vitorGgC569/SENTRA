"""Failures for the peer gateway. None of these retry a side effect."""


class FederationDenied(PermissionError):
    """The Control Plane, the pairing state, or the message shape refused the request."""


class FederationUncertain(RuntimeError):
    """The receipt did not arrive. The intent stays put and is not sent again."""
