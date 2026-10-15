"""Installation peer gateway behind the Canvas shell bridge.

Codex owns service.py and calls this module. Effects use that Canvas runtime's
Control Plane, owner, and the Dot's agent. A renderer payload does not carry
identity or a Grant. Reads do not listen, create an identity, or issue a Grant.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json

from sentra_canvas.shell_requests import ShellHostRequests
from sentra_canvas.store import Denied
from sentra_federation.bind import BindRefused, assert_destination, assert_private_bind
from sentra_federation.gateway import PeerGateway
from sentra_federation.identity import InstallationIdentity
from sentra_mcp.services.durable import DurableStateConflict
from sentra_remote.peer_surface import PeerGatewaySurface

NETWORK_READS = frozenset({"network_home", "network_status"})
NETWORK_MUTATIONS = frozenset({
    "network_enable", "network_disable", "network_invite", "network_revoke",
    "network_converse", "network_delegate", "network_review", "network_reconcile",
})
NETWORK_ACTIONS = NETWORK_READS | NETWORK_MUTATIONS

_FIELDS = {
    "network_home": set(),
    "network_status": {"space_id", "dot_id"},
    "network_enable": {"space_id", "dot_id"},
    "network_disable": {"space_id", "dot_id"},
    "network_invite": {"space_id", "dot_id", "address", "port", "confirmation"},
    "network_revoke": {"space_id", "dot_id", "node_id"},
    "network_converse": {"space_id", "dot_id", "node_id", "text"},
    "network_delegate": {"space_id", "dot_id", "node_id", "task"},
    "network_review": {"space_id", "dot_id", "node_id", "intent_id"},
    "network_reconcile": {"space_id", "dot_id", "node_id", "intent_id"},
}
_CAPABILITY = {
    "network_enable": "federation.gateway.enable",
    "network_disable": "federation.gateway.enable",
    "network_invite": "federation.invite",
    "network_revoke": "federation.invite",
    "network_converse": "federation.conversation",
    "network_delegate": "federation.delegate",
    "network_review": "federation.review",
    "network_reconcile": "federation.delegate",
}
_RENDERER_CONFIG = {
    "renderer", "bind", "host", "mesh_key", "private_key", "sqlite", "cert", "cert_pem",
    "grant", "grant_id", "owner", "principal", "principal_id", "principal_type", "permissions",
    "fingerprint", "identity",
}


def home_network(canvas, project_id):
    """Home caller. Reads installation files and the live listener only."""
    _project(canvas, project_id)
    return _view(canvas, project_id)


def dispatch_network(canvas, project_id, action, params, request_key=None):
    """Root callback. Mutations reserve a central effect before any network I/O."""
    if action not in NETWORK_ACTIONS or not isinstance(params, dict):
        raise ValueError("unknown network action")
    if set(params) - _FIELDS[action] or _RENDERER_CONFIG.intersection(params):
        raise Denied("renderer payload cannot carry bind, identity, or a Grant")
    _project(canvas, project_id)
    if action == "network_home":
        return home_network(canvas, project_id)
    dot = _scope(canvas, project_id, params["space_id"], params["dot_id"])
    if action == "network_status":
        value = _view(canvas, project_id)
        value["space_id"] = params["space_id"]
        value["dot_id"] = params["dot_id"]
        return value
    control, owner = _authority(canvas)
    capability = _CAPABILITY[action]
    if action == "network_reconcile":
        intent = _required(canvas, project_id).gateway.journal.get(params["intent_id"])
        if (not intent or intent.get("peer") != params["node_id"]
                or (intent.get("scope") or {}).get("project_id") != project_id):
            raise Denied("intent is outside the project and peer")
        capability = {"delegate": "federation.delegate", "chat": "federation.conversation",
                      "canvas": "federation.canvas.project"}.get(intent.get("kind"))
        if capability is None:
            raise Denied("unknown intent action")
    decision = _allow(control, owner, capability, project_id)
    journal = ShellHostRequests(control, owner)

    def apply():
        reserved = _reserve(canvas, control, owner, project_id, params, dot, action, request_key)
        try:
            journal.note_effect_possible(project_id, request_key, operation_id=reserved["operation_id"])
            if action == "network_enable":
                value = _enable(canvas, project_id, params, reserved)
            elif action == "network_disable":
                value = _disable(canvas, project_id)
            else:
                session = _required(canvas, project_id)
                if action == "network_invite":
                    value = _invite(canvas, project_id, session, params)
                elif action == "network_revoke":
                    value = _revoke(canvas, project_id, session, params)
                elif action == "network_converse":
                    value = _converse(session, project_id, params)
                elif action == "network_delegate":
                    value = _delegate(session, project_id, params)
                elif action == "network_reconcile":
                    value = _reconcile(session, params)
                else:
                    value = _review(session, params)
            _finish(control, owner, reserved, value)
            return value
        finally:
            control.durable.release_lease(
                reserved["resource_key"], owner, reserved["fencing_token"],
            )

    return journal.invoke(project_id, action, params, request_key, apply)


class _Session:
    def __init__(self, gateway, surface, space_id, dot_id):
        self.gateway, self.surface = gateway, surface
        self.space_id, self.dot_id = space_id, dot_id


def _sessions(canvas):
    sessions = getattr(canvas, "_federation_gateways", None)
    if sessions is None:
        sessions = {}
        canvas._federation_gateways = sessions
    return sessions


def _authority(canvas):
    return canvas._shell_service(), canvas._runtime().owner


def _project(canvas, project_id):
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("project_id required")
    return canvas.store.workspace(project_id)


def _scope(canvas, project_id, space_id, dot_id):
    control, owner = _authority(canvas)
    control.shell.get_space(space_id, owner, project_id=project_id)
    with closing(control.store.connect("shell")) as db:
        return control.shell._entity(db, owner, project_id, "dot", dot_id, space_id=space_id)


def _allow(control, owner, capability, project_id):
    decision = control.authorization.authorize(
        owner,
        principal_type="user",
        principal_id=owner,
        capability=capability,
        scope_type="project",
        scope_id=project_id,
        context={"actual_cost": 0.0},
        local_owner=False,
    )
    if decision.get("allowed") is not True or not decision.get("grant_id"):
        raise Denied("control plane grant missing")
    return decision


def _ident(owner, project_id, request_key):
    raw = json.dumps([owner, project_id, request_key], separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _lock_key(project_id):
    return "fedlock" + hashlib.sha256(project_id.encode()).hexdigest()[:32]


def _reserve(canvas, control, owner, project_id, params, dot, action, request_key):
    """Host WorkItem, Operation and lease. No listener or socket yet."""
    run = canvas._runtime().run(project_id)
    if run["state"] != "RUNNING":
        raise Denied("project run is not active")
    agent_id = dot["agent_id"]
    control.ensure_agent(
        run["run_id"], owner, agent_id=agent_id, role=dot.get("role") or "worker",
        metadata={"workspace_id": project_id, "space_id": params["space_id"], "dot_id": params["dot_id"]},
    )
    ident = _ident(owner, project_id, request_key)
    work_item_id = "WI-fed-" + ident[:32]
    operation_id = "op-fed-" + ident[:32]
    item = control.create_work_item(
        run["run_id"], owner,
        work_item_id=work_item_id,
        external_key="fed-" + ident,
        assignee_agent_id=agent_id,
        objective="Federated " + action,
        execution_policy={"require_quality_gate": False, "stages": []},
        metadata={
            "workspace_id": project_id,
            "space_id": params["space_id"],
            "dot_id": params["dot_id"],
            "action": action,
            "automatic_resend": False,
        },
        side_effect_scope="none",
    )
    operation = control.durable.create_operation(
        run["run_id"], owner,
        kind="federation." + action.removeprefix("network_"),
        idempotency_key="fed-" + ident,
        operation_id=operation_id,
        initial_state="QUEUED",
        cleanup_policy="manual",
    )
    if operation.get("idempotent_replay") and operation["state"] in {"SUCCEEDED", "FAILED", "UNCERTAIN"}:
        raise Denied("central effect already exists; observe it and do not resend")
    resource_key = _lock_key(project_id)
    try:
        lease = control.durable.acquire_lease(
            run["run_id"], owner, resource_key, operation_id=operation["operation_id"], ttl_s=60,
        )
    except DurableStateConflict as exc:
        raise Denied("another network effect holds the project lease") from exc
    return {
        "run_id": run["run_id"],
        "work_item_id": item["work_item_id"],
        "operation_id": operation["operation_id"],
        "resource_key": resource_key,
        "fencing_token": lease["fencing_token"],
        "assignee_agent_id": agent_id,
    }


def _finish(control, owner, reserved, value):
    control.durable.update_operation(
        reserved["operation_id"], owner, state="STARTING",
        progress={"automatic_resend": False, "effect_started": False},
    )
    control.durable.update_operation(
        reserved["operation_id"], owner, state="RUNNING",
        progress={"automatic_resend": False, "effect_started": True, "fencing_token": reserved["fencing_token"]},
    )
    control.durable.update_operation(
        reserved["operation_id"], owner, state="SUCCEEDED",
        result={
            "work_item_id": reserved["work_item_id"],
            "operation_id": reserved["operation_id"],
            "fencing_token": reserved["fencing_token"],
            "automatic_resend": False,
            "action_status": value.get("status"),
        },
        progress={"automatic_resend": False, "effect_started": True},
    )
    control.start_work_item_execution(
        reserved["work_item_id"], owner, run_id=reserved["run_id"], agent_id=reserved["assignee_agent_id"],
    )
    control.transition_work_item(reserved["work_item_id"], owner, "VALIDATING", reason="federated effect recorded")
    control.transition_work_item(
        reserved["work_item_id"], owner, "IN_REVIEW", reason="federated effect awaiting review",
    )
    value["central"] = {
        "work_item_id": reserved["work_item_id"],
        "operation_id": reserved["operation_id"],
        "fencing_token": reserved["fencing_token"],
        "assignee_agent_id": reserved["assignee_agent_id"],
        "work_item_state": "IN_REVIEW",
        "operation_state": "SUCCEEDED",
    }


def _root(canvas, project_id):
    return canvas.state_dir / "federation" / project_id


def _record_path(canvas, project_id):
    return _root(canvas, project_id) / "installation.json"


def _load_record(canvas, project_id):
    path = _record_path(canvas, project_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_record(canvas, project_id, record):
    path = _record_path(canvas, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")


def _configuration(canvas, project_id):
    settings = getattr(canvas, "network", None)
    if settings is None:
        return {"source": "installation-default", "interface_address": "", "adapter_kind": None, "private_bind": True}
    config = settings.status(project_id)["configuration"]
    address = str(config.get("interface_address") or "")
    private = False
    if address:
        try:
            assert_private_bind(address)
            private = True
        except BindRefused:
            private = False
    return {
        "source": "workspace-network",
        "adapter_kind": config.get("adapter_kind"),
        "interface_configured": bool(address),
        "private_bind": private or not address,
        "settings_enabled": config.get("enabled") is True,
    }


def _view(canvas, project_id):
    record = _load_record(canvas, project_id)
    live = _sessions(canvas).get(project_id)
    listening = False
    peers = []
    if live is not None:
        status = live.gateway.status()
        listening = status.get("listening") is True
        peers = [_peer_view(peer) for peer in status.get("peers", [])]
    elif record is not None:
        peers = list(record.get("peers") or [])
    if not listening:
        peers = [
            {**peer, "disconnected": True, "state": peer.get("state") if peer.get("state") == "revoked" else "disconnected"}
            for peer in peers
        ]
    configured = record is not None or live is not None
    document = {
        "enabled": bool(record and record.get("enabled")) or live is not None,
        "configured": configured,
        "listening": listening,
        "disconnected": not listening,
        "host_class": (live.gateway.status()["host_class"] if live is not None else (record or {}).get("host_class")),
        "configuration": _configuration(canvas, project_id),
        "peers": peers,
        "space_id": None if live is None else live.space_id,
        "dot_id": None if live is None else live.dot_id,
        "physical_proof": False,
        "vpn_is_authorization": False,
        "public_bind": False,
        "database_exposed": False,
        "image_installer": False,
        "renderer": "lumen",
        "project_id": project_id,
    }
    return _public(document)


def _peer_view(peer):
    return {
        "node_id": peer.get("node_id"),
        "state": peer.get("state"),
        "paired": peer.get("paired") is True,
        "invite": peer.get("pair_state") or peer.get("invite"),
        "disconnected": peer.get("network_reachable") is not True,
        "execution_authorized": False,
    }


def _remember(canvas, project_id, session, *, enabled):
    status = session.gateway.status()
    _save_record(canvas, project_id, {
        "enabled": enabled,
        "space_id": session.space_id,
        "dot_id": session.dot_id,
        "host_class": status.get("host_class"),
        "peers": [_peer_view(peer) for peer in status.get("peers", [])],
    })


def _bind_host(canvas, project_id):
    settings = getattr(canvas, "network", None)
    address = ""
    if settings is not None:
        address = str(settings.status(project_id)["configuration"].get("interface_address") or "")
    if not address:
        return "127.0.0.1"
    try:
        return assert_private_bind(address)
    except BindRefused as exc:
        raise Denied("configured interface is not a private bind") from exc


def _enable(canvas, project_id, params, reserved):
    sessions = _sessions(canvas)
    current = sessions.get(project_id)
    if current is not None and current.gateway.status().get("listening"):
        _remember(canvas, project_id, current, enabled=True)
        return _enabled(current, reserved, replayed=True)
    control, owner = _authority(canvas)
    host = _bind_host(canvas, project_id)
    root = _root(canvas, project_id)
    identity = InstallationIdentity.load_or_create(root / "identity")
    from sentra_federation.task_runtime import FederatedMachineExecutor
    task_executor = FederatedMachineExecutor(canvas._machine_service(), project_id=project_id,
        agent_id=reserved["assignee_agent_id"], run_id=reserved["run_id"],
        workspace=canvas.store.workspace(project_id)["path"])
    gateway = PeerGateway(
        identity=identity, control=control, owner=owner, principal_id=owner,
        principal_type="user", journal_dir=root / "journal", bound_project_id=project_id,
        task_executor=task_executor,
    )
    surface = PeerGatewaySurface(gateway, host=host, port=0)
    surface.start()
    session = _Session(gateway, surface, params["space_id"], params["dot_id"])
    sessions[project_id] = session
    _remember(canvas, project_id, session, enabled=True)
    return _enabled(session, reserved, replayed=False)


def _disable(canvas, project_id):
    session = _sessions(canvas).pop(project_id, None)
    if session is not None:
        _remember(canvas, project_id, session, enabled=False)
        session.gateway.close()
    elif _load_record(canvas, project_id) is not None:
        record = _load_record(canvas, project_id)
        record["enabled"] = False
        record["peers"] = [
            {**peer, "disconnected": True, "state": "disconnected"} for peer in record.get("peers") or []
        ]
        _save_record(canvas, project_id, record)
    return {
        "status": "committed",
        "enabled": False,
        "listening": False,
        "disconnected": True,
        "physical_proof": False,
        "public_bind": False,
        "renderer": "lumen",
        "automatic_resend": False,
    }


def _enabled(session, reserved, *, replayed):
    status = session.gateway.status()
    return {
        "status": "committed",
        "replayed": replayed,
        "enabled": True,
        "listening": status["listening"],
        "disconnected": False,
        "host_class": status["host_class"],
        "port": status["port"],
        "space_id": session.space_id,
        "dot_id": session.dot_id,
        "physical_proof": False,
        "public_bind": False,
        "vpn_is_authorization": False,
        "database_exposed": False,
        "image_installer": False,
        "renderer": "lumen",
        "automatic_resend": False,
    }


def _required(canvas, project_id):
    session = _sessions(canvas).get(project_id)
    if session is None:
        record = _load_record(canvas, project_id)
        if record and record.get("enabled"):
            raise Denied("network identity is installed but the listener is down; enable restores it")
        raise Denied("network gateway is not enabled")
    return session


def _invite(canvas, project_id, session, params):
    host, port = assert_destination(params["address"], params["port"])
    discovered = session.gateway.discover(host, port)
    seen = session.gateway.exchange_hello(host, port)
    confirmed = None
    if params.get("confirmation") is not None:
        confirmed = session.gateway.confirm(seen["node_id"], params["confirmation"])
    _remember(canvas, project_id, session, enabled=True)
    peer = _peer_view(confirmed or seen)
    peer["node_id"] = (confirmed or seen).get("node_id")
    peer["paired"] = (confirmed or seen).get("paired") is True
    return {
        "status": "committed",
        "discovered_only": discovered.get("execution_authorized") is False,
        "peer": peer,
        "confirmation_code": session.gateway.confirmation_code_for(seen["node_id"]),
        "execution_authorized": False,
        "vpn_is_authorization": False,
        "automatic_resend": False,
    }


def _revoke(canvas, project_id, session, params):
    peer = session.gateway.revoke(params["node_id"])
    _remember(canvas, project_id, session, enabled=True)
    return {
        "status": "committed",
        "peer": _peer_view(peer),
        "revoked": True,
        "execution_authorized": False,
        "automatic_resend": False,
    }


def _converse(session, project_id, params):
    receipt = session.gateway.send_chat(
        params["node_id"], params["text"],
        {"kind": "project", "project_id": project_id},
    )
    return _receipt(receipt, params)


def _delegate(session, project_id, params):
    receipt = session.gateway.delegate(
        params["node_id"],
        {"kind": "project", "project_id": project_id},
        params["task"],
    )
    return _receipt(receipt, params)


def _review(session, params):
    receipt = session.gateway.review(params["node_id"], params["intent_id"])
    return _receipt(receipt, params)


def _reconcile(session, params):
    receipt = session.gateway.reconcile(params["node_id"], params["intent_id"])
    return _receipt(receipt, params)


def _receipt(receipt, params):
    public = {
        key: value for key, value in receipt.items()
        if key not in {"result_document", "grant_id", "fingerprint"}
    }
    return {
        "status": "committed",
        "space_id": params["space_id"],
        "dot_id": params["dot_id"],
        "receipt": public,
        "result_document": receipt.get("result_document"),
        "physical_proof": False,
        "vpn_is_authorization": False,
        "automatic_resend": False,
    }


def _public(document):
    encoded = json.dumps(document)
    lowered = encoded.lower()
    if "sqlite" in lowered or "private_key" in lowered or "grant_id" in lowered or "fingerprint" in lowered:
        raise Denied("network document leaked identity, Grant, or a database")
    return document
