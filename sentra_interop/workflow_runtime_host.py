"""Host-side runtime provider machines for Temporal/LangGraph (Pulso).

This is the real factory/config counterpart to the injectable adapters in
``workflow_runtime``: instead of leaving the SDK as caller-injected
duck-typing only, :class:`RuntimeProviderHost` owns versioned provider
configuration, secret-free option pins, client factories, binding restore
and catalog on top of the **same** ``MachineHost`` control/owner (policy
and registry stay central). Nexo adds its wrapper on these exact APIs:

- ``configure`` — pin provider/server/scope/target/SDK/worker/definition,
  resolve secret refs through the host resolver, build the client through
  a registered factory (or accept a prebuilt one), bind the subordinate
  adapter. No effect beyond client construction.
- ``restore`` — rebuild client + adapter from the persisted binding.
- ``catalog`` — list configured bindings (projections only, no secrets).
- ``dispatch_request`` — build the exact central intent for one runtime
  operation (capability family ``runtime:<provider>:<operation>`` proposed
  for the central allowlist; Nexo/Codex own the registry).
- ``submit`` — execute inside the **current** central admission (raises
  without one). No new grants: admission is the central operation the
  route created for the dispatched intent.

``PulsoWorkflowExecutor`` drives an admitted ``workflow:*`` request
through a host-looked-up bridge worker (``host_handler``), so the host
root admits **and** executes ``workflow_intent`` results instead of only
building them.

Secret material is never persisted: factory options deny secret-like
keys; credentials travel only as vault ``secret_refs`` resolved per call.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from .workflow_contracts import digest, ident
from .workflow_runtime import (
    LangGraphRuntimeAdapter, RuntimeScope, RuntimeUnavailable,
    SubordinateRuntimeAdapter, TemporalRuntimeAdapter)

PROVIDERS = frozenset({"temporal", "langgraph"})

SECRET_LIKE = ("secret", "token", "password", "passwd", "credential",
               "private_key", "api_key", "apikey")


class RuntimeHostDenied(ValueError):
    pass


def _clean_options(options):
    def clean(value, depth=0):
        if depth > 12:
            raise RuntimeHostDenied("factory options nesting exceeds bound")
        if isinstance(value, dict):
            for key, nested in value.items():
                if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(marker in key.lower() for marker in SECRET_LIKE):
                    raise RuntimeHostDenied("factory options must contain only secret-free names; use vault references")
                clean(nested, depth + 1)
        elif isinstance(value, list):
            for nested in value:
                clean(nested, depth + 1)
        elif value is not None and type(value) not in {str, int, float, bool}:
            raise RuntimeHostDenied("persistable JSON factory options required")
    if not isinstance(options, dict):
        raise RuntimeHostDenied("factory options mapping required")
    clean(options)
    digest(options)
    return dict(options)


class RuntimeProviderHost:
    """Versioned Temporal/LangGraph provider configuration + execution."""

    ADAPTERS = {"temporal": TemporalRuntimeAdapter,
                "langgraph": LangGraphRuntimeAdapter}

    def __init__(self, machine_host: Any, *, database: str, workspace: str,
                 secret_resolver: Callable | None = None,
                 clock=time.time) -> None:
        control = getattr(machine_host, "control", None)
        owner = getattr(machine_host, "owner", None)
        if control is None or not isinstance(owner, str) or not owner:
            raise RuntimeHostDenied(
                "same MachineHost control+owner required (policy/registry stay central)")
        root, target = Path(workspace).resolve(), Path(database).resolve()
        if target == root or not target.is_relative_to(root):
            raise ValueError("runtime host projection outside workspace")
        from .workflow_storage import projection_path
        self.machine_host, self.control, self.owner = machine_host, control, owner
        self.workspace = str(root)
        self.database, self.clock = projection_path(database, workspace, control=control), clock
        self._resources: list[Any] = []
        self.secret_resolver = secret_resolver
        self._factories: dict[str, Callable] = {}
        self._adapters: dict[str, TemporalRuntimeAdapter | LangGraphRuntimeAdapter] = {}
        self._register_builtin_factories()
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS rt_provider_configs(
                binding_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                provider TEXT NOT NULL, server TEXT NOT NULL,
                scope_name TEXT NOT NULL, target_name TEXT NOT NULL,
                sdk_name TEXT NOT NULL, sdk_version TEXT NOT NULL,
                worker_version TEXT NOT NULL, definition_id TEXT NOT NULL,
                definition_version TEXT NOT NULL, factory TEXT NOT NULL,
                options_sha256 TEXT NOT NULL, protected_options TEXT NOT NULL,
                secret_refs TEXT NOT NULL, signal_channel TEXT,
                config_sha256 TEXT NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL)""")

    @contextmanager
    def _db(self):
        from .workflow_storage import projection_db
        with projection_db(self.database, control=self.control) as conn:
            yield conn

    def _protect(self, value: dict) -> str:
        from sentra_core.conversations import _encode
        return _encode(value)

    # -- factories -----------------------------------------------------
    def register_factory(self, name: str, constructor: Callable) -> None:
        """Plug a real SDK constructor: ``(options, secrets) -> client``."""
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            raise RuntimeHostDenied("bounded factory name required")
        if not callable(constructor):
            raise RuntimeHostDenied("factory constructor must be callable")
        self._factories[name] = constructor

    def _register_builtin_factories(self) -> None:
        self._factories["temporalio-connect"] = self._temporalio_factory
        self._factories["langgraph-local"] = self._langgraph_factory

    async def _temporalio_factory(self, options, secrets):
        from .workflow_sdk import temporal_client
        return await temporal_client(self, options, secrets)

    async def _langgraph_factory(self, options, secrets):
        from .workflow_sdk import langgraph_client
        return await langgraph_client(self, options, secrets)

    async def aconfigure(self, **kwargs):
        import inspect
        factory = kwargs.get("factory")
        if factory is None:
            return self.configure(**kwargs)
        if kwargs.get("sdk_client") is not None or kwargs.get("operator_approved") is not True:
            raise RuntimeHostDenied("approved factory configuration required")
        options = _clean_options(kwargs.get("factory_options") or {})
        scope = kwargs["scope"]
        self._verify_scope(scope)
        if factory == "temporalio-connect":
            if options.get("address") != kwargs["server"] or options.get("task_queue") != kwargs["scope_name"]:
                raise RuntimeHostDenied("Temporal server/task queue pin mismatch")
        if options.get("package_pins", {}).get(kwargs["sdk_name"]) != kwargs["sdk_version"]:
            raise RuntimeHostDenied("factory package version must equal configured SDK pin")
        if options.get("worker_version") != kwargs["worker_version"]:
            raise RuntimeHostDenied("factory worker version pin mismatch")
        refs = dict(kwargs.get("secret_refs") or {})
        self._provision_scope = scope
        client = await self._construct(factory, options, refs)
        arguments = {**kwargs, "_connected_client": client}
        return self.configure(**arguments)

    def _verify_scope(self, scope):
        if scope.owner != self.owner:
            raise RuntimeHostDenied("runtime scope owner differs")
        item = self.control.work_item_info(scope.work_item_id, self.owner)
        if item["run_id"] != scope.run_id or item.get("assignee_agent_id") != scope.principal_id:
            raise RuntimeHostDenied("runtime scope must use the existing assigned WorkItem")
        if scope.workspace_id and item.get("metadata", {}).get("workspace_id") != scope.workspace_id:
            raise RuntimeHostDenied("runtime workspace scope differs")

    async def _construct(self, factory, options, refs, resolver=None):
        import inspect
        constructor = self._factories.get(factory)
        if constructor is None:
            raise RuntimeHostDenied("runtime factory not registered")
        secrets = {}
        resolver = resolver or self.secret_resolver
        for key, ref in refs.items():
            if resolver is None:
                raise RuntimeHostDenied("vault resolver unavailable")
            value = resolver(ref)
            if inspect.isawaitable(value):
                value = await value
            if not isinstance(value, str) or not value:
                raise RuntimeHostDenied("runtime credential unavailable")
            secrets[key] = value
        client = constructor(options, secrets)
        return await client if inspect.isawaitable(client) else client

    # -- configure / restore / catalog ---------------------------------
    def configure(self, *, scope: RuntimeScope, provider: str, server: str,
                  scope_name: str, target_name: str,
                  sdk_name: str, sdk_version: str, worker_version: str,
                  compatible_versions=(), definition_id: str,
                  definition_version: str,
                  factory: str | None = None,
                  factory_options: dict | None = None,
                  secret_refs: dict | None = None,
                  sdk_client: Any = None,
                  signal_channel: str = "sentra_signal",
                  operator_approved: bool = False, _connected_client=None) -> dict[str, Any]:
        """Pin + build a provider binding (host approval required).

        Exactly one of ``factory`` (built here from secret-free options +
        vault-resolved secrets) or ``sdk_client`` (prebuilt, e.g. inside a
        test/composition harness) must be supplied.
        """
        if operator_approved is not True:
            raise PermissionError("host owner approval required to configure runtime")
        if provider not in PROVIDERS:
            raise RuntimeHostDenied("unknown runtime provider")
        if scope.owner != self.owner:
            raise RuntimeHostDenied("runtime scope belongs to another owner")
        if (factory is None) == (sdk_client is None):
            raise RuntimeHostDenied("supply exactly one of factory or sdk_client")
        options = _clean_options(factory_options or {})
        refs = dict(secret_refs or {})
        for key, ref in refs.items():
            if not isinstance(key, str) or not isinstance(ref, str) or not ref:
                raise RuntimeHostDenied("secret_refs must map names to vault references")
        adapter_cls = self.ADAPTERS[provider]
        for name, default in (("execution_timeout_seconds",3600),("idle_timeout_seconds",120)):
            value=options.get(name,default)
            if type(value) not in {int,float} or not 1<=value<=86400:
                raise RuntimeHostDenied("bounded runtime timeout required")
        if sdk_client is None:
            constructor = self._factories.get(str(factory))
            if constructor is None:
                raise RuntimeHostDenied(
                    f"unknown runtime factory {factory!r}; host must register it")
            secrets: dict[str, str] = {}
            if refs and _connected_client is None:
                if self.secret_resolver is None:
                    raise RuntimeHostDenied("no secret resolver for factory secret_refs")
                for key, ref in refs.items():
                    value = self.secret_resolver(ref)
                    if not isinstance(value, str) or not value:
                        raise RuntimeHostDenied("factory secret resolution failed")
                    secrets[key] = value
            client_or_factory = _connected_client
            if client_or_factory is None:
                import inspect
                if inspect.iscoroutinefunction(constructor):
                    raise RuntimeHostDenied("async factory requires await aconfigure on MachineHost loop")
                client_or_factory = constructor(options, secrets)
                if inspect.isawaitable(client_or_factory):
                    raise RuntimeHostDenied("await aconfigure required")
        else:
            client_or_factory = sdk_client
            if refs:
                raise RuntimeHostDenied(
                    "prebuilt clients resolve their own credentials; "
                    "secret_refs apply to factories only")
        if provider == "langgraph":
            ident(signal_channel)
            adapter: TemporalRuntimeAdapter | LangGraphRuntimeAdapter = adapter_cls(
                self.database, workspace=str(Path(self.database).parent),
                signal_channel=signal_channel, clock=self.clock, control=self.control)
        else:
            adapter = adapter_cls(self.database,
                                  workspace=str(Path(self.database).parent),
                                  clock=self.clock, control=self.control)
        self._verify_scope(scope)
        record = adapter.configure(
            owner=self.owner, scope=scope, server=server, scope_name=scope_name,
            target_name=target_name, sdk_client=client_or_factory,
            sdk_name=sdk_name, sdk_version=sdk_version,
            worker_version=worker_version,
            compatible_versions=tuple(compatible_versions),
            definition_id=definition_id, definition_version=definition_version,
            operator_approved=True)
        import json as _json
        with self._db() as db:
            existing = db.execute("SELECT * FROM rt_provider_configs WHERE binding_id=? AND owner=?",
                (record["binding_id"], self.owner)).fetchone()
            if existing and (existing["factory"] != str(factory or "prebuilt") or existing["options_sha256"] != digest(options)
                    or existing["secret_refs"] != _json.dumps(refs, sort_keys=True)):
                raise RuntimeHostDenied("runtime factory configuration immutable; explicit new binding required")
            db.execute(
                "INSERT INTO rt_provider_configs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(binding_id) DO UPDATE SET updated=excluded.updated",
                (record["binding_id"], self.owner, provider, server, scope_name,
                 target_name, sdk_name, sdk_version, worker_version,
                 definition_id, definition_version, str(factory or "prebuilt"),
                 digest(options), self._protect(options),
                 _json.dumps(refs, sort_keys=True),
                 signal_channel if provider == "langgraph" else None,
                 record["config_sha256"], self.clock(), self.clock()))
        for name, default in (("execution_timeout_seconds", 3600), ("idle_timeout_seconds", 120)):
            value = options.get(name, default)
            if type(value) not in {int, float} or not 1 <= value <= 86400:
                raise RuntimeHostDenied("bounded runtime timeout required")
            if adapter._config is None:
                raise RuntimeHostDenied("runtime configuration unavailable")
            adapter._config[name] = value
        self._adapters[record["binding_id"]] = adapter
        return {**record, "factory": str(factory or "prebuilt")}

    def _unprotect_options(self, protected: str) -> dict:
        from sentra_core.conversations import _decode
        value = _decode(protected)
        if not isinstance(value, dict):
            raise RuntimeHostDenied("stored factory options invalid")
        return value

    async def arestore(self, binding_id: str, *,
                secret_resolver: Callable | None = None) -> TemporalRuntimeAdapter | LangGraphRuntimeAdapter:
        """Rebuild client + adapter from a persisted binding (host action)."""
        cached = self._adapters.get(binding_id)
        if cached is not None:
            return cached
        import json as _json
        with self._db() as db:
            row = db.execute("SELECT * FROM rt_provider_configs WHERE binding_id=? "
                             "AND owner=?", (binding_id, self.owner)).fetchone()
        if row is None:
            raise FileNotFoundError("runtime provider binding not found")
        if row["factory"] == "prebuilt":
            raise RuntimeHostDenied("prebuilt client requires explicit host reattachment")
        options = self._unprotect_options(row["protected_options"])
        if digest(options) != row["options_sha256"]:
            raise RuntimeHostDenied("runtime options pin mismatch")
        self._provision_scope = self._scope_for_binding(binding_id)
        self._verify_scope(self._provision_scope)
        client = await self._construct(row["factory"], options,
            _json.loads(row["secret_refs"]), secret_resolver)
        adapter_cls = self.ADAPTERS[row["provider"]]
        if row["provider"] == "langgraph":
            adapter = adapter_cls(self.database,
                                  workspace=str(Path(self.database).parent),
                                  signal_channel=row["signal_channel"] or "sentra_signal",
                                  clock=self.clock, control=self.control)
        else:
            adapter = adapter_cls(self.database,
                                  workspace=str(Path(self.database).parent),
                                  clock=self.clock, control=self.control)
        scope = self._scope_for_binding(binding_id)
        self._verify_scope(scope)
        adapter.configure(
            owner=self.owner, scope=scope, server=row["server"],
            scope_name=row["scope_name"], target_name=row["target_name"],
            sdk_client=client, sdk_name=row["sdk_name"],
            sdk_version=row["sdk_version"], worker_version=row["worker_version"],
            definition_id=row["definition_id"],
            definition_version=row["definition_version"],
            compatible_versions=self._saved_compatible_versions(binding_id),
            operator_approved=True)
        for name, default in (("execution_timeout_seconds", 3600), ("idle_timeout_seconds", 120)):
            adapter._config[name] = options.get(name, default)
        self._adapters[binding_id] = adapter
        return adapter

    def _saved_compatible_versions(self,binding_id):
        with self._db() as db:
            row=db.execute("SELECT compatible_versions FROM rt_bindings WHERE binding_id=? AND owner=?",(binding_id,self.owner)).fetchone()
        return tuple(row["compatible_versions"].split(",")) if row else ()

    def restore(self, binding_id, *, secret_resolver=None):
        adapter = self._adapters.get(binding_id)
        if adapter is None:
            raise RuntimeHostDenied("await runtime_host.arestore(binding_id) on owned host loop first")
        return adapter

    def _scope_for_binding(self, binding_id: str) -> RuntimeScope:
        adapter = self._adapters.get(binding_id)
        if adapter is not None and adapter._config is not None:
            config = adapter._config
            return RuntimeScope(owner=config["owner"], run_id=config["run_id"],
                                work_item_id=config["work_item_id"],
                                principal_id=config["principal_id"])
        with self._db() as db:
            row = db.execute("SELECT * FROM rt_bindings WHERE binding_id=? AND owner=?",
                (binding_id, self.owner)).fetchone()
            saved = dict(row) if row is not None else None
        if saved is None:
            raise FileNotFoundError("runtime binding scope not found")
        return RuntimeScope(owner=saved["owner"], run_id=saved["run_id"],
                            work_item_id=saved["work_item_id"],
                            principal_id=saved["principal_id"])

    def binding_fingerprint(self, binding_id):
        with self._db() as db:
            row = db.execute("SELECT config_sha256,factory,options_sha256,secret_refs FROM rt_provider_configs WHERE binding_id=? AND owner=?",
                (binding_id, self.owner)).fetchone()
        if row is None:
            raise RuntimeHostDenied("runtime binding unavailable")
        return digest(dict(row))

    def catalog(self, owner: str | None = None) -> list[dict[str, Any]]:
        """List configured provider bindings (projections; never secrets)."""
        owner = self.owner if owner is None else owner
        if owner != self.owner:
            raise PermissionError("provider catalog belongs to another owner")
        with self._db() as db:
            rows = db.execute("SELECT binding_id,provider,server,scope_name,target_name,"
                              "sdk_name,sdk_version,worker_version,definition_id,"
                              "definition_version,factory,config_sha256,created,updated "
                              "FROM rt_provider_configs WHERE owner=? ORDER BY created",
                              (owner,)).fetchall()
        return [dict(row) for row in rows]

    async def aclose(self):
        """Close owned workers before their clients; failed handles stay tracked."""
        import inspect
        failures=[]
        for resource in list(reversed(self._resources)):
            try:
                await resource.__aexit__(None,None,None)
                self._resources.remove(resource)
            except Exception as exc:
                failures.append(type(exc).__name__)
        if self._resources:
            return {"closed":False,"failures":failures,"retry_cleanup_only":True}
        for binding,adapter in list(self._adapters.items()):
            client=getattr(adapter,"_client",None)
            try:
                method=getattr(client,"aclose",None) or getattr(client,"close",None)
                if callable(method):
                    result=method()
                    if inspect.isawaitable(result):
                        await result
                self._adapters.pop(binding,None)
            except Exception as exc:
                failures.append(type(exc).__name__)
        return {"closed":not failures,"failures":failures,"effects_replayed":False}

    # -- dispatch + submit (Nexo wrapper surface) ----------------------
    def dispatch_request(self, binding_id: str, *, operation: str,
                         workflow_id: str, occurrence: str,
                         arguments: dict | None = None) -> dict[str, Any]:
        """Build the exact central intent for one runtime operation.

        Capability family ``runtime:<provider>:<operation>`` is proposed
        for the central allowlist (registry owned by Nexo/Codex). Performs
        no effect; the route admits the returned intent.
        """
        adapter = self._adapters.get(binding_id)
        if adapter is None:
            adapter = self.restore(binding_id)
        config = adapter._config
        if config is None:
            raise RuntimeHostDenied("runtime binding has no pinned configuration")
        provider = config["provider"]
        allowed = {"start", "advance", "signal", "interrupt", "resume",
                   "cancel", "observe", "reconcile", "fork"}
        if operation not in allowed:
            raise RuntimeHostDenied("unknown runtime operation")
        if provider == "temporal" and operation == "fork":
            raise RuntimeHostDenied("fork is a LangGraph-only operation")
        if operation == "configure":
            raise RuntimeHostDenied("configure is host-provisioned, not dispatched")
        ident(workflow_id)
        if not isinstance(occurrence, str) or not occurrence:
            raise RuntimeHostDenied("occurrence required")
        args = {"workflow_id": workflow_id, "occurrence": occurrence}
        if arguments is not None:
            if not isinstance(arguments,dict) or set(arguments)&set(args):
                raise RuntimeHostDenied("runtime public argument mapping required")
            args.update(arguments)
        return {"capability_id": f"runtime:{provider}:{operation}",
                "arguments": args,
                "binding_id": binding_id,
                "admit_via": "central operation journal",
                "effects_started": False}

    async def submit(self, binding_id: str, *, operation: str,
                     scope: RuntimeScope, workflow_id: str, occurrence: str,
                     payload: dict | None = None,
                     signal_name: str | None = None,
                     values: dict | None = None,
                     reason: str | None = None,
                     new_occurrence: str | None = None,
                     checkpoint_id: str | None = None) -> dict[str, Any]:
        """Execute one runtime operation inside the current admission.

        Requires a current CentralEffectContext matching the scope (raises
        otherwise). Uses no new grants: admission is the central operation
        the route created for the dispatched intent.
        """
        adapter = self._adapters.get(binding_id)
        if adapter is None:
            adapter = await self.arestore(binding_id)
        context = adapter._admission(scope)
        request = context.request
        if request.capability_id != "runtime:" + adapter.PROVIDER + ":" + operation or request.arguments.get("binding_id") != binding_id or request.arguments.get("workflow_id") != workflow_id or request.arguments.get("occurrence") != occurrence:
            raise RuntimeHostDenied("runtime dispatch mismatches the admitted intent")
        from sentra_runtime.provider_content import text_digest
        checked = {"start":("inputs_sha256",payload),"signal":("payload_sha256",payload),
            "resume":("values_sha256",values),"interrupt":("reason_sha256",reason)}
        if operation in checked:
            key,value=checked[operation]
            if text_digest(value)!=request.arguments.get(key):
                raise RuntimeHostDenied("runtime payload differs from immutable admission")
        if operation=="advance" and values is not None and text_digest(values)!=request.arguments.get("resume_sha256"):
            raise RuntimeHostDenied("runtime resume payload differs")
        if operation=="fork" and (new_occurrence,checkpoint_id)!=(request.arguments.get("new_occurrence"),request.arguments.get("checkpoint_id")):
            raise RuntimeHostDenied("runtime fork selectors differ")
        if operation == "start":
            if not isinstance(payload, dict):
                raise RuntimeHostDenied("start requires a payload mapping")
            return await adapter.start(scope, workflow_id=workflow_id,
                                       occurrence=occurrence, inputs=payload)
        if operation == "advance":
            if values is not None:
                if not isinstance(adapter, LangGraphRuntimeAdapter):
                    raise RuntimeHostDenied(
                        "advance resume is a LangGraph-only operation")
                # submit is reachable only inside an admitted central
                # operation, which embodies host approval for the resume.
                return await adapter.advance(scope, workflow_id=workflow_id,
                                             occurrence=occurrence,
                                             resume=values)
            return await adapter.advance(scope, workflow_id=workflow_id,
                                         occurrence=occurrence)
        if operation == "signal":
            if not isinstance(payload, dict):
                raise RuntimeHostDenied("signal requires a payload mapping")
            signal_args = dict(payload)
            name = signal_name or request.arguments.get("name")
            if name!=request.arguments.get("name"):
                raise RuntimeHostDenied("signal name differs from admission")
            if isinstance(adapter, LangGraphRuntimeAdapter):
                return await adapter.signal(scope, workflow_id=workflow_id,
                    occurrence=occurrence, payload={"name": name, "payload": signal_args})
            return await adapter.signal(scope, workflow_id=workflow_id,
                occurrence=occurrence, name=name, payload=signal_args)
        if operation == "interrupt":
            if not isinstance(reason, str) or not reason:
                raise RuntimeHostDenied("interrupt requires a reason")
            return await adapter.interrupt(scope, workflow_id=workflow_id,
                                           occurrence=occurrence, reason=reason)
        if operation == "resume":
            if not isinstance(values, dict):
                raise RuntimeHostDenied("resume requires a values mapping")
            if isinstance(adapter, LangGraphRuntimeAdapter):
                # submit is reachable only inside an admitted central
                # operation, which embodies host approval for the resume.
                return await adapter.resume(scope, workflow_id=workflow_id,
                                            occurrence=occurrence, values=values,
                                            operator_approved=True)
            return await adapter.resume(scope, workflow_id=workflow_id,
                                        occurrence=occurrence, payload=values)
        if operation == "cancel":
            return await adapter.cancel(scope, workflow_id=workflow_id,
                                        occurrence=occurrence)
        if operation == "observe":
            return await adapter.observe(scope, workflow_id=workflow_id,
                                         occurrence=occurrence)
        if operation == "reconcile":
            return await adapter.reconcile(scope, workflow_id=workflow_id,
                                           occurrence=occurrence)
        if operation == "fork":
            if not isinstance(adapter, LangGraphRuntimeAdapter):
                raise RuntimeHostDenied("fork is a LangGraph-only operation")
            if not isinstance(new_occurrence, str) or not new_occurrence:
                raise RuntimeHostDenied("fork requires a new occurrence")
            return await adapter.fork(scope, workflow_id=workflow_id,
                                      occurrence=occurrence,
                                      new_occurrence=new_occurrence,
                                      checkpoint_id=checkpoint_id)
        raise RuntimeHostDenied("unknown runtime operation")


