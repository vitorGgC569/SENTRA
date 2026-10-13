"""Server-only Selo host composition with real clients and configured state.

The caller is the authenticated host, never the renderer. Physical dispatch
borrows a previously admitted CentralEffectContext; this facade creates no
Run, WorkItem, Operation, Grant, lease or second budget authority.
"""
import asyncio
import contextvars
import base64
from dataclasses import asdict, is_dataclass
import inspect
from pathlib import Path
import re
import time

from sentra_quality.protected_state import ProtectedState, StateConflict, canonical, digest
from sentra_quality.provider_clients import ScopedJSONHTTP, LangfuseClient, ProviderUnavailable, send_otlp
from sentra_quality.audit_state import ProtectedAuditDeliveryStore
from sentra_quality.authority_guard import CentralReferences
from sentra_quality.learning_runtime import ProtectedLearningStore


PROVIDERS = frozenset({"opa", "openfga", "keycloak", "spire", "tessera", "immudb",
                       "langfuse", "otlp", "grype", "learning", "memory"})
_COMMON = {"enabled", "credential_ref", "timeout_s", "allow_loopback"}
_FIELDS = {
    "opa": {"endpoint", "bundle_name", "active_revision", "bundle_root", "validator"},
    "openfga": {"endpoint", "store_id", "authorization_model_id", "subject_type"},
    "keycloak": {"oidc", "pinned_jwks"}, "spire": {"workload"},
    "tessera": {"configuration", "executable", "executable_sha256"},
    "immudb": {"configuration", "executable", "executable_sha256"},
    "langfuse": {"endpoint", "api_profile", "export_content"},
    "otlp": {"endpoint", "path", "batch_size", "max_pending", "retention_seconds",
             "max_attempts", "batch_delay_seconds"},
    "grype": {"scan", "sbom", "expected_sbom_sha256", "third_party_root", "trusted_pins", "fail_at"},
    "learning": set(), "memory": set(),
}
_ACTIONS = {
    "opa": {"observe_revision", "bundle_stage", "bundle_activate", "bundle_resource", "bundle_status"},
    "openfga": {"discover", "changes", "assertions"},
    "keycloak": {"discover", "login_begin", "login_complete", "authenticate", "refresh", "logout",
                 "revoke", "session_status", "backchannel_logout", "retry_invalidations", "exchange"},
    "spire": {"connect", "authenticate", "jwt", "bundles", "close"},
    "tessera": {"connect", "initialize_trust", "enqueue_operation", "publish", "observe", "verify", "remote_status", "close"},
    "immudb": {"connect", "initialize_trust", "enqueue_operation", "publish", "observe", "verify", "export_transaction", "remote_status", "close"},
    "langfuse": (set(LangfuseClient.ACTIONS) - {"traces", "run_item"}) | {"eval_compare", "eval_run", "eval_item", "eval_score", "telemetry_flush"},
    "otlp": {"telemetry_flush", "prune"},
    "grype": {"scan", "release_gate", "diff", "report"},
    "learning": {"propose", "get", "list", "review", "withdraw", "skill_candidate", "skill_review_bundle"},
    "memory": {"put", "get", "delete", "list", "cost_summary"},
}
for _provider_actions in _ACTIONS.values():
    _provider_actions.update({"reconcile", "cancel", "close"})
for _artifact_provider in ("tessera", "immudb", "grype", "opa"):
    _ACTIONS[_artifact_provider].add("proof_read")
_FORBIDDEN = frozenset({"owner", "tenant_id", "principal", "principal_id", "principal_type",
                        "grant", "Grant", "local_owner", "resource_id", "reviewer", "session_id",
                        "browser_binding", "credentials", "credential_ref", "configuration"})


def build_client(*, host, control, owner, tenant_id, workspace_id, workspace_root, vault):
    return SeloHostFacade(host=host, control=control, owner=owner,
                          tenant_id=tenant_id, workspace_id=workspace_id, workspace_root=workspace_root, vault=vault)


