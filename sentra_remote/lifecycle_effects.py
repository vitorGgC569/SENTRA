"""Host-owned checkpoint propagated to every composed lifecycle effect."""
from contextlib import contextmanager
from contextvars import ContextVar

_checkpoint = ContextVar("sentra_lifecycle_checkpoint", default=None)
_providers = ContextVar("sentra_lifecycle_provider_context", default=None)


@contextmanager
def lifecycle_scope(checkpoint, *, provider_context=None):
    if not callable(checkpoint):
        raise PermissionError("trusted lifecycle checkpoint required")
    token = _checkpoint.set(checkpoint)
    providers_token = _providers.set(provider_context)
    try:
        yield
    finally:
        _checkpoint.reset(token)
        _providers.reset(providers_token)


def provider_context():
    value = _providers.get()
    if not isinstance(value, dict):
        raise RuntimeError("host provider configuration is not composed")
    return value


def checkpoint_effect():
    check = _checkpoint.get()
    if check is not None:
        check()
        return
    from sentra_runtime.effect_boundary import current_effect_context
    context = current_effect_context.get()
    if context is None:
        raise PermissionError("lifecycle effect requires an admitted host operation")
    context.checkpoint()
