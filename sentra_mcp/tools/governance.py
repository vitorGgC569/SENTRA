"""Compact governance/control-plane MCP surface."""
from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.auth.middleware.auth_context import get_access_token

from ..errors import SentraSemanticError, error_envelope
from ..identity import authorization_principal, resolve_owner
from ..models import ResponseEnvelope
from ..services.governance import GovernanceConflict


def _ok(value: dict[str, Any]) -> ResponseEnvelope:
    return ResponseEnvelope.success(value)


def _required(name: str, value: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{name} is required for this action")
    return value


def _fail(exc: Exception) -> ResponseEnvelope:
    if isinstance(exc, SentraSemanticError):
        return error_envelope(exc)
    if isinstance(exc, GovernanceConflict):
        return error_envelope(SentraSemanticError(
            "STATE_CONFLICT", str(exc), category="state", retryable=False
        ))
    if isinstance(exc, PermissionError):
        return error_envelope(exc, code="forbidden")
    if isinstance(exc, FileNotFoundError):
        return error_envelope(exc, code="not_found")
    if isinstance(exc, FileExistsError):
        return error_envelope(exc, code="conflict")
    if isinstance(exc, (ValueError, TypeError)):
        return error_envelope(exc, code="invalid_request")
    return error_envelope(exc, code="governance_error")


def register_governance_tools(
    mcp: MCPServer,
    control_plane: Any,
    *,
    specialized: bool = False,
    conversation_memory: Any | None = None,
) -> None:
    def specialized_tool():
        if specialized:
            return mcp.tool()
        return lambda fn: fn

    @mcp.tool()
    def sentra_governance(
        action: Literal[
            "work_create", "work_get", "work_list", "work_transition",
            "work_checkout", "work_start", "work_release", "work_failure",
            "work_recovery", "work_recovery_complete", "work_quality_gate",
            "work_policy_submit", "work_policy_decide",
            "activity_list", "cost_record", "cost_summary",
            "routine_create", "routine_get", "routine_fire",
            "secret_create", "secret_get", "secret_rotate", "secret_bind",
            "work_product_register", "skill_install", "plugin_register",
            "blueprint_export", "blueprint_import",
        ],
        ctx: Context,
        run_id: str | None = None,
        goal_id: str | None = None,
        agent_id: str | None = None,
        work_item_id: str | None = None,
        objective: str | None = None,
        work_state: str | None = None,
        work_states: list[str] | None = None,
        external_key: str | None = None,
        parent_work_item_id: str | None = None,
        acceptance_criteria: list[str] | None = None,
        blockers: list[str] | None = None,
        dependencies: list[str] | None = None,
        assignee_user_id: str | None = None,
        required_capabilities: list[str] | None = None,
        target_files: list[str] | None = None,
        resource_locks: list[str] | None = None,
        side_effect_scope: str = "workspace",
        execution_policy: dict[str, Any] | None = None,
        retry_policy: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        reason: str = "",
        recovery_class: str | None = None,
        recovery_outcome: str = "resume",
        error_class: str | None = None,
        side_effect_may_have_started: bool = False,
        failure_chain_id: str | None = None,
        evidence: list[str] | None = None,
        quality_gate_passed: bool | None = None,
        candidate_revision: str | None = None,
        actor_type: str | None = None,
        actor_id: str | None = None,
        decision: str | None = None,
        comment: str = "",
        actual_cost: float = 0.0,
        market_cost: float = 0.0,
        quota_usage: float = 0.0,
        currency: str = "USD",
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        provider: str | None = None,
        model: str | None = None,
        workspace: str | None = None,
        operation_id: str | None = None,
        routine_id: str | None = None,
        routine_name: str | None = None,
        trigger_kind: str | None = None,
        trigger_spec: dict[str, Any] | None = None,
        work_template: dict[str, Any] | None = None,
        active_policy: str = "coalesce_if_active",
        missed_policy: str = "skip_missed",
        missed_cap: int = 1,
        enabled: bool = True,
        next_due_at: float | None = None,
        source: str = "manual",
        secret_id: str | None = None,
        secret_name: str | None = None,
        secret_value: str | None = None,
        scope_type: str = "instance",
        scope_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        env_name: str | None = None,
        purpose: str = "runtime",
        artifact_id: str | None = None,
        work_product_kind: str = "artifact",
        work_product_title: str = "",
        skill_name: str | None = None,
        skill_version: str | None = None,
        skill_content: str | None = None,
        skill_source: str = "local",
        plugin_manifest: dict[str, Any] | None = None,
        verified_methods: list[str] | None = None,
        narrowed_capabilities: list[str] | None = None,
        trusted_ui: bool = False,
        blueprint: dict[str, Any] | None = None,
        dry_run: bool = True,
        offset: int = 0,
        limit: int = 100,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Operate SENTRA work/governance state without bypassing Durable authority."""
        try:
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)

            if action == "work_create":
                return _ok(control_plane.create_work_item(
                    str(_required("run_id", run_id)), owner,
                    objective=str(_required("objective", objective)),
                    goal_id=goal_id, external_key=external_key,
                    parent_work_item_id=parent_work_item_id,
                    acceptance_criteria=acceptance_criteria, blockers=blockers,
                    dependencies=dependencies, assignee_agent_id=agent_id,
                    assignee_user_id=assignee_user_id,
                    required_capabilities=required_capabilities, target_files=target_files,
                    resource_locks=resource_locks, side_effect_scope=side_effect_scope,
                    execution_policy=execution_policy, retry_policy=retry_policy,
                    budget=budget, metadata=metadata,
                ))
            if action == "work_get":
                return _ok(control_plane.work_item_info(
                    str(_required("work_item_id", work_item_id)), owner
                ))
            if action == "work_list":
                return _ok(control_plane.list_work_items(
                    owner, run_id=run_id, states=work_states, limit=limit, offset=offset
                ))
            if action == "work_transition":
                return _ok(control_plane.transition_work_item(
                    str(_required("work_item_id", work_item_id)), owner,
                    str(_required("work_state", work_state)), reason=reason, metadata=metadata,
                ))
            if action == "work_checkout":
                return _ok(control_plane.checkout_work_item(
                    str(_required("work_item_id", work_item_id)), owner,
                    run_id=str(_required("run_id", run_id)), agent_id=agent_id,
                ))
            if action == "work_start":
                return _ok(control_plane.start_work_item_execution(
                    str(_required("work_item_id", work_item_id)), owner,
                    run_id=str(_required("run_id", run_id)), agent_id=agent_id,
                ))
            if action == "work_release":
                return _ok(control_plane.release_work_item_locks(
                    str(_required("work_item_id", work_item_id)), owner,
                    run_id=str(_required("run_id", run_id)),
                ))
            if action == "work_failure":
                return _ok(control_plane.record_work_item_failure(
                    str(_required("work_item_id", work_item_id)), owner,
                    error_class=str(_required("error_class", error_class)),
                    side_effect_may_have_started=side_effect_may_have_started,
                    failure_chain_id=failure_chain_id,
                ))
            if action == "work_recovery":
                return _ok(control_plane.begin_work_item_recovery(
                    str(_required("work_item_id", work_item_id)), owner,
                    recovery_class=str(_required("recovery_class", recovery_class)),
                    run_id=run_id, agent_id=agent_id,
                ))
            if action == "work_recovery_complete":
                return _ok(control_plane.complete_work_item_recovery(
                    str(_required("work_item_id", work_item_id)), owner,
                    outcome=recovery_outcome, reason=reason,
                ))
            if action == "work_quality_gate":
                return _ok(control_plane.record_work_item_quality_gate(
                    str(_required("work_item_id", work_item_id)), owner,
                    passed=bool(_required("quality_gate_passed", quality_gate_passed)),
                    reason=reason, evidence=evidence,
                    candidate_revision=candidate_revision, metadata=metadata,
                ))
            if action == "work_policy_submit":
                return _ok(control_plane.submit_work_item_policy(
                    str(_required("work_item_id", work_item_id)), owner, evidence=evidence,
                ))
            if action == "work_policy_decide":
                return _ok(control_plane.decide_work_item_policy(
                    str(_required("work_item_id", work_item_id)), owner,
                    actor_type=str(_required("actor_type", actor_type)),
                    actor_id=str(_required("actor_id", actor_id)),
                    decision=str(_required("decision", decision)),
                    comment=comment, evidence=evidence,
                ))
            if action == "activity_list":
                return _ok(control_plane.list_activity(owner, limit=limit, offset=offset))
            if action == "cost_record":
                return _ok(control_plane.record_cost(
                    owner, actual_cost=actual_cost, market_cost=market_cost,
                    quota_usage=quota_usage, currency=currency, input_tokens=input_tokens,
                    output_tokens=output_tokens, reasoning_tokens=reasoning_tokens,
                    workspace=workspace, goal_id=goal_id, work_item_id=work_item_id,
                    run_id=run_id, operation_id=operation_id, agent_id=agent_id,
                    provider=provider, model=model, metadata=metadata,
                ))
            if action == "cost_summary":
                return _ok(control_plane.cost_summary(
                    owner, work_item_id=work_item_id, run_id=run_id,
                    goal_id=goal_id, agent_id=agent_id,
                ))
            if action == "routine_create":
                return _ok(control_plane.create_routine(
                    owner, name=str(_required("routine_name", routine_name)),
                    trigger_kind=str(_required("trigger_kind", trigger_kind)),
                    trigger_spec=trigger_spec or {}, work_template=work_template or {},
                    active_policy=active_policy, missed_policy=missed_policy,
                    missed_cap=missed_cap, enabled=enabled, next_due_at=next_due_at,
                    authority_run_id=run_id, goal_id=goal_id, metadata=metadata,
                ))
            if action == "routine_get":
                return _ok(control_plane.routine_info(
                    str(_required("routine_id", routine_id)), owner
                ))
            if action == "routine_fire":
                return _ok(control_plane.fire_routine(
                    str(_required("routine_id", routine_id)), owner,
                    run_id=str(_required("run_id", run_id)), goal_id=goal_id, source=source,
                ))
            if action == "secret_create":
                return _ok(control_plane.create_secret(
                    owner, name=str(_required("secret_name", secret_name)),
                    value=str(_required("secret_value", secret_value)),
                    scope_type=scope_type, scope_id=scope_id, metadata=metadata,
                ))
            if action == "secret_get":
                return _ok(control_plane.secret_info(
                    str(_required("secret_id", secret_id)), owner
                ))
            if action == "secret_rotate":
                return _ok(control_plane.rotate_secret(
                    str(_required("secret_id", secret_id)), owner,
                    value=str(_required("secret_value", secret_value)),
                ))
            if action == "secret_bind":
                return _ok(control_plane.bind_secret(
                    str(_required("secret_id", secret_id)), owner,
                    target_type=str(_required("target_type", target_type)),
                    target_id=str(_required("target_id", target_id)),
                    env_name=env_name, purpose=purpose,
                ))
            if action == "work_product_register":
                return _ok(control_plane.register_work_product(
                    str(_required("work_item_id", work_item_id)), owner,
                    artifact_id=str(_required("artifact_id", artifact_id)),
                    kind=work_product_kind, title=work_product_title, metadata=metadata,
                ))
            if action == "skill_install":
                return _ok(control_plane.install_skill(
                    owner, name=str(_required("skill_name", skill_name)),
                    version=str(_required("skill_version", skill_version)),
                    content=str(_required("skill_content", skill_content)),
                    source=skill_source, metadata=metadata,
                ))
            if action == "plugin_register":
                return _ok(control_plane.register_plugin(
                    owner, manifest=plugin_manifest or {},
                    verified_methods=verified_methods,
                    narrowed_capabilities=narrowed_capabilities,
                    trusted_ui=trusted_ui, metadata=metadata,
                ))
            if action == "blueprint_export":
                return _ok(control_plane.export_blueprint(
                    str(_required("run_id", run_id)), owner
                ))
            if action == "blueprint_import":
                return _ok(control_plane.import_blueprint(
                    str(_required("run_id", run_id)), owner,
                    blueprint=dict(_required("blueprint", blueprint)),
                    dry_run=dry_run,
                ))
            raise ValueError("unsupported governance action")
        except Exception as exc:
            return _fail(exc)


    @mcp.tool()
    def sentra_coordination(
        action: Literal[
            "event_ingest", "event_stream_status",
            "session_checkpoint_write", "session_checkpoint_get",
            "conversation_list", "conversation_get", "conversation_search",
            "workspace_create", "workspace_get", "workspace_transition",
            "workspace_acquire", "workspace_renew", "workspace_release",
        ],
        ctx: Context,
        source_instance_id: str | None = None,
        source_epoch: str | None = None,
        source_seq: int | None = None,
        payload: dict[str, Any] | None = None,
        cursor: dict[str, Any] | None = None,
        event_id: str | None = None,
        run_id: str | None = None,
        chat_id: str | None = None,
        workspace: str | None = None,
        conversation_id: str | None = None,
        query: str | None = None,
        limit: int = 20,
        operation_id: str | None = None,
        idempotency_key: str | None = None,
        execution_workspace_id: str | None = None,
        authority_run_id: str | None = None,
        execution_run_id: str | None = None,
        work_item_id: str | None = None,
        backend: str | None = None,
        physical_ref: str | None = None,
        device_id: str | None = None,
        base_revision: str | None = None,
        current_revision: str | None = None,
        workspace_state: str | None = None,
        fencing_token: int | None = None,
        ttl_s: float = 300.0,
        dirty: bool = False,
        metadata: dict[str, Any] | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Ordered source ingress and durable execution-workspace ownership."""
        try:
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            if action in {"conversation_list", "conversation_get", "conversation_search"}:
                if conversation_memory is None:
                    raise RuntimeError("local conversation memory is unavailable")
                principal, _, _ = authorization_principal(ctx)
                return _ok(conversation_memory.read(
                    action, principal=principal, owner=owner, workspace=workspace,
                    path=physical_ref or ".", session_id=conversation_id, query=query, limit=limit, cursor=cursor,
                    local_operator=get_access_token() is None))
            if action == "event_ingest":
                if type(source_seq) is not int:
                    raise ValueError("source_seq is required for this action")
                return _ok(control_plane.ingest_source_event(
                    owner,
                    source_instance_id=str(_required("source_instance_id", source_instance_id)),
                    source_epoch=str(_required("source_epoch", source_epoch)),
                    source_seq=source_seq,
                    payload=payload or {},
                    event_id=event_id,
                    run_id=run_id,
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                ))
            if action == "event_stream_status":
                return _ok(control_plane.source_stream_status(
                    owner,
                    source_instance_id=str(_required("source_instance_id", source_instance_id)),
                    source_epoch=str(_required("source_epoch", source_epoch)),
                ))
            if action == "session_checkpoint_write":
                if type(source_seq) is not int:
                    raise ValueError("source_seq is required for this action")
                return _ok(control_plane.write_session_checkpoint(
                    owner,
                    run_id=str(_required("run_id", run_id)),
                    chat_id=str(_required("chat_id", chat_id)),
                    source_instance_id=str(_required("source_instance_id", source_instance_id)),
                    source_epoch=str(_required("source_epoch", source_epoch)),
                    source_seq=source_seq,
                    checkpoint=payload or {},
                    cursor=cursor,
                ))
            if action == "session_checkpoint_get":
                return _ok(control_plane.latest_session_checkpoint(
                    owner,
                    run_id=str(_required("run_id", run_id)),
                    chat_id=str(_required("chat_id", chat_id)),
                    source_instance_id=source_instance_id,
                    source_epoch=source_epoch,
                ))
            if action == "workspace_create":
                return _ok(control_plane.create_execution_workspace(
                    owner,
                    authority_run_id=str(_required("authority_run_id", authority_run_id or run_id)),
                    work_item_id=work_item_id,
                    backend=str(_required("backend", backend)),
                    physical_ref=physical_ref,
                    device_id=device_id,
                    base_revision=base_revision,
                    metadata=metadata,
                ))
            if action == "workspace_get":
                return _ok(control_plane.execution_workspace_info(
                    str(_required("execution_workspace_id", execution_workspace_id)), owner
                ))
            if action == "workspace_transition":
                return _ok(control_plane.transition_execution_workspace(
                    str(_required("execution_workspace_id", execution_workspace_id)), owner,
                    str(_required("workspace_state", workspace_state)),
                    current_revision=current_revision, metadata=metadata,
                ))
            if action == "workspace_acquire":
                return _ok(control_plane.acquire_execution_workspace(
                    str(_required("execution_workspace_id", execution_workspace_id)), owner,
                    execution_run_id=str(_required("execution_run_id", execution_run_id or run_id)),
                    operation_id=operation_id, ttl_s=ttl_s,
                ))
            if action == "workspace_renew":
                if type(fencing_token) is not int:
                    raise ValueError("fencing_token is required for this action")
                return _ok(control_plane.renew_execution_workspace(
                    str(_required("execution_workspace_id", execution_workspace_id)), owner,
                    fencing_token=fencing_token, ttl_s=ttl_s,
                ))
            if action == "workspace_release":
                if type(fencing_token) is not int:
                    raise ValueError("fencing_token is required for this action")
                return _ok(control_plane.release_execution_workspace(
                    str(_required("execution_workspace_id", execution_workspace_id)), owner,
                    fencing_token=fencing_token, dirty=dirty,
                ))
            raise ValueError("unsupported coordination action")
        except Exception as exc:
            return _fail(exc)


    @specialized_tool()
    def sentra_blueprint(
        action: Literal["export", "import"],
        ctx: Context,
        run_id: str,
        blueprint: dict[str, Any] | None = None,
        dry_run: bool = True,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Export/import portable SENTRA control-plane blueprints without secrets."""
        try:
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            if action == "export":
                return _ok(control_plane.export_blueprint(run_id, owner))
            if action == "import":
                return _ok(control_plane.import_blueprint(
                    run_id, owner, blueprint=blueprint or {}, dry_run=dry_run
                ))
            raise ValueError("unsupported blueprint action")
        except Exception as exc:
            return _fail(exc)


    @specialized_tool()
    def sentra_policy(
        action: Literal["grant", "revoke", "check", "list"],
        ctx: Context,
        grant_id: str | None = None,
        principal_type: str | None = None,
        principal_id: str | None = None,
        capability: str | None = None,
        scope_type: str = "instance",
        scope_id: str | None = None,
        conditions: dict[str, Any] | None = None,
        ancestors: dict[str, list[str]] | None = None,
        decision_context: dict[str, Any] | None = None,
        ttl_s: float | None = None,
        include_revoked: bool = False,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Manage/check capability grants. Roles are not an authorization source."""
        try:
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            if action == "grant":
                return _ok(control_plane.authorization_grant(
                    owner,
                    principal_type=str(_required("principal_type", principal_type)),
                    principal_id=str(_required("principal_id", principal_id)),
                    capability=str(_required("capability", capability)),
                    scope_type=scope_type,
                    scope_id=scope_id,
                    conditions=conditions,
                    ttl_s=ttl_s,
                ))
            if action == "revoke":
                return _ok(control_plane.authorization_revoke(
                    str(_required("grant_id", grant_id)), owner
                ))
            if action == "check":
                return _ok(control_plane.authorization_check(
                    owner,
                    principal_type=str(_required("principal_type", principal_type)),
                    principal_id=str(_required("principal_id", principal_id)),
                    capability=str(_required("capability", capability)),
                    scope_type=scope_type,
                    scope_id=scope_id,
                    ancestors=ancestors,
                    context=decision_context,
                    local_owner=(
                        authorization_principal(ctx)[0] == "local-operator"
                        and principal_type == "user"
                        and principal_id == owner
                    ),
                ))
            if action == "list":
                return _ok(control_plane.authorization_list(
                    owner,
                    principal_type=principal_type,
                    principal_id=principal_id,
                    include_revoked=include_revoked,
                ))
            raise ValueError("unsupported policy action")
        except Exception as exc:
            return _fail(exc)


    @specialized_tool()
    def sentra_budget(
        action: Literal["set", "check", "list"],
        ctx: Context,
        scope_type: str = "instance",
        scope_id: str | None = None,
        limits: dict[str, Any] | None = None,
        mode: str = "hard_stop",
        window_seconds: float | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
        workspace: str | None = None,
        goal_id: str | None = None,
        work_item_id: str | None = None,
        run_id: str | None = None,
        operation_id: str | None = None,
        agent_id: str | None = None,
        provider: str | None = None,
        proposed: dict[str, Any] | None = None,
        enabled_only: bool = False,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Manage hierarchical actual/market/quota/token budget admission."""
        try:
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            if action == "set":
                return _ok(control_plane.budget_set(
                    owner,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    limits=limits or {},
                    mode=mode,
                    window_seconds=window_seconds,
                    enabled=enabled,
                    metadata=metadata,
                ))
            if action == "check":
                return _ok(control_plane.budget_check(
                    owner,
                    workspace=workspace,
                    goal_id=goal_id,
                    work_item_id=work_item_id,
                    run_id=run_id,
                    operation_id=operation_id,
                    agent_id=agent_id,
                    provider=provider,
                    proposed=proposed,
                ))
            if action == "list":
                return _ok(control_plane.budget_list(
                    owner, enabled_only=enabled_only
                ))
            raise ValueError("unsupported budget action")
        except Exception as exc:
            return _fail(exc)


    @specialized_tool()
    def sentra_plugin(
        action: Literal["info", "list", "worker_start", "worker_call", "worker_stop"],
        ctx: Context,
        plugin_id: str | None = None,
        plugin_worker_id: str | None = None,
        command: str | list[str] | None = None,
        workspace: str | None = None,
        mode: str | None = None,
        run_id: str | None = None,
        timeout_s: float = 5.0,
        narrowed_capabilities: list[str] | None = None,
        method: str | None = None,
        params: dict[str, Any] | None = None,
        scope_type: str = "instance",
        scope_id: str | None = None,
        ancestors: dict[str, list[str]] | None = None,
        policy_context: dict[str, Any] | None = None,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Manage verified out-of-process plugin workers."""
        try:
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            if action == "info":
                return _ok(control_plane.plugin_info(
                    str(_required("plugin_id", plugin_id)), owner
                ))
            if action == "list":
                return _ok(control_plane.plugin_list(owner))
            if action == "worker_start":
                return _ok(control_plane.plugin_worker_start(
                    owner,
                    plugin_id=str(_required("plugin_id", plugin_id)),
                    command=command,
                    workspace=workspace,
                    mode=mode,
                    run_id=run_id,
                    timeout_s=timeout_s,
                    narrowed_capabilities=narrowed_capabilities,
                ))
            if action == "worker_call":
                return _ok(control_plane.plugin_worker_call(
                    str(_required("plugin_worker_id", plugin_worker_id)),
                    owner,
                    method=str(_required("method", method)),
                    params=params or {},
                    scope_type=scope_type,
                    scope_id=scope_id,
                    ancestors=ancestors,
                    policy_context=policy_context,
                    timeout_s=timeout_s,
                ))
            if action == "worker_stop":
                return _ok(control_plane.plugin_worker_stop(
                    str(_required("plugin_worker_id", plugin_worker_id)), owner
                ))
            raise ValueError("unsupported plugin action")
        except Exception as exc:
            return _fail(exc)


    @specialized_tool()
    def sentra_skill(
        action: Literal["install", "list", "bind", "agent_skills"],
        ctx: Context,
        skill_id: str | None = None,
        name: str | None = None,
        version: str | None = None,
        content: str | None = None,
        source: str = "local",
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
        agent_id: str | None = None,
        priority: int = 100,
        enabled: bool = True,
        max_chars: int = 6000,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Install versioned skills and explicitly bind them to logical Agents."""
        try:
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            if action == "install":
                return _ok(control_plane.install_skill(
                    owner,
                    name=str(_required("name", name)),
                    version=str(_required("version", version)),
                    content=str(_required("content", content)),
                    source=source,
                    metadata=metadata,
                ))
            if action == "list":
                return _ok(control_plane.skill_list(owner))
            if action == "bind":
                return _ok(control_plane.skill_bind(
                    str(_required("skill_id", skill_id)),
                    owner,
                    run_id=str(_required("run_id", run_id)),
                    agent_id=str(_required("agent_id", agent_id)),
                    priority=priority,
                    enabled=enabled,
                ))
            if action == "agent_skills":
                return _ok(control_plane.agent_skills(
                    str(_required("run_id", run_id)),
                    owner,
                    agent_id=str(_required("agent_id", agent_id)),
                    max_chars=max_chars,
                ))
            raise ValueError("unsupported skill action")
        except Exception as exc:
            return _fail(exc)


    @specialized_tool()
    def sentra_routine(
        action: Literal["list", "bind", "enable", "disable", "fire", "tick"],
        ctx: Context,
        routine_id: str | None = None,
        authority_run_id: str | None = None,
        goal_id: str | None = None,
        source: str = "manual",
        now: float | None = None,
        enabled_only: bool = False,
        session_token: str | None = None,
    ) -> ResponseEnvelope:
        """Operate durable routines; imported routines require an explicit runtime bind."""
        try:
            owner = resolve_owner(ctx, session_token=session_token, require_session=True)
            if action == "list":
                return _ok(control_plane.routine_list(
                    owner, enabled_only=enabled_only
                ))
            if action == "bind":
                return _ok(control_plane.bind_routine(
                    str(_required("routine_id", routine_id)),
                    owner,
                    authority_run_id=str(_required("authority_run_id", authority_run_id)),
                    goal_id=goal_id,
                ))
            if action in {"enable", "disable"}:
                return _ok(control_plane.set_routine_enabled(
                    str(_required("routine_id", routine_id)),
                    owner,
                    enabled=action == "enable",
                ))
            if action == "fire":
                return _ok(control_plane.fire_routine(
                    str(_required("routine_id", routine_id)),
                    owner,
                    run_id=str(_required("authority_run_id", authority_run_id)),
                    goal_id=goal_id,
                    source=source,
                ))
            if action == "tick":
                return _ok(control_plane.tick_routines(now=now))
            raise ValueError("unsupported routine action")
        except Exception as exc:
            return _fail(exc)
