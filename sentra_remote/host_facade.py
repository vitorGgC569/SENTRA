"""Concrete Vitra host facade: setup/doctor/repair/backup/migrate/update (Vitra-owned).

Server-only composition point. Root (Codex principal) binds this facade with
control/owner/Canvas callbacks plus config; the facade instantiates the REAL
runners from `guest_runners` and exposes an allowlisted `dispatch` with durable
`request_key` idempotency, receipts, and an admin-quiesce gate for effects.

No parallel authority, by construction:
- Owner admission (`authorize`), offline proof (`offline`) and quiesce proof
  (`quiesced`) are host-supplied callbacks bound to the authenticated session.
  The facade never mints grants, WorkItems, Runs or tokens.
- `control` is accepted for Root wiring convenience and reported as
  bound/unbound; the facade invokes ONLY the injected callbacks, never
  control internals for effect execution. Its reservation ledger uses the SAME
  configured store and consults central Operation state; it creates no authority.
- Process management (stop/kill/restart) does NOT exist here: there is no
  stop/kill capability to call. `apply_on_app_exit` only seals journals; the
  host's update helper applies bytes after the app exits, preserving live
  ConPTY sessions and the working version. Caller-supplied `exclude_pids`
  (e.g. preview PID 47408) are recorded in the receipt and never signaled —
  nothing here can signal any PID.
- Receipts carry phases/counts/digests only; DSNs, keys and secrets are never
  written to the receipt journal.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SCHEMA = 1

READ_ACTIONS = frozenset({
    "setup_states", "doctor", "backup_status", "update_status",
    "migration_status", "provider_inventory", "provider_states",
    "extension_plan", "pending_provenance", "receipts",
})
MUTATING_ACTIONS = frozenset({
    "repair", "backup_prepare", "backup_restore",
    "sqlite_migrate_prepare", "sqlite_migrate_commit", "sqlite_migrate_recover",
    "pg_migrate_prepare", "pg_migrate_commit", "pg_migrate_rollback",
    "update_stage", "update_commit",
    "provider_install", "provider_health", "provider_repair", "provider_configure",
    "provider_renew", "provider_recovery", "provider_remove", "provider_revoke",
})
ALLOWLIST = READ_ACTIONS | MUTATING_ACTIONS

# Effects that only probe (no state change) ride the mutating allowlist so
# they are receipted, but skip the quiesce gate.
PROBE_ONLY = frozenset({"provider_health"})


@dataclass(slots=True)
class VitraFacadeConfig:
    state_root: Path
    installation_id: str = ""
    receipts_path: Path | None = None
    exclude_pids: tuple[int, ...] = ()
    product_version: str = ""
    owner: str = ""
    install_root: Path | None = None

    def validated(self) -> "VitraFacadeConfig":
        source = Path(self.state_root).absolute()
        if source.is_symlink() or (hasattr(source, 'is_junction') and source.is_junction()):
            raise PermissionError("unsafe facade state root")
        root = source.resolve(strict=True)
        object.__setattr__(self, "state_root", root)
        return self


def _canonical(params: dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True, default=str)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _summarize(action: str, result: Any) -> dict[str, Any]:
    """Receipt-safe projection: phases/counts/digests, never secrets."""
    if isinstance(result, dict):
        safe: dict[str, Any] = {}
        for key in ("schema", "phase", "decision", "reason", "operation_id",
                    "version", "target", "current", "stale", "apply_on",
                    "alive", "action", "provider", "ok", "state", "count",
                    "from", "to", "files", "total", "states", "pid", "handoff_sha256", "manifest_sha256"):
            if key in result and isinstance(result[key], (str, int, bool, list, dict)):
                if key == 'files' and isinstance(result[key], list):
                    safe[key] = len(result[key]); continue
                if key == 'states' and isinstance(result[key], list):
                    safe[key] = [{k: item[k] for k in ('provider', 'ok', 'state') if k in item}
                                 for item in result[key][:64] if isinstance(item, dict)]
                    continue
                if isinstance(result[key], (list, dict)):
                    continue
                text = _canonical(result[key])
                if len(text) <= 2048 and "dsn" not in key and "secret" not in key and "key" != key:
                    safe[key] = result[key]
        return safe
    return {"result": str(result)[:256]}


class VitraHostFacade:
    """Server-only facade. Root binds callbacks; center/shell/CLI call dispatch."""

    def __init__(
        self, config: VitraFacadeConfig, *,
        control: Any = None,
        authorize: Callable[[str, str, str], bool] | None = None,
        offline: Callable[[], bool] | None = None,
        quiesced: Callable[[], bool] | None = None,
        apply_link: Callable[[str, str], None] | None = None,
        sql_runner: Callable[..., Any] | None = None,
        conpty_handles: Callable[[], list[str]] | None = None,
        sidecar_verify: Callable[[dict[str, Any]], bool] | None = None,
        provider_runner: Callable[..., dict[str, Any]] | None = None,
        dump_runner: Callable[..., Path] | None = None,
        restore_runner: Callable[..., None] | None = None,
        resolve_parameters: Callable[..., dict[str, Any]] | None = None,
        checkpoint: Callable[[], None] | None = None,
        repair_runner: Callable[..., dict[str, Any]] | None = None,
        migration_handlers: dict[str, Callable[..., dict[str, Any]]] | None = None,
        reconcile_callback: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.config = config.validated()
        self.control = control
        self._authorize = authorize
        self._offline = offline
        self._quiesced = quiesced
        self._apply_link = apply_link
        self._sql_runner = sql_runner
        self._conpty_handles = conpty_handles
        self._sidecar_verify = sidecar_verify
        self._resolve_parameters = resolve_parameters
        self._checkpoint_callback = checkpoint
        self._repair_runner = repair_runner
        self._migration_handlers = dict(migration_handlers or {})
        self._reconcile_callback = reconcile_callback
        self.owner = config.owner or getattr(getattr(control, "store", None), "principal_id", "")
        self._ledger = None
        if control is not None and self.owner and config.installation_id:
            from .maintenance_ledger import MaintenanceLedger
            self._ledger = MaintenanceLedger(control, owner=self.owner, installation_id=config.installation_id)
        if provider_runner is None or dump_runner is None or restore_runner is None:
            from . import guest_runners as _guests
            self._provider_runner = provider_runner or _guests.provider_runner
            self._dump_runner = dump_runner or _guests.postgres_dump_runner
            self._restore_runner = restore_runner or _guests.postgres_restore_runner
        else:
            self._provider_runner = provider_runner
            self._dump_runner = dump_runner
            self._restore_runner = restore_runner

    # -- transport ------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "allowlist": sorted(ALLOWLIST),
                "control_bound": self.control is not None,
                "callbacks": {"authorize": self._authorize is not None,
                              "offline": self._offline is not None,
                              "quiesced": self._quiesced is not None,
                              "apply_link": self._apply_link is not None,
                              "sql_runner": self._sql_runner is not None,
                              "conpty_handles": self._conpty_handles is not None,
                              "sidecar_verify": self._sidecar_verify is not None},
                "authority": "host control plane (no parallel authority here)",
                "exclude_pids": list(self.config.exclude_pids),
                "maintenance_revision": self._ledger.revision() if self._ledger else None,
                "parameter_authority": "host resolver only"}

    def _journal_path(self) -> Path | None:
        if self.config.receipts_path is None:
            return None
        path = Path(self.config.receipts_path).absolute()
        if path.is_symlink():
            raise PermissionError("unsafe receipts journal path")
        return path

    def _find_receipt(self, request_key: str) -> dict[str, Any] | None:
        journal = self._journal_path()
        if journal is None or not journal.is_file():
            return None
        try:
            lines = journal.read_text(encoding="utf-8").splitlines()[-500:]
        except OSError:
            return None
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("request_key") == request_key:
                return entry
        return None

    def _seal_receipt(self, request_key: str, action: str,
                      params_digest: str, outcome: dict[str, Any]) -> dict[str, Any]:
        receipt = {"schema": SCHEMA, "request_key": request_key, "action": action,
                   "params_digest": params_digest, "sealed_at": time.time(),
                   "exclude_pids": list(self.config.exclude_pids), **outcome}
        journal = self._journal_path()
        if journal is not None:
            journal.parent.mkdir(parents=True, exist_ok=True)
            with journal.open("a", encoding="utf-8") as out:
                out.write(json.dumps(receipt, sort_keys=True) + "\n")
                out.flush()
                try:
                    os.fsync(out.fileno())
                except OSError:
                    pass
        return receipt

    # -- dispatch -------------------------------------------------------

    def dispatch(self, action: str, *, request_key: str = "",
                 params: dict[str, Any] | None = None) -> dict[str, Any]:
        """One allowlisted action with durable request_key idempotency."""
        name = (action or "").strip()
        if name not in ALLOWLIST:
            raise ValueError("vitra action is not allowlisted")
        key = (request_key or "").strip()
        if not key or len(key) > 128:
            raise ValueError("durable request_key is required (max 128)")
        if params is not None and not isinstance(params, dict):
            raise ValueError("dispatch params must be an object")
        given = dict(params or {})
        public_fields = {"provider", "configuration_id", "stage_id", "backup_id", "release_id", "migration_id", "which",
                         "expected_revision", "request_key", "from_version", "target_version"}
        if set(given) - public_fields or any(not isinstance(v, (str, int, bool)) for v in given.values()):
            raise PermissionError("lifecycle parameters/paths/authority must be resolved by the host")
        if self._resolve_parameters is None:
            if name not in {"provider_inventory", "pending_provenance", "receipts"}:
                raise RuntimeError("trusted lifecycle parameter resolver is not configured")
            trusted = given
        else:
            trusted = self._resolve_parameters(name, dict(given), request_key=key)
            if not isinstance(trusted, dict):
                raise ValueError("host lifecycle resolver returned invalid parameters")
        if name in READ_ACTIONS:
            if name == "receipts":
                return {"value": {"receipt": self._ledger.lookup(given.get("request_key", key)) if self._ledger else None}}
            return {"deduplicated": False, "value": self._read(name, trusted)}
        if self._ledger is None:
            raise RuntimeError("maintenance requires the configured Control Plane store")
        operation_id = str(trusted.get("operation_id") or "")
        previous = self._ledger.lookup(key)
        if previous is None:
            self._admit(operation_id, probe_only=name in PROBE_ONLY)
        elif self._authorize is None or self._authorize(self.owner, previous["operation_id"], self.config.installation_id) is not True:
            raise PermissionError("maintenance receipt access denied")
        def freeze(value):
            if isinstance(value, Path): return str(value)
            if isinstance(value, bytes): return {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
            if callable(value):
                identity = value if hasattr(value, '__qualname__') else type(value)
                return {"callback": identity.__module__ + "." + identity.__qualname__}
            if isinstance(value, dict): return {str(k): freeze(v) for k,v in value.items()}
            if isinstance(value, (list, tuple)): return [freeze(v) for v in value]
            if value is None or isinstance(value, (str, int, float, bool)): return value
            raise ValueError("unsupported trusted lifecycle intent value")
        intent = {"public": given, "trusted": freeze(trusted)}
        first = self._ledger.reserve(key, name, intent, operation_id,
            expected_revision=given.get("expected_revision"))
        if not first:
            prior = self._ledger.lookup(key)
            return {"deduplicated": True, "status": "uncertain" if prior["state"] in {"PENDING", "RUNNING", "UNCERTAIN"} else prior["state"].lower(),
                    "receipt": {k:v for k,v in prior.items() if k != "result"}, "value": prior["result"]}
        self._ledger.transition(key, from_state="PENDING", revision=1, state="RUNNING")
        from .lifecycle_effects import lifecycle_scope
        try:
            with lifecycle_scope(lambda: self._checkpoint(operation_id, name), provider_context={
                "control": self.control, "owner": self.owner, "state_root": self.config.state_root,
                "install_root": self.config.install_root, "configuration": trusted.get("provider_config", {}),
                "installation_id": self.config.installation_id}):
                self._checkpoint(operation_id, name)
                outcome = self._mutate(name, trusted)
            safe = _summarize(name, outcome)
            state = "DEFERRED" if isinstance(outcome, dict) and outcome.get("decision") == "defer" else "SUCCEEDED"
            if isinstance(outcome, dict) and outcome.get("decision") == "scheduled":
                state = "RUNNING"
            if isinstance(outcome, dict) and outcome.get("ok") is False:
                state = "FAILED"
            receipt = self._ledger.transition(key, from_state="RUNNING", revision=2, state=state, result=safe)
            return {"deduplicated": False, "status": "pending" if state == "RUNNING" else state.lower(), "value": safe,
                    "receipt": {k:v for k,v in receipt.items() if k != "result"}}
        except BaseException:
            # No effect is replayed on an exception, timeout or receipt failure.
            # Reservation remains authoritative evidence for reconciliation.
            try: self._ledger.transition(key, from_state="RUNNING", revision=2, state="UNCERTAIN")
            except Exception: pass
            raise RuntimeError("maintenance outcome uncertain; consult the original request_key without reexecuting") from None

    def _checkpoint(self, operation_id, action):
        self._admit(operation_id, probe_only=action in PROBE_ONLY)
        if self._checkpoint_callback is not None:
            self._checkpoint_callback()
        else:
            from sentra_runtime.effect_boundary import current_effect_context
            context = current_effect_context.get()
            if context is None:
                raise PermissionError("maintenance effect checkpoint is not composed")
            context.checkpoint()

    def reconcile(self, request_key, *, expected_revision):
        """Server-only evidence recovery; never reruns the reserved effect."""
        if self._ledger is None or self._reconcile_callback is None:
            raise RuntimeError("maintenance evidence reconciler is not configured")
        prior = self._ledger.lookup(request_key)
        if not prior or prior["revision"] != expected_revision:
            raise FileExistsError("maintenance reconciliation CAS changed")
        if prior["state"] not in {"PENDING", "RUNNING", "UNCERTAIN"}:
            return prior
        evidence = self._reconcile_callback(dict(prior))
        if (not isinstance(evidence, dict) or evidence.get("operation_id") != prior["operation_id"]
                or evidence.get("state") not in {"SUCCEEDED", "FAILED"}
                or not isinstance(evidence.get("receipt_id"), str) or not evidence["receipt_id"]):
            raise PermissionError("verified host effect receipt required for reconciliation")
        operation = self.control.durable.operation_status(prior["operation_id"], self.owner)
        if operation["state"] != evidence["state"]:
            raise PermissionError("effect receipt does not agree with central Operation")
        return self._ledger.transition(request_key, from_state=prior["state"], revision=expected_revision,
            state=evidence["state"], result=_summarize(prior["action"], evidence.get("result", {})))

    # -- reads (no approval, no quiesce, no journal) --------------------

    def _read(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "setup_states":
            from .setup_states import describe_setup_states
            return describe_setup_states(
                params.get("status") if isinstance(params.get("status"), dict) else {},
                current_version=str(params.get("current_version") or ""),
                newest_version=str(params.get("newest_version") or ""))
        if action == "doctor":
            from .install_doctor import inspect_installation, inspect_provider_surface
            root = params.get("install_root", "")
            plan = inspect_installation(Path(root)) if root else None
            return {"installation": plan.status if plan else "unknown",
                    "providers": inspect_provider_surface(
                        params.get("probes") if isinstance(params.get("probes"), dict) else None)}
        if action == "backup_status":
            reader = params.get('status_reader')
            if not callable(reader):
                raise RuntimeError('native C09 backup status reader is not composed')
            return reader()
        if action == "update_status":
            from .coordinated_upgrade import coordinated_status
            return coordinated_status(Path(str(params.get("stage") or ".")))
        if action == "migration_status":
            reader = params.get('status_reader')
            if not callable(reader):
                raise RuntimeError('native authority migration status reader is not composed')
            return reader()
        if action == "provider_inventory":
            from .optional_providers import transitive_inventory
            return transitive_inventory()
        if action == "provider_states":
            from .install_doctor import inspect_provider_surface
            return inspect_provider_surface(
                params.get("probes") if isinstance(params.get("probes"), dict) else None)
        if action == "extension_plan":
            from .coordinated_upgrade import plan_extension_update
            installed = params.get("installed")
            release = params.get("release")
            if not isinstance(installed, dict) or not isinstance(release, dict):
                raise ValueError("extension_plan requires installed + release manifests")
            return plan_extension_update(installed, release)
        if action == "pending_provenance":
            return pending_provenance()
        if action == "receipts":
            found = self._find_receipt(str(params.get("request_key") or ""))
            return {"receipt": found}
        raise ValueError("unreadable vitra action")

    # -- effects (approval + quiesce, receipted) ------------------------

    def _admit(self, operation_id: str, *, probe_only: bool = False) -> str:
        if not self.owner or not operation_id:
            raise PermissionError("owner operation identity required")
        installation = self.config.installation_id
        if not installation:
            raise PermissionError("facade installation binding required")
        if self._authorize is None or self._offline is None:
            raise PermissionError("owner-auth/offline callbacks not bound")
        if self._offline() is not True:
            raise PermissionError("offline process gate failed")
        if self._authorize(self.owner, operation_id, installation) is not True:
            raise PermissionError("owner admission denied")
        if self.control is None:
            raise PermissionError("same Control Plane authority required")
        operation = self.control.durable.operation_status(operation_id, self.owner)
        if operation["state"] not in {"STARTING", "RUNNING"} and not probe_only:
            raise PermissionError("maintenance operation is not active")
        if not probe_only:
            if self._quiesced is None or self._quiesced() is not True:
                raise PermissionError("admin-quiesced proof required for effects")
        return installation

    def _mutate(self, action: str, params: dict[str, Any]) -> Any:
        owner = self.owner
        operation_id = str(params.get("operation_id") or "")
        installation = self._admit(operation_id, probe_only=action in PROBE_ONLY)
        state = self.config.state_root
        auth, off = self._authorize, self._offline
        if action == "repair":
            if self._repair_runner is None:
                providers = params.get("providers")
                if not isinstance(providers, list) or not providers or not self._provider_runner:
                    raise ValueError("repair unavailable: no real repair plan/runner bound")
                results = []
                from .optional_providers import provider_repair
                for provider in providers:
                    self._checkpoint(operation_id, action)
                    result = provider_repair(provider, approved=True, runner=self._provider_runner)
                    results.append({"provider": provider, "ok": result.get("ok") is True})
                return {"ok": all(r["ok"] for r in results), "count": len(results), "states": results}
            return self._repair_runner(params)
        if action == "backup_prepare":
            result = self.control.store.backup(Path(params["stage"]), quiesced=True,
                file_roots=params.get("file_roots"), recovery_key=params.get("recovery_key"))
            return {"phase": "BACKED_UP", "manifest_sha256": result.get("manifest_sha256") if isinstance(result, dict) else None}
        if action == "backup_restore":
            return self.control.store.restore(Path(params["stage"]), manifest_sha256=params["manifest_sha256"], quiesced=True,
                file_roots=params.get("file_roots"), recovery_key=params.get("recovery_key"))
        if action.startswith("sqlite_migrate_"):
            handler = self._migration_handlers.get(action)
            if handler is None:
                raise RuntimeError("native authority migration handler is not composed")
            return handler(params)
        if action.startswith("pg_migrate_"):
            handler = self._migration_handlers.get(action)
            if handler is None:
                raise RuntimeError("native PostgreSQL migration handler is not composed")
            return handler(params)
        if action == "update_stage":
            from .coordinated_upgrade import stage_product_update
            manifest = params.get("manifest")
            if not isinstance(manifest, dict):
                raise ValueError("update_stage requires a release manifest")
            stage = stage_product_update(
                state, Path(str(params.get("stage") or "")), manifest,
                installation_id=installation, owner_id=owner, operation_id=operation_id,
                current_mcp_schema=int(params.get("current_mcp_schema") or 1),
                authorize=auth, offline=off)
            return {"stage": str(stage), "phase": "STAGED"}
        if action == "update_commit":
            return self.apply_on_app_exit(
                Path(str(params.get("stage") or "")), owner_id=owner,
                operation_id=operation_id, installation_id=installation,
                prepared=params.get("prepared"))
        if action.startswith("provider_"):
            runner = self._provider_runner
            if runner is None:
                raise ValueError(f"{action} unavailable: no provider runner bound")
            from . import optional_providers as _providers
            method = getattr(_providers, action, None)
            if method is None or not callable(method):
                raise ValueError("unknown provider action")
            approved = True  # actual approval was proven by the host's authorize callback
            if action == "provider_health":
                return method(str(params.get("provider") or ""), runner=runner)
            return method(str(params.get("provider") or ""),
                          approved=approved, runner=runner)
        raise ValueError("unhandled vitra action")

    def _sqlite_migrate(self, action: str, params: dict[str, Any],
                        installation: str, owner: str, auth: Any, off: Any) -> Any:
        from . import staged_upgrade as _su
        state = self.config.state_root
        stage = Path(str(params.get("stage") or ""))
        database = Path(str(params.get("database") or ""))
        if action == "sqlite_migrate_prepare":
            migrate = params.get("migrate")
            if migrate is not None and not callable(migrate):
                raise ValueError("sqlite migrate callback must be callable")
            return {"stage": str(_su.prepare_staged_migration(
                state, database, stage, installation_id=installation,
                owner_id=owner, operation_id=owner, authorize=auth, offline=off,
                migrate=migrate, target_schema=int(params.get("target_schema") or 0)))}
        if action == "sqlite_migrate_commit":
            _su.commit_staged_migration(
                stage, state, database, installation_id=installation,
                owner_id=owner, operation_id=owner, authorize=auth, offline=off)
            return {"phase": "COMMITTED"}
        _su.recover_interrupted_migration(
            stage, state, database, installation_id=installation,
            owner_id=owner, operation_id=owner, authorize=auth, offline=off)
        return {"phase": "RECOVERED"}

    def _pg_migrate(self, action: str, params: dict[str, Any],
                    installation: str, owner: str, auth: Any, off: Any) -> Any:
        from . import postgres_migration as _pg
        state = self.config.state_root
        dsn = str(params.get("dsn") or "")
        if action == "pg_migrate_prepare":
            return {"stage": str(_pg.prepare_postgres_migration(
                state, Path(str(params.get("stage") or "")),
                database=str(params.get("database") or ""),
                current_version=int(params.get("current_version") or 0),
                target_version=int(params.get("target_version") or 0),
                statements_digest=str(params.get("statements_digest") or ""),
                installation_id=installation, owner_id=owner, operation_id=owner,
                authorize=auth, offline=off,
                dump_runner=self._dump_runner, dsn=dsn))}
        if action == "pg_migrate_commit":
            if self._sql_runner is None:
                raise ValueError("postgres migration unavailable: no SQL runner bound")
            return _pg.commit_postgres_migration(
                Path(str(params.get("stage") or "")), state,
                installation_id=installation, owner_id=owner, operation_id=owner,
                authorize=auth, offline=off, sql_runner=self._sql_runner,
                statements=str(params.get("statements") or ""), dsn=dsn)
        return _pg.rollback_postgres_migration(
            Path(str(params.get("stage") or "")), state,
            installation_id=installation, owner_id=owner, operation_id=owner,
            authorize=auth, offline=off, restore_runner=self._restore_runner, dsn=dsn)

    # -- app-exit apply (seal only; never touches processes) -----------

    def apply_on_app_exit(self, stage_dir: Path, *, owner_id: str,
                          operation_id: str, installation_id: str = "", prepared=None) -> dict[str, Any]:
        """Seal a staged product update for application after the app exits.

        Defers while any ConPTY session is alive (handles from the bound
        provider; Pulso registry stays authoritative). Preserves the working
        version on any failure — bytes are applied later by the host's update
        helper, never here. No PID is ever signaled; `exclude_pids` (preview
        PID 47408 and friends) are recorded in the outcome for the host log.
        """
        from .coordinated_upgrade import commit_product_update
        installation = installation_id or self.config.installation_id
        handles: list[str] | None = None
        if self._conpty_handles is not None:
            try:
                seen = self._conpty_handles()
                if not isinstance(seen, list) or any(not isinstance(h, str) or not h for h in seen):
                    raise ValueError('invalid live ConPTY inventory')
                handles = list(seen)
            except Exception:
                handles = None
        if handles is None:
            return {"phase": "STAGED", "decision": "defer",
                    "reason": "conpty_handles_unavailable",
                    "exclude_pids": list(self.config.exclude_pids)}
        if prepared is None or self.config.install_root is None:
            return {"phase":"STAGED","decision":"defer","reason":"verified_package_handoff_unavailable"}
        result = commit_product_update(
            stage_dir, installation_id=installation, owner_id=owner_id,
            operation_id=operation_id, authorize=self._authorize,
            offline=self._offline, alive_conpty_handles=handles)
        if result.get('decision') == 'defer': return result
        from .app_exit_update import schedule_on_exit
        return {**schedule_on_exit(control=self.control,owner=self.owner,operation_id=operation_id,
            installation_id=installation,state_root=self.config.state_root,install_dir=self.config.install_root,
            prepared=prepared,conpty_handles=handles,checkpoint=lambda:self._checkpoint(operation_id,'update_commit')),
            "exclude_pids": list(self.config.exclude_pids)}


VITRA_FACADE_SIGNATURE: dict[str, Any] = {
    "schema": 1,
    "reads": sorted(READ_ACTIONS),
    "effects": sorted(a for a in MUTATING_ACTIONS if a not in PROBE_ONLY),
    "probes": sorted(PROBE_ONLY),
    "construction": ("VitraHostFacade(config, control=..., authorize=..., offline=..., "
                     "quiesced=..., conpty_handles=..., resolve_parameters=..., checkpoint=..., "
                     "repair_runner=..., provider_runner=..., migration_handlers=..., "
                     "reconcile_callback=...) — all callbacks server-only, bound by Root"),
    "invariants": [
        "no grants/WorkItems/Runs/tokens minted here",
        "effects require owner admission + offline proof + admin quiesce",
        "durable reservation BEFORE effect; same key and fingerprint only consults state/receipt",
        "PENDING/RUNNING/UNCERTAIN never reexecutes; host evidence and CAS reconcile",
        "apply_on_app_exit seals journals and schedules only the verified host update helper",
        "no process signaling capability exists in this module",
    ],
}


def pending_provenance() -> dict[str, Any]:
    """Pins awaiting the final build/distrib (QuickJS guest, RustDesk/HCS).

    Recorded as PENDING implementation, never homologation: no digests are
    fabricated and no readiness is claimed. Other owners (Pacto/Forja) own
    the artifacts; Vitra tracks the release-blocking pin record.
    """
    path = Path(__file__).resolve().parent / "pending_provenance.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": SCHEMA, "state": "unrecorded"}
    return data if isinstance(data, dict) else {"schema": SCHEMA, "state": "invalid"}
