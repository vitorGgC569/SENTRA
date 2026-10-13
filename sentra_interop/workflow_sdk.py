"""Real SDK provisioning from immutable, owner-selected source manifests."""
import hashlib
import importlib.metadata
import importlib.util
import inspect
import uuid
from pathlib import Path

from .workflow_runtime import RuntimeUnavailable, RuntimeScopeConflict


def package_pin(options, name):
    expected = options.get("package_pins", {}).get(name)
    if not isinstance(expected, str) or not expected:
        raise RuntimeScopeConflict("exact installed package pin required: " + name)
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        raise RuntimeUnavailable("SDK unavailable: " + name)
    if actual != expected:
        raise RuntimeScopeConflict("SDK package pin changed: " + name)
    return actual


def source_module(host, options):
    manifest = options.get("definition_source") or {}
    path = (Path(host.workspace) / str(manifest.get("path", ""))).resolve(strict=True)
    if not path.is_file() or not path.is_relative_to(Path(host.workspace)):
        raise RuntimeScopeConflict("definition source outside provisioned workspace")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest.get("sha256"):
        raise RuntimeScopeConflict("definition source digest changed")
    for dependency in manifest.get("dependencies", []):
        target=(Path(host.workspace)/dependency["path"]).resolve(strict=True)
        if not target.is_file() or not target.is_relative_to(Path(host.workspace)) or hashlib.sha256(target.read_bytes()).hexdigest()!=dependency["sha256"]:
            raise RuntimeScopeConflict("definition dependency source pin changed")
    name = "sentra_owned_workflow_" + manifest["sha256"]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


async def dispatch_subordinate(host, bindings, key, arguments, effect_key, scope):
    """Only host-pinned child assignments can perform graph/worker effects."""
    binding = bindings.get(key)
    if not isinstance(binding, dict) or set(binding) != {"workspace_id", "machine_id", "work_item_id", "capability_id"}:
        raise RuntimeScopeConflict("subordinate activity assignment unavailable")
    if not isinstance(arguments, dict) or not isinstance(effect_key, str) or not 1 <= len(effect_key) <= 256:
        raise RuntimeScopeConflict("bounded activity intent required")
    item = host.control.work_item_info(binding["work_item_id"], host.owner)
    if item["run_id"] != scope.run_id:
        raise RuntimeScopeConflict("subordinate activity outside configured parent Run")
    identity = "pulso-sdk-" + uuid.uuid5(uuid.NAMESPACE_URL,
        host.owner + ":" + scope.run_id + ":" + scope.work_item_id + ":" + key + ":" + effect_key).hex
    result = await host.machine_host._dispatch(binding["workspace_id"], binding["work_item_id"],
        binding["machine_id"], binding["capability_id"], identity, arguments, identity)
    if result["state"] != "SUCCEEDED":
        raise RuntimeScopeConflict("central activity receipt " + result["state"] + "; no effect replay")
    return result


async def temporal_client(host, options, secrets):
    scope = host._provision_scope
    version = package_pin(options, "temporalio")
    from temporalio.client import Client
    from temporalio.service import TLSConfig
    address, namespace = options.get("address"), options.get("namespace")
    if not address or not namespace:
        raise RuntimeScopeConflict("Temporal address and namespace required")
    if options.get("tls") is not True:
        raise RuntimeScopeConflict("Temporal authenticated TLS required")
    tls = TLSConfig(server_root_ca_cert=secrets.get("server_ca", "").encode() or None,
        client_cert=secrets.get("client_cert", "").encode() or None,
        client_private_key=secrets.get("client_key", "").encode() or None,
        domain=options.get("tls_domain"))
    client = await Client.connect(address, namespace=namespace, tls=tls,
                                  api_key=secrets.get("api_key"))
    client.sdk_version = version
    if options.get("provision_worker"):
        from temporalio.worker import Worker
        module = source_module(host, options)
        provision = getattr(module, options.get("worker_factory", "build_worker"), None)
        if not callable(provision):
            raise RuntimeUnavailable("pinned worker definition factory unavailable")
        # The reviewed factory receives existing authority, not a new scheduler.
        values = provision(machine_host=host.machine_host, control=host.control)
        if inspect.isawaitable(values):
            values = await values
        if not isinstance(values, dict) or not values.get("workflows"):
            raise RuntimeUnavailable("pinned Temporal workflow registrations required")
        if values.get("activities"):
            raise RuntimeScopeConflict("effect activities must use the registered sentra_dispatch gateway")
        bindings = values.get("activity_bindings", {})
        from temporalio import activity

        @activity.defn(name="sentra_dispatch")
        async def sentra_dispatch(intent):
            if not isinstance(intent, dict) or set(intent) != {"binding_key", "arguments"}:
                raise RuntimeScopeConflict("Temporal activity accepts only a host binding and arguments")
            info = activity.info()
            with host._db() as db:
                registered = db.execute("SELECT 1 FROM rt_external_ids e JOIN rt_bindings b ON b.binding_id=e.binding_id "
                    "WHERE e.external_id=? AND b.owner=? AND b.run_id=? AND b.work_item_id=?",
                    (info.workflow_id, host.owner, scope.run_id, scope.work_item_id)).fetchone()
            if registered is None:
                raise RuntimeScopeConflict("Temporal activity has no existing scoped parent occurrence")
            return await dispatch_subordinate(host, bindings, intent["binding_key"], intent["arguments"],
                                               info.workflow_id + ":" + info.activity_id, scope)
        worker = Worker(client, task_queue=options["task_queue"],
            workflows=values["workflows"], activities=[sentra_dispatch],
            build_id=options["worker_version"])
        await worker.__aenter__()
        host._resources.append(worker)
    return client


async def langgraph_client(host, options, secrets):
    scope = host._provision_scope
    version = package_pin(options, "langgraph")
    package_pin(options, "langgraph-checkpoint")
    from .workflow_sdk_store import configured_checkpointer
    saver = configured_checkpointer(host.control, host.owner)
    module = source_module(host, options)
    builder = getattr(module, options.get("graph_factory", "build_graph"), None)
    if not callable(builder):
        raise RuntimeUnavailable("pinned LangGraph definition factory unavailable")
    bindings = options.get("activity_bindings", {})

    async def dispatch(binding_key, arguments, effect_key):
        from sentra_runtime.effect_boundary import current_effect_context
        context = current_effect_context.get()
        if context is None or context.receipt.owner != host.owner:
            raise RuntimeScopeConflict("graph effect outside admitted runtime operation")
        context.checkpoint()
        request = context.request
        key = request.arguments["workflow_id"] + ":" + request.arguments["occurrence"] + ":" + effect_key
        return await dispatch_subordinate(host, bindings, binding_key, arguments, key, scope)

    graph = builder(checkpointer=saver, dispatch=dispatch, machine_host=host.machine_host,
                    control=host.control)
    if inspect.isawaitable(graph):
        graph = await graph
    if getattr(graph, "checkpointer", None) is not saver:
        raise RuntimeScopeConflict("graph must use configured authority checkpointer")
    for attr in ("ainvoke", "aget_state", "aupdate_state"):
        if not callable(getattr(graph, attr, None)):
            raise RuntimeUnavailable("compiled graph API unavailable")
    graph.sdk_version = version
    return graph
