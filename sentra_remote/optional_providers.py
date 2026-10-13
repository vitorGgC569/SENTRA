"""Optional provider lifecycle: install/health/repair/recovery/remove (Vitra-owned).

Optional components stay complete requirements: real configuration flow,
explicit unavailable state, cancel/revoke/recovery and distribution notes.
Deny-only responses, stubs and fixtures never substitute implementation.

Every effect requires explicit user approval plus a host-injected runner.
Without a runner the operation fails explicitly as unavailable; nothing is
silently executed, downloaded or removed. Transitive pins, SBOM entries
and NOTICE records are tracked per file so release composition (Codex)
can verify provenance without trusting remote claims.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

SCHEMA = 1

Runner = Callable[[str, dict[str, Any]], dict[str, Any]]

PROVIDERS: dict[str, dict[str, Any]] = {
    "git": {
        "display": "Git",
        "package": "Git.Git",
        "pin_version": "2.47.1",
        "source": "winget",
        "license": "GPL-2.0-only",
        "notice": "sentra_remote/provider_notices/git-NOTICE.txt",
    },
    "docker": {
        "display": "Docker Desktop",
        "package": "Docker.DockerDesktop",
        "pin_version": "4.34.3",
        "source": "winget",
        "license": "Docker Subscription Agreement",
        "notice": "sentra_remote/provider_notices/docker-NOTICE.txt",
    },
    "ollama": {
        "display": "Ollama local models",
        "package": "Ollama.Ollama",
        "pin_version": "0.6.8",
        "source": "winget",
        "license": "MIT",
        "notice": "sentra_remote/provider_notices/ollama-NOTICE.txt",
    },
    "tunnel-client": {
        "display": "OpenAI tunnel client",
        "package": None,
        "pin_version": "0.0.14",
        "pin_sha256": "784ab8da7b5a88f0109f1fd8aaf0a1c86067430b896dddf307ef7e3cc49fa1a5",
        "source": "https://github.com/openai/tunnel-client/releases/download/",
        "license": "MIT",
        "notice": "sentra_remote/provider_notices/tunnel-client-NOTICE.txt",
    },
    "pdfium": {
        "display": "PDFium (pypdfium2)",
        "package": None,
        "pin_version": "4.30.0",
        "source": "pypi",
        "license": "BSD-3-Clause",
        "notice": "sentra_remote/provider_notices/pdfium-NOTICE.txt",
    },
    "web-models": {
        "display": "Web Models (Electron)",
        "package": None,
        "pin_version": "tracked-in-integration-build.json",
        "source": "vendored payload",
        "license": "see web-models/licenses/codex-chatgpt-web/LICENSE",
        "notice": "sentra_remote/provider_notices/web-models-NOTICE.txt",
    },
    "electron": {
        "display": "Electron display",
        "package": None,
        "pin_version": "tracked-in-sentra-surface-build.json",
        "source": "npm pinned",
        "license": "MIT",
        "notice": "sentra_remote/provider_notices/electron-NOTICE.txt",
    },
}

VALID_STATES = frozenset({
    "absent", "installable", "installing", "ready",
    "degraded", "unavailable", "removed", "revoked",
})


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    name: str
    state: str
    detail: str
    pin_version: str = ""
    sbom_tracked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_provider(name: str) -> dict[str, Any]:
    spec = PROVIDERS.get(name)
    if spec is None:
        raise ValueError("unknown optional provider")
    return spec


def describe_provider(name: str, probe: dict[str, Any] | None = None) -> ProviderStatus:
    """Pure projection over a verified health probe. Never claims readiness without proof."""
    spec = _require_provider(name)
    probe = probe if isinstance(probe, dict) else {}
    if probe.get("ready") is True:
        state, detail = "ready", str(probe.get("detail") or f"{spec['display']} is ready.")
    elif probe.get("degraded") is True:
        state, detail = "degraded", str(probe.get("detail") or f"{spec['display']} needs attention.")
    elif probe.get("installed") is True:
        state, detail = "degraded", str(probe.get("detail") or f"{spec['display']} installed but not healthy.")
    elif probe.get("unavailable") is True:
        state, detail = "unavailable", str(probe.get("detail") or f"{spec['display']} explicitly unavailable.")
    else:
        state, detail = "installable", f"Optional: {spec['display']} can be installed with approval."
    return ProviderStatus(name=name, state=state, detail=detail,
                          pin_version=str(spec.get("pin_version") or ""),
                          sbom_tracked=True)


def _admit(action: str, name: str, *, approved: bool, runner: Runner | None) -> Runner:
    _require_provider(name)
    if action not in {"install", "repair", "recovery", "remove", "health", "renew", "configure"}:
        raise ValueError("unknown provider action")
    if action in {"install", "repair", "recovery", "remove", "renew", "configure"} and approved is not True:
        raise PermissionError(f"provider {action} requires explicit user approval")
    if runner is None or not callable(runner):
        raise ValueError(f"provider {action} unavailable: no host runner configured for {name}")
    return runner


def provider_configure(name: str, *, approved: bool = False, runner: Runner | None = None) -> dict[str, Any]:
    run = _admit('configure', name, approved=approved, runner=runner)
    result = run('configure', {'provider': name, 'pin': PROVIDERS[name]})
    if not isinstance(result, dict):
        raise ValueError('provider configuration runner returned invalid evidence')
    return {'schema': SCHEMA, 'provider': name, 'action': 'configure', **result}


def provider_install(name: str, *, approved: bool = False,
                     runner: Runner | None = None) -> dict[str, Any]:
    """Install an optional provider via the host runner. Cancel = do not approve."""
    run = _admit("install", name, approved=approved, runner=runner)
    result = run("install", {"provider": name, "pin": PROVIDERS[name]})
    if not isinstance(result, dict):
        raise ValueError("provider runner returned an invalid result")
    return {"schema": SCHEMA, "provider": name, "action": "install", **result}


def provider_health(name: str, *, runner: Runner | None = None) -> dict[str, Any]:
    run = _admit("health", name, approved=True, runner=runner)
    result = run("health", {"provider": name})
    if not isinstance(result, dict):
        raise ValueError("provider runner returned an invalid result")
    return {"schema": SCHEMA, "provider": name, "action": "health", **result}


def provider_repair(name: str, *, approved: bool = False,
                    runner: Runner | None = None) -> dict[str, Any]:
    run = _admit("repair", name, approved=approved, runner=runner)
    result = run("repair", {"provider": name, "pin": PROVIDERS[name]})
    if not isinstance(result, dict):
        raise ValueError("provider runner returned an invalid result")
    return {"schema": SCHEMA, "provider": name, "action": "repair", **result}


def provider_recovery(name: str, *, approved: bool = False,
                      runner: Runner | None = None) -> dict[str, Any]:
    """Explicit recovery after interrupted install/repair. No auto-retry."""
    run = _admit("recovery", name, approved=approved, runner=runner)
    result = run("recovery", {"provider": name, "pin": PROVIDERS[name]})
    if not isinstance(result, dict):
        raise ValueError("provider runner returned an invalid result")
    return {"schema": SCHEMA, "provider": name, "action": "recovery", **result}


def provider_remove(name: str, *, approved: bool = False,
                    runner: Runner | None = None) -> dict[str, Any]:
    """Remove an optional provider. Revokes its local registration; never touches user data."""
    run = _admit("remove", name, approved=approved, runner=runner)
    result = run("remove", {"provider": name})
    if not isinstance(result, dict):
        raise ValueError("provider runner returned an invalid result")
    return {"schema": SCHEMA, "provider": name, "action": "remove", **result}


def provider_revoke(name: str, *, approved: bool = False,
                    runner: Runner | None = None) -> dict[str, Any]:
    """Cancel/revoke a pending provider operation (install/repair in flight)."""
    run = _admit("recovery", name, approved=approved, runner=runner)
    result = run("revoke", {"provider": name})
    if not isinstance(result, dict):
        raise ValueError("provider runner returned an invalid result")
    return {"schema": SCHEMA, "provider": name, "action": "revoke", **result}


def provider_renew(name: str, *, approved: bool = False,
                   runner: Runner | None = None) -> dict[str, Any]:
    """Renew a provider registration: re-verify pin + live health, re-seat config.

    Covers credential/scope renewal (tunnel client, ollama daemon) and pin
    re-verification after repair. Explicit approval; without a runner the
    renewal is explicitly unavailable, never silently skipped.
    """
    run = _admit("renew", name, approved=approved, runner=runner)
    result = run("renew", {"provider": name, "pin": PROVIDERS[name]})
    if not isinstance(result, dict):
        raise ValueError("provider runner returned an invalid result")
    return {"schema": SCHEMA, "provider": name, "action": "renew", **result}


def transitive_inventory() -> dict[str, Any]:
    """Per-file pins/SBOM/NOTICE inventory for release composition (read-only)."""
    files: list[dict[str, Any]] = []
    for name, spec in sorted(PROVIDERS.items()):
        files.append({
            "provider": name,
            "display": spec.get("display"),
            "pin_version": spec.get("pin_version"),
            "pin_sha256": spec.get("pin_sha256", ""),
            "sbom_purl": f"pkg:generic/{name}@{spec.get('pin_version')}",
            "notice": spec.get("notice"),
            "license": spec.get("license"),
            "source": spec.get("source"),
        })
    return {"schema": SCHEMA, "files": files, "count": len(files)}
