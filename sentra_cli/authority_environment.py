"""Consume Nexo's protected authority capsule without exporting a plaintext DSN."""
from sentra_runtime.provider_authority import ENVIRONMENT_KEY, load_provider_binding


def provider_child_environment(state_root, inherited):
    environment = dict(inherited)
    selector = environment.pop(ENVIRONMENT_KEY, None)
    for name in ("SENTRA_CONTROL_DSN", "SENTRA_POSTGRES_DSN", "SENTRA_CONTROL_BACKEND",
                 "SENTRA_CONTROL_TENANT_ID", "SENTRA_CONTROL_PRINCIPAL_ID",
                 "SENTRA_CANVAS_BEARER", "SENTRA_CANVAS_AGENT_TOKEN",
                 "SENTRA_CANVAS_AGENT_PORT", "SENTRA_CANVAS_AGENT_SCOPE"):
        environment.pop(name, None)
    if selector:
        binding = load_provider_binding(state_root)
        if binding is None:
            raise PermissionError("hosted CLI child lacks a valid authority capsule")
        environment[ENVIRONMENT_KEY] = selector
    return environment