class PulsoWorkflowExecutor:
    """Admit-and-execute driver for ``workflow_intent`` shell results.

    The host root admits the built intent as a distinct central operation,
    then calls :meth:`execute` with the admitted ``request``. The executor
    validates intent shape, resolves the bridge worker through the
    host-injected ``bridge_lookup`` and drives ``host_handler``. Uses no
    new grants: authority is the admitted request itself.

    Final host resolver signature (for Nexo/Codex composition)::

        workflow_resolver(action, ctx, params) -> dict
            action "observe" | "output":
                params {workflow_id, namespace?, step_id?, checkpoint_id?}
                -> read projection dict (no admission needed)
            action "execute":
                params {request, intent} with request the admitted
                OperationRequest and intent a workflow_intent value
                -> effect result dict
    """

    WORKFLOW_CAPABILITIES = frozenset({
        "workflow:create", "workflow:advance", "workflow:resume",
        "workflow:signal", "workflow:cancel", "workflow:observe",
        "workflow:output", "workflow:memory",
    })

    def __init__(self, *, bridge_lookup: Callable | None = None) -> None:
        self.bridge_lookup = bridge_lookup

    async def execute(self, *, request: Any, intent: dict) -> dict[str, Any]:
        """Drive one admitted workflow intent through its bridge worker."""
        if self.bridge_lookup is None:
            raise RuntimeHostDenied("workflow bridge lookup not composed")
        if not isinstance(intent, dict):
            raise RuntimeHostDenied("workflow intent mapping required")
        capability = intent.get("capability_id")
        arguments = intent.get("arguments")
        if capability not in self.WORKFLOW_CAPABILITIES:
            raise RuntimeHostDenied("unknown workflow capability")
        if not isinstance(arguments, dict):
            raise RuntimeHostDenied("workflow intent arguments required")
        if getattr(request, "capability_id", None) != capability:
            raise RuntimeHostDenied("admitted request mismatches workflow intent")
        if dict(getattr(request, "arguments", {}) or {}) != dict(arguments):
            raise RuntimeHostDenied("admitted arguments mismatch workflow intent")
        workflow_id = arguments.get("workflow_id", "")
        worker = self.bridge_lookup(
            workflow_id, arguments.get("namespace", ""))
        handler = getattr(worker, "host_handler", None)
        if not callable(handler):
            raise RuntimeHostDenied("bridge worker has no host handler")
        outcome = handler(request)
        import inspect as _inspect
        if _inspect.isawaitable(outcome):
            outcome = await outcome
        if isinstance(outcome, dict):
            if outcome.get("status") == "UNCERTAIN":
                return {"ok": False, "value": outcome}
            return {"ok": True, "value": outcome}
        state = getattr(outcome, "state", None)
        operation_id = getattr(outcome, "operation_id", None)
        return {"ok": state == "SUCCEEDED", "value": {"state": state,
            "operation_id": operation_id, "evidence": dict(getattr(outcome, "evidence", {}) or {}),
            "error": getattr(outcome, "error", None)}}