class SeloHostFacade:
    def __init__(self, *, host, control, owner, tenant_id, workspace_id, workspace_root, vault):
        if not callable(vault) or control.store is not control.durable.store:
            raise ValueError("trusted vault and shared configured Control Plane required")
        if not isinstance(tenant_id, str) or not 1 <= len(tenant_id) <= 256 or "\0" in tenant_id:
            raise ValueError("trusted tenant identity required")
        if control.store.backend == "postgres" and control.store.tenant_id != tenant_id:
            raise PermissionError("Selo tenant authority mismatch")
        self.host, self.control, self.owner = host, control, owner
        self.tenant_id, self.workspace_id, self.vault = tenant_id, workspace_id, vault
        self.state = ProtectedState(store=control.store, owner=owner, workspace_id=workspace_id,
                                    namespace="selo.host")
        self.references = CentralReferences(control=control, owner=owner, workspace_id=workspace_id,
                                            workspace_root=workspace_root)
        self.workspace_root = self.references.workspace_root
        self.audit = ProtectedAuditDeliveryStore(self.state)
        self.learning = ProtectedLearningStore(self.state, self.references)
        from sentra_quality.effect_coverage import EffectCoverage
        self.coverage = EffectCoverage(self.state, self.references)
        self.clients, self._active = {}, {}
        self._credential_fingerprints = {}
        self._dispatch_configuration = contextvars.ContextVar("selo_dispatch_configuration", default=None)
        self._closed = False

    def configuration(self, provider):
        self._provider(provider)
        row = self.state.get("configuration:" + provider)
        return {"provider": provider, "revision": row["revision"] if row else None,
                "configuration": row["value"] if row else None, "grant_created": False}

    def configure(self, provider, configuration, *, expected_revision):
        """Trusted operator API; configuration is inert, secrets are vault refs."""
        self._provider(provider)
        if self._closed or provider in self.clients or any(p == provider for p, _ in self._active.values()):
            raise StateConflict("close provider before changing its configuration")
        value = self._validate_configuration(provider, configuration)
        revision = self.state.put("configuration:" + provider, value, expected_revision=expected_revision)
        return {"provider": provider, "revision": revision, "configured": True,
                "started": False, "grant_created": False}

    @staticmethod
    def _provider(provider):
        if provider not in PROVIDERS:
            raise ValueError("unknown Selo provider")

    def _validate_configuration(self, provider, configuration):
        if not isinstance(configuration, dict) or set(configuration) - (_COMMON | _FIELDS[provider]):
            raise ValueError("unknown provider configuration fields")
        value = __import__("json").loads(canonical(configuration))
        if type(value.get("enabled")) is not bool:
            raise ValueError("explicit provider enabled state required")
        def secrets(obj):
            if isinstance(obj, dict):
                for key, item in obj.items():
                    if (re.search(r"password|private_key|secret|bearer|token|dsn", key, re.I)
                            and key not in {"signing_key_file", "signing_key_sha256"}):
                        raise ValueError("secrets must be supplied through credential_ref")
                    secrets(item)
            elif isinstance(obj, list):
                for item in obj:
                    secrets(item)
        secrets(value)
        ref = value.get("credential_ref")
        if ref is not None and (not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,256}", ref)):
            raise ValueError("invalid vault credential reference")
        if not value["enabled"]:
            return value
        if provider in {"opa", "openfga", "langfuse", "keycloak", "tessera", "immudb"} and not ref:
            raise ValueError("explicit vault reference required")
        if provider in {"opa", "openfga", "langfuse", "otlp"}:
            ScopedJSONHTTP(base=value["endpoint"], allow_loopback=value.get("allow_loopback", False),
                           timeout_s=value.get("timeout_s", 5), checkpoint=lambda: None)
        if provider == "opa":
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value.get("bundle_name", "sentra")) or not value.get("active_revision"):
                raise ValueError("pinned OPA bundle/revision required")
        elif provider == "openfga":
            from sentra_runtime.openfga_rebac import OpenFGACheckClient
            OpenFGACheckClient(endpoint=value["endpoint"], bearer="unused", store_id=value["store_id"],
                authorization_model_id=value["authorization_model_id"], subject_type=value.get("subject_type", "agent"),
                http=object())
        elif provider == "keycloak":
            from sentra_runtime.keycloak_provider import KeycloakOIDCConfig
            from sentra_runtime.keycloak_identity import PinnedKeycloakJWTVerifier
            config = KeycloakOIDCConfig(**value["oidc"])
            PinnedKeycloakJWTVerifier(issuer=config.issuer, audience=config.audience, pinned_jwks=value["pinned_jwks"])
        elif provider == "spire":
            from sentra_runtime.spire_identity import SpireWorkloadConfig
            SpireWorkloadConfig(**value["workload"])
        elif provider in {"tessera", "immudb"}:
            from sentra_runtime.tessera_provider import TesseraConfig
            from sentra_runtime.immudb_provider import ImmudbAuditConfig
            (TesseraConfig if provider == "tessera" else ImmudbAuditConfig)(
                owner=self.owner, workspace_id=self.workspace_id, **value["configuration"])
            if not Path(value["executable"]).is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", value["executable_sha256"]):
                raise ValueError("pinned absolute audit SDK executable required")
        elif provider == "langfuse":
            LangfuseClient(None, api_profile=value.get("api_profile", "langfuse-v3-dataset-runs"))
            if type(value.get("export_content", False)) is not bool:
                raise ValueError("explicit dataset/prompt content export choice required")
        elif provider == "otlp":
            from sentra_quality.telemetry_state import validate_queue_configuration
            validate_queue_configuration(value)
            if value.get("path", "/v1/traces") != "/v1/traces":
                raise ValueError("OTLP trace route must be pinned")
        elif provider == "grype":
            from sentra_quality.grype_scan import GrypeScanConfig
            GrypeScanConfig(**value["scan"])
            if not all(Path(value[key]).is_absolute() for key in ("sbom", "third_party_root", "trusted_pins")):
                raise ValueError("trusted absolute release input paths required")
            if not re.fullmatch(r"[0-9a-f]{64}", value["expected_sbom_sha256"]):
                raise ValueError("pinned SBOM required")
        return value

    def _config(self, provider):
        row = self.state.get("configuration:" + provider)
        if row is None or row["value"].get("enabled") is not True:
            raise ProviderUnavailable("PROVIDER_NOT_CONFIGURED_OR_DISABLED")
        return row

    def _credential(self, config):
        if not config.get("credential_ref"):
            return None
        value = self.vault(config["credential_ref"])
        if inspect.isawaitable(value):
            if inspect.iscoroutine(value): value.close()
            raise ValueError("host-loop vault resolver must be synchronous")
        if value is None:
            raise ProviderUnavailable("VAULT_CREDENTIAL_UNAVAILABLE")
        if isinstance(value, dict) and "_expires_at" in value:
            deadline = value["_expires_at"]
            if type(deadline) not in {int, float} or not __import__("math").isfinite(deadline) or deadline <= time.time():
                raise ProviderUnavailable("VAULT_CREDENTIAL_EXPIRED")
        return value

    def _context(self, *, provider=None, action=None, arguments=None, request_key=None):
        from sentra_runtime.effect_boundary import CentralEffectContext, current_effect_context
        context = current_effect_context.get()
        if (not isinstance(context, CentralEffectContext) or context.receipt.owner != self.owner
                or context.authority.durable is not self.control.durable):
            raise PermissionError("existing Selo central physical context required")
        run = self.control.durable.run_status(context.receipt.run_id, self.owner, include_details=False)
        work = self.control.governance.work_item_info(context.request.work_item_id, self.owner)
        if (not self.references.root_matches(run["workspace"])
                or work["run_id"] != context.receipt.run_id or not self.references.work_matches(work)):
            raise PermissionError("Selo context outside workspace")
        if provider is not None:
            expected = {"provider": provider, "action": action, "arguments": arguments, "request_key": request_key}
            if (dict(context.request.arguments) != expected or
                    context.request.capability_id != "selo." + provider + "." + action):
                raise PermissionError("Selo intent/capability differs from admitted envelope")
        context.checkpoint()
        return context

    def _checkpoint(self):
        self._context()
        binding = self._dispatch_configuration.get()
        if binding is not None:
            provider, revision = binding
            if self._config(provider)["revision"] != revision:
                raise StateConflict("provider configuration changed during physical dispatch")
            config = self._config(provider)["value"]
            if config.get("credential_ref"):
                fingerprint = digest(self._credential(config))
                expected = self._credential_fingerprints.get(provider)
                if expected is not None and fingerprint != expected:
                    raise ProviderUnavailable("VAULT_CHANGED_EXPLICIT_REAUTHENTICATION_REQUIRED")

    def _identity_binding(self, context):
        lookup = getattr(self.host, "selo_identity_binding", None)
        if not callable(lookup):
            raise ProviderUnavailable("TRUSTED_HOST_IDENTITY_BINDING_UNAVAILABLE")
        value = lookup(owner=self.owner, workspace_id=self.workspace_id,
                       principal_id=context.request.principal_id)
        if (not isinstance(value, dict) or value.get("principal_id") != context.request.principal_id
                or value.get("kind") not in {"user", "agent", "service", "device"}):
            raise PermissionError("host identity binding mismatch")
        return value

    def _source_permission(self, snapshot, context):
        """Reading evidence of another WorkItem requires its real scoped Grant."""
        source = snapshot["origin"]["work_item_id"]
        if source == context.request.work_item_id:
            return
        binding = self._identity_binding(context)
        decision = self.control.authorization.authorize(self.owner,
            principal_type=binding["kind"], principal_id=context.request.principal_id,
            capability=context.request.capability_id, scope_type="work_item", scope_id=source,
            context={"actual_cost": 0.0}, local_owner=False)
        if decision.get("allowed") is not True:
            raise PermissionError("source evidence WorkItem grant unavailable")

    def _client(self, provider, *, checkpoint=None):
        row = self._config(provider)
        config = row["value"]
        credential = self._credential(config) if config.get("credential_ref") else None
        fingerprint = digest(credential) if credential is not None else None
        cached = self.clients.get(provider)
        if cached and self._credential_fingerprints.get(provider) != fingerprint:
            raise ProviderUnavailable("VAULT_CHANGED_EXPLICIT_REAUTHENTICATION_REQUIRED")
        if cached and cached[0] == row["revision"] and checkpoint is None:
            return cached[1]
        if cached and cached[0] != row["revision"]:
            raise StateConflict("provider changed; explicit close/recovery required")
        check = checkpoint or self._checkpoint
        if provider in {"opa", "openfga", "keycloak", "langfuse", "otlp"}:
            http = ScopedJSONHTTP(base=config.get("endpoint") or config["oidc"]["issuer"],
                credential=credential, auth="basic" if provider == "langfuse" else "bearer",
                allow_loopback=config.get("allow_loopback", False),
                timeout_s=config.get("timeout_s", 5), checkpoint=check)
            if provider == "langfuse":
                client = LangfuseClient(http, api_profile=config.get("api_profile", "langfuse-v3-dataset-runs"))
            elif provider == "otlp":
                client = http
            elif provider == "openfga":
                from sentra_runtime.openfga_rebac import OpenFGACheckClient
                client = OpenFGACheckClient(endpoint=config["endpoint"], bearer="unused",
                    store_id=config["store_id"], authorization_model_id=config["authorization_model_id"],
                    subject_type=config.get("subject_type", "agent"), http=http)
            elif provider == "opa":
                from sentra_runtime.opa_pdp import OPAClient
                def revision():
                    response = http.get("/v1/data/system/bundles/" + config.get("bundle_name", "sentra") + "/manifest/revision")
                    if response.get("result") != config["active_revision"]:
                        raise ProviderUnavailable("OPA_REVISION_NOT_ACTIVE")
                    return response["result"]
                client = OPAClient(endpoint=config["endpoint"], bearer="unused", http=http,
                    decision_path="/v1/data/sentra/decision", active_revision=revision)
            else:
                from sentra_runtime.keycloak_provider import KeycloakOIDCProvider, KeycloakOIDCConfig
                from sentra_runtime.keycloak_identity import PinnedKeycloakJWTVerifier
                oidc = KeycloakOIDCConfig(**config["oidc"])
                notify = getattr(self.host, "selo_identity_invalidated", None)
                if not callable(notify):
                    raise ProviderUnavailable("HOST_REVOCATION_CONSUMER_UNAVAILABLE")
                # Keycloak service client_secret is not an HTTP bearer.
                http.authorization = None
                client = KeycloakOIDCProvider(config=oidc, enabled=True,
                    verifier=PinnedKeycloakJWTVerifier(issuer=oidc.issuer, audience=oidc.audience, pinned_jwks=config["pinned_jwks"]),
                    store=self.state.scoped("selo.identity.keycloak"), http=http,
                    client_secret_provider=lambda: self._credential(config), on_invalidate=notify)
        elif provider == "spire":
            from sentra_runtime.spire_identity import SpireWorkloadConfig, SpireWorkloadIdentityClient
            notify = getattr(self.host, "selo_workload_identity_changed", None)
            if not callable(notify):
                raise ProviderUnavailable("HOST_WORKLOAD_REVOCATION_CONSUMER_UNAVAILABLE")
            client = SpireWorkloadIdentityClient(SpireWorkloadConfig(**config["workload"]),
                                                enabled=True, on_identity_change=notify)
        elif provider in {"tessera", "immudb"}:
            from sentra_runtime.tessera_provider import TesseraConfig, TesseraAuditProvider
            from sentra_runtime.immudb_provider import ImmudbAuditConfig, ImmudbAuditProvider
            settings = (TesseraConfig if provider == "tessera" else ImmudbAuditConfig)(
                owner=self.owner, workspace_id=self.workspace_id, **config["configuration"])
            client = (TesseraAuditProvider if provider == "tessera" else ImmudbAuditProvider)(
                config=settings, store=self.audit, executable=config["executable"],
                executable_sha256=config["executable_sha256"], enabled=True,
                credential_provider=lambda _provider, _profile: self._credential(config))
            # Bind the concrete owned SDK bridge to the SAME facade checkpoint,
            # including config/vault revision, before every private IPC effect.
            client.bridge._checkpoint = self._checkpoint
        else:
            raise ValueError("provider has no external client")
        # Admission transports close over their own CorePDP recheck; never cache
        # that closure for a different request. Only physical clients are cached.
        if checkpoint is None:
            self.clients[provider] = (row["revision"], client)
            self._credential_fingerprints[provider] = fingerprint
        return client

    def status(self):
        providers = []
        for provider in sorted(PROVIDERS):
            row = self.state.get("configuration:" + provider)
            missing = []
            if row and row["value"].get("enabled"):
                config = row["value"]
                files = ([config["executable"]] if provider in {"tessera", "immudb"} else
                         [config["workload"]["executable"]] if provider == "spire" else
                         [config["scan"]["executable"], config["sbom"], config["trusted_pins"]] if provider == "grype" else [])
                missing = ["dependency_file_missing" for path in files if not Path(path).is_file()]
            providers.append({"provider": provider, "revision": row["revision"] if row else None,
                "state": "configured" if row and row["value"].get("enabled") and not missing else "unavailable",
                "dependency_errors": missing,
                "client_created": provider in self.clients, "operational_verified": False,
                "actions": sorted(_ACTIONS[provider])})
        from sentra_quality.telemetry_state import ProtectedTelemetryQueue
        return {"backend": self.control.store.backend, "providers": providers,
                "audit": self.audit.status(), "telemetry": ProtectedTelemetryQueue(self.state).stats(),
                "grant_created": False, "closed": self._closed}

    def request_status(self, request_key):
        row = self.state.get("request:" + str(request_key))
        return {"request_key": request_key, "value": self._public_value(row["value"]) if row else None,
                "replay_effect": False}

    @staticmethod
    def _public_value(value):
        return {key: item for key, item in value.items() if key != "arguments"}

    async def dispatch(self, provider, action, arguments, *, request_key):
        self._provider(provider)
        if self._closed or action not in _ACTIONS[provider] or not isinstance(arguments, dict):
            raise ValueError("unavailable/unknown Selo dispatch action")
        if set(arguments) & _FORBIDDEN:
            raise PermissionError("browser/agent cannot supply identity, Grant, secret or configuration")
        if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request_key):
            raise ValueError("durable request_key required")
        args = __import__("json").loads(canonical(arguments))
        if len(canonical(args).encode()) > 512000:
            raise ValueError("Selo dispatch argument bound exceeded")
        context = self._context(provider=provider, action=action, arguments=args, request_key=request_key)
        config = self._config(provider)
        intent = digest([provider, action, args, config["revision"], context.receipt.operation_id])
        key = "request:" + request_key
        with self.state.transaction() as tx:
            previous = tx.get(key)
            if previous:
                if previous["value"]["intent_sha256"] != intent:
                    raise StateConflict("Selo request key immutable intent conflict")
                return self._public_value(previous["value"])
            value = {"provider": provider, "action": action, "intent_sha256": intent,
                "operation_id": context.receipt.operation_id, "state": "RUNNING", "result": None,
                "configuration_revision": config["revision"], "started_at": time.time()}
            value["arguments"] = args  # protected recovery selectors; never a public status DTO
            revision = tx.put(key, value)
        task = asyncio.current_task()
        self._active[request_key] = (provider, task)
        configuration_token = self._dispatch_configuration.set((provider, config["revision"]))
        try:
            self._checkpoint()
            self.coverage.capture(context, phase="admitted")
            result = await self._dispatch(provider, action, args, context, config["value"], request_key)
            self._checkpoint()
            self.coverage.capture(context, phase="returned")
            if hasattr(result, "public_metadata"):
                result = result.public_metadata()
            elif is_dataclass(result):
                result = asdict(result)
            value.update(state="SUCCEEDED", result=result, finished_at=time.time())
            self.state.put(key, value, expected_revision=revision)
            return self._public_value(value)
        except BaseException as exc:
            # A network write/read response or local mutation may already exist.
            # Keep the same key, never repeat it because a caller saw an error.
            value.update(state="UNCERTAIN", error_code=type(exc).__name__, finished_at=time.time())
            self.state.put(key, value, expected_revision=revision)
            raise
        finally:
            self._dispatch_configuration.reset(configuration_token)
            self._active.pop(request_key, None)

    async def _dispatch(self, provider, action, args, context, config, request_key):
        if action == "proof_read":
            reference = args["artifact"]
            offset, limit = args.get("offset", 0), args.get("limit", 262144)
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 262144:
                raise ValueError("invalid proof artifact page")
            data = self.audit.read_blob(reference)
            return {"artifact": reference, "offset": offset, "size_bytes": len(data),
                    "data_base64": base64.b64encode(data[offset:offset + limit]).decode(),
                    "next_offset": min(len(data), offset + limit), "complete": offset + limit >= len(data)}
        if action == "close": return await self.close_provider(provider)
        if action == "reconcile": return await self._reconcile(provider, args["target_request_key"], context)
        if action == "cancel": return await self.cancel(args["target_request_key"], provider=provider)
        if provider == "learning":
            if action == "propose":
                self._source_permission(self.references.snapshot(args["operation_id"], terminal=True), context)
                return self.learning.propose_from_artifact(request_key=request_key, **args)
            if action != "list":
                item = self.learning.get(self.owner, args["suggestion_id"])
                self._source_permission({"origin": item["origin"]}, context)
            else:
                page = self.learning.list(self.owner, **args)
                visible = []
                for item in page["items"]:
                    try:
                        self._source_permission({"origin": item["origin"]}, context)
                    except PermissionError:
                        continue
                    visible.append(item)
                return {"items": visible, "offset": args.get("offset", 0), "limit": args.get("limit", 100)}
            if action == "review":
                if self._identity_binding(context)["kind"] != "user":
                    raise PermissionError("learning review requires an authenticated human")
                return self.learning.review(self.owner, reviewer=context.request.principal_id, **args)
            methods = {"get": "get", "list": "list", "withdraw": "withdraw",
                       "skill_candidate": "to_skill_files", "skill_review_bundle": "review_bundle"}
            return getattr(self.learning, methods[action])(self.owner, **args)
        if provider == "memory":
            from memory.protected_store import ProtectedMemoryStore
            if action == "cost_summary":
                return self.control.cost_summary(self.owner, work_item_id=context.request.work_item_id)
            return getattr(ProtectedMemoryStore(self.state), action)(context=context, **args)
        if provider in {"langfuse", "otlp"}:
            from sentra_quality.telemetry_state import ProtectedTelemetryQueue
            if action in {"telemetry_flush", "prune"}:
                queue = ProtectedTelemetryQueue(self.state, config=config if provider == "otlp" else {})
                if action == "prune": return queue.prune()
                return queue.flush(provider, self._client(provider), **args)
            from sentra_quality.eval_runtime import ProtectedEvalRuntime
            if action == "eval_item":
                self._source_permission(self.references.snapshot(args["operation_id"], terminal=True), context)
            if (action in {"eval_score", "score_create"} and
                    (args.get("correction_of") is not None or args.get("data_type") == "CORRECTION")
                    and self._identity_binding(context)["kind"] != "user"):
                raise PermissionError("human correction requires an authenticated user")
            return ProtectedEvalRuntime(self.state, self.references, self._client("langfuse"),
                                        export_content=config.get("export_content", False)).dispatch(
                                            action, args, context=context, request_key=request_key)
        if provider == "grype":
            from sentra_quality.grype_runtime import GrypeRuntime
            return await context.run_blocking(GrypeRuntime(self.state, config).dispatch,
                                             action, args, context=context)
        client = self._client(provider)
        if provider in {"tessera", "immudb"}:
            if action == "enqueue_operation":
                snapshot = self.references.snapshot(args["operation_id"], terminal=True)
                self._source_permission(snapshot, context)
                body = {"scope_sha256": self.audit.scope, "schema": "sentra.central-operation-commitment/v1",
                        "source_operation_id": snapshot["origin"]["operation_id"],
                        "origin_sha256": digest(snapshot["origin"]), "state": snapshot["state"],
                        "source_event_sha256": digest(snapshot), "proves_core_effect_coverage": False}
                return {"delivery_key": self.audit.enqueue(provider=provider,
                    profile_sha256=client.profile_sha256, event_id=digest(snapshot), body=body)}
            if action == "initialize_trust":
                if self._identity_binding(context)["kind"] != "user":
                    raise PermissionError("audit trust initialization requires authenticated operator")
                # Seed bytes are a pinned operator artifact, never browser JSON.
                artifact = self.control.durable.artifact_info(args["artifact_id"], self.owner)
                if artifact["run_id"] != context.receipt.run_id or artifact["sha256"] != args["sha256"]:
                    raise PermissionError("operator trust artifact scope/digest mismatch")
                raw = self.control.durable.read_artifact(args["artifact_id"], max_bytes=65536)
                result = (client.initialize_trust(checkpoint=raw) if provider == "tessera"
                          else client.initialize_trust(immutable_state_protobuf=raw))
            else:
                method = "status" if action == "remote_status" else action
                result = getattr(client, method)(**args)
        elif provider == "spire":
            result = (client.start(**args) if action == "connect" else
                      client.jwt_svid(**args) if action == "jwt" else
                      client.trust_bundles() if action == "bundles" else getattr(client, action)(**args))
        elif provider == "keycloak":
            binding = self._identity_binding(context)
            if action == "login_begin":
                if not callable(getattr(self.host, "selo_identity_authenticated", None)):
                    raise ProviderUnavailable("HOST_AUTHENTICATED_SESSION_CONSUMER_UNAVAILABLE")
                result = client.begin_login(browser_binding=binding["browser_binding"], **args)
            elif action == "login_complete":
                consume = getattr(self.host, "selo_identity_authenticated", None)
                if not callable(consume): raise ProviderUnavailable("HOST_AUTHENTICATED_SESSION_CONSUMER_UNAVAILABLE")
                result = client.complete_login(browser_binding=binding["browser_binding"], **args)
                consume(owner=self.owner, workspace_id=self.workspace_id,
                        session_id=result["session_id"], principal=result["principal"])
                result = {"principal": asdict(result["principal"]), "consent_scopes": result["consent_scopes"],
                          "session_bound_server_side": True, "grant_created": False}
            elif action in {"authenticate", "refresh", "logout", "revoke", "session_status", "exchange"}:
                if action == "exchange":
                    result = client.token_exchange(binding["session_id"], **args)
                    # Credential remains inside the server. Consumption is an
                    # explicit trusted host method, never a browser DTO token.
                    consume = getattr(self.host, "selo_audience_credential", None)
                    if not callable(consume): raise ProviderUnavailable("HOST_AUDIENCE_CONSUMER_UNAVAILABLE")
                    consume(result)
                    result = result.public_metadata()
                else:
                    result = getattr(client, action)(binding["session_id"], **args)
            else:
                method = "retry_invalidation_notifications" if action == "retry_invalidations" else action
                result = getattr(client, method)(**args)
        elif provider == "openfga":
            if action == "discover":
                if args.get("object_type") != "work_item":
                    raise PermissionError("this host discovery catalog is WorkItem-scoped")
                result = client.list_objects(principal_id=context.request.principal_id, **args)
                # Return only candidates whose current CorePDP resource grant
                # permits navigation. Discovery never grants machine execution.
                data = asdict(result)
                kind = self._identity_binding(context)["kind"]
                data["objects"] = [obj for obj in result.objects if self._discovery_allowed(obj,
                    principal_id=context.request.principal_id, principal_type=kind)]
                result = data
            elif action == "changes":
                projection = self.state.scoped("selo.openfga")
                old = projection.get("changes")
                page = client.read_changes(continuation_token=old["value"]["continuation_token"] if old else "", **args)
                invalidate = getattr(self.host, "selo_relationships_changed", None)
                if not callable(invalidate): raise ProviderUnavailable("HOST_RELATION_INVALIDATION_UNAVAILABLE")
                invalidate(owner=self.owner, workspace_id=self.workspace_id, changes=page["changes"])
                projection.put("changes", {"continuation_token": page["continuation_token"],
                    "generation": (old["value"]["generation"] if old else 0) + 1},
                    expected_revision=old["revision"] if old else None)
                result = page
            else: result = client.read_assertions()
        else:
            if action == "observe_revision": return {"active_revision": client.active_revision()}
            return await self._bundle_action(action, args, config)
        if inspect.isawaitable(result): result = await result
        if action == "close": self.clients.pop(provider, None)
        return result if result is not None else {"closed": action == "close"}

    def _discovery_allowed(self, obj, *, principal_id, principal_type):
        try:
            kind, work_id = obj.split(":", 1)
            if kind != "work_item": return False
            work = self.control.governance.work_item_info(work_id, self.owner)
            run = self.control.durable.run_status(work["run_id"], self.owner, include_details=False)
            if not self.references.root_matches(run["workspace"]) or not self.references.work_matches(work): return False
            return self.control.authorization.authorize(self.owner, principal_type=principal_type,
                principal_id=principal_id, capability="selo.openfga.discover", scope_type="work_item",
                scope_id=work_id, local_owner=False).get("allowed") is True
        except Exception: return False

    async def _bundle_action(self, action, args, config):
        from sentra_runtime.policy_bundle import OPABundleManager, OPAOfflineValidator, OPABundleCandidate
        if not config.get("validator") or not config.get("bundle_root"):
            raise ProviderUnavailable("OPA_BUNDLE_PUBLICATION_UNCONFIGURED")
        manager = OPABundleManager(root=config["bundle_root"], workspace=self.workspace_root,
            store=self.state.scoped("selo.opa.bundle"), validator=OPAOfflineValidator(**config["validator"]),
            bundle_name=config.get("bundle_name", "sentra"))
        projection = self.state.scoped("selo.opa.candidates")
        if action == "bundle_stage":
            artifact = self.control.durable.artifact_info(args["artifact_id"], self.owner)
            if artifact["sha256"] != args["expected_sha256"]:
                raise PermissionError("OPA bundle artifact digest mismatch")
            if artifact["run_id"] != self._context().receipt.run_id:
                raise PermissionError("OPA bundle artifact outside current Run")
            self._checkpoint()
            candidate = manager.stage(artifact["path"], expected_sha256=args["expected_sha256"],
                                      expected_revision=args["expected_revision"])
            candidate_id = "candidate:" + digest(asdict(candidate))
            projection.put(candidate_id, asdict(candidate))
            return {"candidate_id": candidate_id, "sha256": candidate.sha256, "revision": candidate.revision}
        if action == "bundle_resource":
            resource = manager.resource()
            blob = self.audit.proof_blob(resource.pop("body"))
            return {**resource, "artifact": blob}
        if action == "bundle_status":
            authenticated = getattr(self.host, "selo_opa_instance_authorized", None)
            if not callable(authenticated): raise ProviderUnavailable("OPA_STATUS_AUTHENTICATION_UNAVAILABLE")
            return manager.accept_status(args["status"], trusted_instance_authorize=authenticated)
        candidate = projection.get(args["candidate_id"])
        if candidate is None: raise FileNotFoundError("staged OPA candidate unavailable")
        def authorize(*_):
            self._checkpoint()
            return True  # exact bundle_activate capability already centrally fenced
        return await manager.activate(OPABundleCandidate(**candidate["value"]),
            acceptance_cases=args["acceptance_cases"], trusted_admin_authorize=authorize)

    def policy(self, request, *, core_pdp, identity_binding=None):
        """Real deny-only admission wrapper; caller binds identity server-side.

        Wrap the BASE CorePDP, not this wrapper itself. Each HTTP roundtrip
        rechecks that same decision and constraints; discovery is never reused.
        """
        from sentra_runtime.contracts import PolicyDecision
        try:
            decision = core_pdp(request)
        except Exception:
            return PolicyDecision(False, "CorePDP unavailable")
        if not isinstance(decision, PolicyDecision):
            if inspect.iscoroutine(decision): decision.close()
            return PolicyDecision(False, "typed synchronous CorePDP decision required")
        if decision.allowed is not True:
            return decision
        def check():
            current = core_pdp(request)
            if (not isinstance(current, PolicyDecision) or current.allowed is not True
                    or current.constraints != decision.constraints):
                raise PermissionError("CorePDP changed during external veto")
        try:
            work = self.control.governance.work_item_info(request.work_item_id, self.owner)
            run = self.control.durable.run_status(work["run_id"], self.owner, include_details=False)
            if not self.references.root_matches(run["workspace"]) or not self.references.work_matches(work):
                raise PermissionError("veto workspace path/metadata mismatch")
            for provider in ("opa", "openfga", "keycloak", "spire"):
                row = self.state.get("configuration:" + provider)
                if not row or row["value"].get("enabled") is not True: continue
                check()
                credential_fingerprint = digest(self._credential(row["value"])) if row["value"].get("credential_ref") else None
                def check_profile(provider=provider, revision=row["revision"], credential_fingerprint=credential_fingerprint):
                    check()
                    current = self._config(provider)
                    if current["revision"] != revision:
                        raise StateConflict("external veto configuration changed during admission")
                    if credential_fingerprint is not None and digest(self._credential(current["value"])) != credential_fingerprint:
                        raise ProviderUnavailable("VAULT_CHANGED_DURING_VETO_ADMISSION")
                if provider in self.clients and self.clients[provider][0] != row["revision"]:
                    raise StateConflict("external identity client profile changed")
                client = (self.clients[provider][1] if provider == "spire" and provider in self.clients
                          else self._client(provider, checkpoint=check_profile))
                if provider == "opa": allowed = client.decide(request=request, workspace_id=self.workspace_id).allowed
                elif provider == "openfga": allowed = client.allows(request=request)
                else:
                    if not isinstance(identity_binding, dict): raise PermissionError("trusted identity binding required")
                    identity = (client.authenticate(identity_binding["session_id"]) if provider == "keycloak"
                                else client.authenticate(identity_binding["spiffe_id"]))
                    allowed = identity.principal_id == request.principal_id
                if allowed is not True: return PolicyDecision(False, "external policy veto: " + provider, decision.constraints)
                check_profile()
            return PolicyDecision(True, decision.reason, decision.constraints)
        except Exception:
            return PolicyDecision(False, "external policy/identity unavailable", decision.constraints)

    async def cancel(self, request_key, *, provider):
        target = self.state.get("request:" + str(request_key))
        if target is None or target["value"]["provider"] != provider:
            raise PermissionError("cancel target outside scoped provider")
        self._context()
        self._source_permission(self.references.snapshot(target["value"]["operation_id"]), self._context())
        active = self._active.get(request_key)
        if active:
            self.control.durable.request_cancel(target["value"]["operation_id"], self.owner,
                                                side_effect_may_have_started=True)
            active[1].cancel()
        return {"request_key": request_key, "cancel_requested": active is not None,
                "replay_effect": False, "status": self.request_status(request_key)}

    async def _reconcile(self, provider, target_key, context):
        row = self.state.get("request:" + str(target_key))
        if row is None or row["value"]["provider"] != provider:
            raise PermissionError("reconciliation target outside provider scope")
        target, evidence = row["value"], None
        if target_key in self._active:
            return {"target_request_key": target_key, "state": "RUNNING", "resubmitted": False}
        if target["state"] == "SUCCEEDED": return self._public_value(target)
        self._source_permission(self.references.snapshot(target["operation_id"]), context)
        args, action = target["arguments"], target["action"]
        if provider in {"tessera", "immudb"} and action in {"publish", "observe"}:
            client = self._client(provider)
            evidence = await client.observe(args["key"])
            if self.audit.row(args["key"])["state"] != "CONFIRMED": evidence = None
        elif provider == "keycloak" and action == "login_complete":
            client = self._client(provider)
            login = client.store.get("login:" + args["state"])
            if login and login["value"]["phase"] == "COMPLETED":
                session_id = login["value"]["session_id"]
                principal = client.authenticate(session_id)
                consume = getattr(self.host, "selo_identity_authenticated", None)
                if not callable(consume): raise ProviderUnavailable("HOST_AUTHENTICATED_SESSION_CONSUMER_UNAVAILABLE")
                consume(owner=self.owner, workspace_id=self.workspace_id, session_id=session_id, principal=principal)
                evidence = {"session_bound_server_side": True, "principal": asdict(principal)}
        elif provider == "langfuse":
            from sentra_quality.eval_runtime import ProtectedEvalRuntime
            runtime = ProtectedEvalRuntime(self.state, self.references, self._client(provider),
                                           export_content=self._config(provider)["value"].get("export_content", False))
            evidence = runtime.observe(action, args, target_key)
        elif provider == "grype" and action == "scan":
            scans = self.state.scoped("selo.grype").records("scan-")
            matches = [r["value"] for _, r in scans if r["value"]["operation_id"] == target["operation_id"]]
            if len(matches) == 1: evidence = matches[0]
        if evidence is None:
            return {"target_request_key": target_key, "state": "UNCERTAIN", "resubmitted": False,
                    "observer_available": provider in {"tessera", "immudb", "keycloak", "langfuse", "grype"}}
        context.checkpoint()
        target.update(state="SUCCEEDED", result=evidence, reconciled_by=context.receipt.operation_id,
                      effect_repeated=False)
        self.state.put("request:" + target_key, target, expected_revision=row["revision"])
        return self._public_value(target)

    def enqueue(self, event, *, correlations=None):
        """Trusted host event hook, asynchronous export does not alter effects."""
        from sentra_quality.telemetry_state import ProtectedTelemetryQueue
        targets = [p for p in ("otlp", "langfuse") if (self.state.get("configuration:" + p) or {}).get("value", {}).get("enabled")]
        if not targets: return {"enqueued": False, "reason": "telemetry_unconfigured"}
        otlp = self.state.get("configuration:otlp")
        return ProtectedTelemetryQueue(self.state, config=otlp["value"] if otlp else {}).enqueue(
            event, targets=targets, correlations=correlations)

    def record_effect_boundary(self, context, *, phase):
        """Trusted host hook for other executors; accepts no browser evidence."""
        return self.coverage.capture(context, phase=phase)

    def effect_coverage(self, run_id):
        return self.coverage.report(run_id)

    async def close_provider(self, provider):
        self._provider(provider)
        cached = self.clients.pop(provider, None)
        self._credential_fingerprints.pop(provider, None)
        if cached:
            method = getattr(cached[1], "close", None)
            if callable(method):
                result = method()
                if inspect.isawaitable(result): await result
        return {"provider": provider, "closed": True, "queued_proofs_preserved": True}

    async def close(self):
        tasks = []
        for _, task in list(self._active.values()):
            if task is not asyncio.current_task():
                task.cancel(); tasks.append(task)
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        for provider in list(self.clients): await self.close_provider(provider)
        self._closed = True
