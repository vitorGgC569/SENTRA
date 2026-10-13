"""Identity check for host-injected Pacto stores; never a Grant or DB fallback."""
from pathlib import Path


def require_same_store(left, right, *, namespace="plugin_bundle"):
    if left is right:
        return
    if getattr(left, "backend", None) != getattr(right, "backend", None):
        raise PermissionError("Pacto stores use different authorities")
    if getattr(left, "backend", None) == "postgres":
        names = ("tenant_id", "principal_id", "_dsn")
        if any(not getattr(left, key, None) or getattr(left, key) != getattr(right, key, None) for key in names):
            raise PermissionError("Pacto PostgreSQL authority/tenant/principal differs")
        # DSN never leaves this comparison or appears in errors/projections.
    elif getattr(left, "backend", None) == "sqlite":
        a, b = left.path_for(namespace), right.path_for(namespace)
        if a is None or b is None or Path(a).resolve() != Path(b).resolve():
            raise PermissionError("Pacto local authority differs")
    else:
        raise PermissionError("Pacto authority identity unavailable")
