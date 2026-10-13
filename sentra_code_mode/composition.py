"""Drop-in composition helpers for the central owner (Codex).

Owner: Pacto. This module holds NO authority: every helper takes the host's
already-authenticated ``control`` (ControlPlaneService) and explicit
``owner``/``root``/WorkItem scope callbacks. Codex wires these into
``sentra_canvas/service.py`` + ``server.py`` + shell bridge with a few lines
each (see docstrings); Pacto never edits those files.

Shell envelope rules follow docs/SENTRA_SHELL_BRIDGE_INTEGRATION_2026-10-11.md:
POST-only JSON, allowlisted ``action``, ``request_key`` for mutating actions,
``project_id`` canonical with legacy ``ws`` alias normalized on input.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Mapping

from . import QuickJSArtifact, ResourceLimits

CODE_MODE_SHELL_ACTIONS = ("code_propose", "code_execute", "code_status", "code_cancel", "code_discovery")
CODE_MODE_MUTATING_ACTIONS = ("code_propose", "code_execute", "code_cancel")

_REQUEST_KEY = re.compile(r"[A-Za-z0-9_-]{8,160}\Z")
_ID = re.compile(r"[A-Za-z0-9_:.@/-]{1,256}\Z")


def build_code_mode(control, *, engine: str = "quickjs-wasm",
                    limits: ResourceLimits | None = None,
                    artifact: QuickJSArtifact | None = None):
    """Instantiate the dispatcher on the central control (no second authority).

    Default engine is ``quickjs-wasm`` (the only A08-satisfying engine); with
    no pinned artifact it raises explicit UNAVAILABLE via the env pins.
    ``bounded-js`` is an explicit opt-in interim engine, never the A08 answer.
    """
    """Instantiate the dispatcher on the central control (no second authority)."""
    from .dispatcher import CodeModeDispatcher
    if engine == "quickjs-wasm" and artifact is None:
        from .artifact_config import load_artifact_from_env
        artifact = load_artifact_from_env()  # explicit UNAVAILABLE when unpinned
    return CodeModeDispatcher(control, limits=limits, engine=engine, artifact=artifact)


def build_admission(*, limits: ResourceLimits | None = None):
    """Status/admission bound to env pins when present (explicit otherwise)."""
    from .artifact_config import build_admission as build
    return build(limits=limits)


_Machine_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
CODE_MACHINE_CAPABILITIES = ("code:configure", "code:restore",
                             "code:inventory", "code:discovery")


def approve_artifact(*, wasm_path: str, sbom_path: str,
                     wasm_sha256: str, sbom_sha256: str):
    """Host-approved artifact pins (operator route standing, never chat/model).

    Format-validates the pins and returns the ``QuickJSArtifact``; byte
    existence + SHA verification happen at admission/readiness and before
    every run (never trusted from this constructor alone).
    """
    return QuickJSArtifact(wasm_path=wasm_path, sbom_path=sbom_path,
                           wasm_sha256=wasm_sha256.strip().lower(),
                           sbom_sha256=sbom_sha256.strip().lower())


def build_fenced_tool_map(tool_handlers) -> dict[str, Any]:
    """Validate the host-selected tool map for fenced inner Operations.

    Keys are allowlisted names, values are HOST-SELECTED callables (never
    JS/model-provided). Empty map is valid and means ``call_tool`` is denied
    inside the sandbox. Each inner call becomes its OWN OperationRequest
    through the central gate (see ``_FencedToolBridge``) — the map itself
    creates no grants.
    """
    handlers = dict(tool_handlers or {})
    if len(handlers) > 32:
        raise ValueError("fenced tool map exceeds 32 entries")
    for name, handler in handlers.items():
        if not isinstance(name, str) or not _Machine_TOOL_NAME.fullmatch(name):
            raise ValueError("tool name outside allowlist charset: " + str(name)[:80])
        if not callable(handler):
            raise ValueError("host tool handler required for: " + name)
    return handlers


def declare_code_machine(owner: str, tool_names) -> Any:
    """Declare the Code Mode machine on the SAME central authority.

    Capabilities: ``code:configure`` (admit a proposal), ``code:restore``
    (cancel + idempotent replay from stored receipts), ``code:inventory``
    (list proposals), ``code:discovery`` (signature + admission status),
    plus ``code-tool:<name>`` per allowlisted inner tool. Authority stays
    with the Control Plane via ``CentralInteropAdapter``; this declaration
    mints no grants. For Nexo/root composition.
    """
    from sentra_runtime.contracts import Capability, Machine
    names = list(tool_names or [])
    if len(names) > 32 or any(not isinstance(n, str)
                              or not _Machine_TOOL_NAME.fullmatch(n) for n in names):
        raise ValueError("bounded allowlisted tool identity required")
    if len({n for n in names}) != len(names):
        raise ValueError("duplicate tool identity")
    machine_id = "code-mode-" + hashlib.sha256(
        owner.encode()).hexdigest()[:24]
    capabilities = tuple([Capability(cap, "Code Mode central lifecycle: " + cap)
                          for cap in CODE_MACHINE_CAPABILITIES]
                         + [Capability("code-tool:" + n, "Code Mode composed tool: " + n)
                            for n in names])
    return Machine(machine_id, "code-mode", owner, capabilities)


def compose_quickjs_dispatcher(control, *, artifact=None,
                               limits: ResourceLimits | None = None):
    """Central helper: quickjs-wasm dispatcher with approved artifact.

    ``artifact`` is a host-approved ``QuickJSArtifact`` (see
    ``approve_artifact``); omitted means env pins (explicit UNAVAILABLE when
    unconfigured). quickjs-only by construction — there is no engine
    parameter, so no subset facade can be counted as A08 here.
    """
    from .dispatcher import CodeModeDispatcher
    if artifact is None:
        from .artifact_config import load_artifact_from_env
        artifact = load_artifact_from_env()
    return CodeModeDispatcher(control, limits=limits,
                              engine="quickjs-wasm", artifact=artifact)


def machine_adapter(control, *, owner: str, run_id: str, tool_names):
    """(machine, adapter) pair for Nexo/root on the same central authority.

    Lifecycle mapping (all durable, all centrally fenced):
    configure → ``dispatcher.propose`` (+ artifact admission);
    restore → ``dispatcher.cancel`` + idempotent ``execute`` replay (stored
    receipts; never re-runs the guest blindly);
    inventory → ``dispatcher.inventory`` (read-only);
    discovery → ``dispatcher.discovery`` (read-only signature + status).
    """
    from sentra_interop.central import CentralInteropAdapter
    machine = declare_code_machine(owner, tool_names)
    return machine, CentralInteropAdapter(control=control, run_id=run_id,
                                          owner=owner, machine=machine)


def normalize_shell_envelope(body: Mapping[str, Any], *, allowed_actions) -> dict[str, Any]:
    """Validate a shell bridge body and normalize ws->project_id.

    Returns a canonical dict with ``project_id`` (never ``ws``). Raises
    ValueError on unknown action, missing request_key for mutations, or
    invalid IDs. Identity/scope still derive from the authenticated session
    and Control Plane on the Codex side; this only normalizes the envelope.
    """
    if not isinstance(body, Mapping):
        raise ValueError("shell bridge body must be JSON object")
    action = body.get("action")
    if action not in tuple(allowed_actions):
        raise ValueError("unsupported shell bridge action")
    project_id = body.get("project_id", body.get("ws"))
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise ValueError("validated project workspace identity required")
    canonical = {k: v for k, v in body.items() if k != "ws"}
    canonical["project_id"] = project_id
    if action in CODE_MODE_MUTATING_ACTIONS:
        request_key = body.get("request_key")
        if not isinstance(request_key, str) or not _REQUEST_KEY.fullmatch(request_key):
            raise ValueError("mutating shell action requires request_key")
    return canonical


def dispatch_skill_library_extra(*, library, scope: Callable[[str, str], Mapping[str, Any]],
                                 owner: str, root: str, action: str,
                                 p: Mapping[str, Any]):
    """Drop-in for the Pacto-owned skill actions in ``center_skill_library``.

    ``scope(work_item_id, agent_id)`` is the Canvas-side WorkItem/agent check
    (raises on mismatch); read-only actions bypass it, exactly like the
    existing ``list``/``revoke`` vs ``activate``/``disclose`` split. Call ONLY
    from the authenticated owner route; ``rollback``/``replace``/``upgrade``
    are operator-approved effects of that route (same standing as the
    existing ``revoke``), never model-issued grants.
    """
    params = dict(p or {})
    if action == "review":
        return library.review(owner, root, params["package_id"])
    if action == "versions":
        return library.versions(owner, root, params["name"])
    if action == "latest":
        return library.latest(owner, root, params["name"])
    if action in ("upgrade", "rollback", "replace", "deactivate"):
        scope(params["work_item_id"], params["agent_id"])
        if action == "upgrade":
            return library.upgrade_activation(owner, root, params["name"],
                                              params["new_package_id"],
                                              params["work_item_id"], params["agent_id"])
        if action == "rollback":
            return library.rollback_activation(owner, root, params["name"],
                                               params["previous_package_id"],
                                               params["work_item_id"], params["agent_id"],
                                               approved=True)
        if action == "replace":
            return library.replace_activation(owner, root, params["old_package_id"],
                                              params["new_package_id"],
                                              params["work_item_id"], params["agent_id"])
        return library.deactivate(owner, root, params["package_id"],
                                  params["work_item_id"], params["agent_id"])
    raise ValueError("unsupported skill library action")


async def dispatch_code_center(*, dispatcher, action: str, p: Mapping[str, Any],
                               owner: str, root: str,
                               tools: Mapping[str, Callable] | None = None):
    """Drop-in for ``code_*`` center/shell actions (Codex registers the route).

    ``p`` carries the already-validated envelope (see
    ``normalize_shell_envelope``) plus WorkItem binding fields. ``tools`` maps
    allowlisted names to HOST-SELECTED callables; omit/empty means
    ``call_tool`` is denied inside the sandbox. Mutations are idempotent per
    ``operation_id``; the shell layer should derive it from ``request_key``.
    """
    params = dict(p or {})
    if action in ("code_propose", "propose"):
        return dispatcher.propose(owner=owner, workspace=root,
                                  run_id=params["run_id"],
                                  work_item_id=params["work_item_id"],
                                  agent_id=params["agent_id"],
                                  source=params["source"],
                                  engine=params.get("engine"))
    if action in ("code_execute", "execute"):
        return await dispatcher.execute(
            owner=owner, proposal_id=params["proposal_id"],
            operation_id=params["operation_id"],
            idempotency_key=params["idempotency_key"],
            source=params.get("source"), tools=tools)
    if action in ("code_status", "status"):
        return dispatcher.status(owner, params["proposal_id"])
    if action in ("code_cancel", "cancel"):
        return dispatcher.cancel(owner, params["proposal_id"])
    raise ValueError("unsupported Code Mode action")


def dispatch_mcpb_extra(*, lifecycle, action: str, p: Mapping[str, Any],
                        owner: str, root: str):
    """Spec map for the Pacto-owned MCPB read/recovery actions.

    Effect actions (``uninstall``) require the owner route's approval flag;
    ``dispatch_tool`` is async and must be awaited by the caller's route.
    ``restart_ticket``/``transport_status``/``sandbox_spec``/``collision_check``
    are read-only or inert.
    """
    params = dict(p or {})
    if action == "transport_status":
        return lifecycle.transport_status(owner, root, params["server_id"])
    if action == "restart_ticket":
        return lifecycle.restart_ticket(owner, root, params["server_id"])
    if action == "sandbox_spec":
        return lifecycle.sandbox_spec(owner, root, params["package_sha256"])
    if action == "collision_check":
        return lifecycle.collision_check(params["provider_id"], params["methods"])
    if action == "uninstall":
        return lifecycle.uninstall(owner, root, params["package_sha256"],
                                   approved=params.get("approved") is True)
    raise ValueError("unsupported MCPB lifecycle action")
