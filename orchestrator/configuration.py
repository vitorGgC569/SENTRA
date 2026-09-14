"""Operator-owned settings and explicit provider routing for the operational CLI."""
from __future__ import annotations

import os

from .agents.router import ModelRouter
from .anti_explosion import AntiExplosionConfig
from .quality_gate import QuorumPolicy


def build_router(config, *, worker=None, reviewer=None, mock=False):
    oma = config.get("oma", {})
    routing = config.get("routing", {})
    worker = worker or routing.get("worker", "extension")
    reviewer = reviewer or routing.get("reviewer", worker)
    fallback = routing.get("fallback")
    selected = {worker, reviewer} | ({fallback} if fallback else set())
    routes = routing.get("roles", {})
    if not isinstance(routes, dict):
        raise ValueError("routing.roles must be a mapping")
    selected.update(routes.values())
    providers = {}
    for name in selected:
        if name not in {"local", "extension", "openai"}:
            raise ValueError(f"unknown provider '{name}'; choose local, extension or openai")
        if mock:
            from .providers.mock_provider import MockProvider
            providers[name] = MockProvider(model_name="scripted-demo-" + name)
        elif name == "openai":
            from .providers.openai_provider import OpenAIProvider
            providers[name] = OpenAIProvider(routing.get("openai_model"),
                os.environ.get(routing.get("openai_key_env", "OPENAI_API_KEY")))
        elif name == "local":
            from .providers.local_provider import LocalModelProvider
            cfg = config.get("local_model", {})
            providers[name] = LocalModelProvider(
                base_url=cfg.get("base_url", "http://127.0.0.1:11434/v1"),
                model_name=cfg.get("model_name", "qwen2.5:0.5b-instruct-q4_K_M"),
                api_key=os.environ.get(cfg.get("api_key_env", "OMA_LOCAL_API_KEY"), cfg.get("api_key", "local")),
                temperature=cfg.get("temperature", .1))
        else:
            from .providers.extension_provider import BrowserExtensionProvider
            providers[name] = BrowserExtensionProvider(config.get("browser", {}).get("relay_base", "http://127.0.0.1:8765"))
    providers["master"] = providers[reviewer]
    router = ModelRouter(providers, primary_provider_name=worker, fallback_provider_name=fallback,
                         failure_threshold=oma.get("circuit_failure_threshold",3),
                         recovery_timeout=oma.get("circuit_recovery_timeout",30))
    router.role_routes = routes
    router.request_timeout = config.get("browser", {}).get("timeout_seconds",300)
    router.max_output_tokens = oma.get("max_output_tokens",4096)
    router.max_inflight_requests = oma.get("max_inflight_requests",2)
    if not 1 <= router.max_inflight_requests <= 8:
        raise ValueError("oma.max_inflight_requests must be 1..8")
    if not 5 <= router.request_timeout <= 900 or not 1 <= router.max_output_tokens <= 16000:
        raise ValueError("invalid provider timeout or output-token limit")
    return router


def _release_score(oma) -> float:
    value = oma.get("min_release_score", 9.5)
    if type(value) not in (int, float) or not 0 <= value <= 10:
        raise ValueError("oma.min_release_score must be 0..10 (default 9.5: critics release exec only at/above)")
    return float(value)


def engine_options(config, max_rounds=None, workers=None):
    from workspace.docker_runner import settings
    from .compute_policy import from_config as compute_policy_from_config
    oma, orch = config.get("oma", {}), config.get("orchestrator", {})
    validation = config.get("validation", {})
    commands = validation.get("commands", ["[[TEST|all]]"])
    profiles = validation.get("profiles", {})
    allowed_paths = validation.get("allowed_patch_paths")
    if allowed_paths is not None and (not isinstance(allowed_paths, list) or
                                      any(not isinstance(p, str) for p in allowed_paths)):
        raise ValueError("allowed_patch_paths must be a list of exact repository-relative file paths")
    if not 1 <= validation.get("timeout_seconds",120) <= 3600:
        raise ValueError("validation timeout must be 1..3600 seconds")
    if type(oma.get("max_repair_rounds",15)) is not int or not 0 <= oma.get("max_repair_rounds",15) <= 20:
        raise ValueError("max_repair_rounds must be 0..20")
    stagnation_limit = oma.get("stagnation_limit", 5)
    if type(stagnation_limit) is not int or not 1 <= stagnation_limit <= 20:
        raise ValueError("oma.stagnation_limit must be an int 1..20 (identical rejections before STAGNANT escalation)")
    if not isinstance(commands, list) or not commands or any(not isinstance(c, str) for c in commands):
        raise ValueError("validation.commands must be a nonempty list of directives")
    delay = oma.get("inter_call_delay_s", 0)
    if not isinstance(delay, (int, float)) or not 0 <= delay <= 600:
        raise ValueError("oma.inter_call_delay_s must be 0..600 seconds")
    if not isinstance(oma.get("fixed_conversations", False), bool):
        raise ValueError("oma.fixed_conversations must be a boolean")
    max_seats = oma.get("max_seats", 8)
    if type(max_seats) is not int or not 1 <= max_seats <= 8:
        raise ValueError("oma.max_seats must be an int 1..8 (chat-creation cap; 5 = master+executor+3 validators)")
    transient_max_retries = oma.get("transient_max_retries", 3)
    if type(transient_max_retries) is not int or not 0 <= transient_max_retries <= 10:
        raise ValueError("oma.transient_max_retries must be an int 0..10 (transient delivery retries before isolated failure)")
    transient_backoff = oma.get("transient_backoff_base_s", 30.0)
    if not isinstance(transient_backoff, (int, float)) or not 0 <= float(transient_backoff) <= 600:
        raise ValueError("oma.transient_backoff_base_s must be 0..600 seconds (exponential backoff base for transient retries)")
    if not isinstance(profiles, dict) or any(not isinstance(argv, list) or not argv or
            any(not isinstance(arg, str) or not arg for arg in argv) for argv in profiles.values()):
        raise ValueError("validation.profiles must map names to nonempty argv lists (never shell strings)")
    return {
        "acceptance_criteria": config.get("default_acceptance_criteria", []),
        "validation_commands": commands, "command_profiles": profiles,
        "test_timeout": validation.get("timeout_seconds",120),
        "execution": settings(validation.get("execution")),
        "allowed_patch_paths": allowed_paths,
        "max_parallel_workers": workers or orch.get("max_parallel_sessions",1),
        "max_rounds": max_rounds or orch.get("max_rounds",20),
        "no_progress_limit": orch.get("no_progress_limit",3),
        "max_repair_rounds": oma.get("max_repair_rounds",15),
        "stagnation_limit": stagnation_limit,
        "task_token_budget": oma.get("task_token_budget",120000),
        "token_budget_master": oma.get("token_budget_master",50000),
        "token_budget_secondary": oma.get("token_budget_secondary",1000000),
        "quorum_policy": QuorumPolicy(validators_required=oma.get("validators_required",3),
            minimum_approvals=oma.get("minimum_approvals",2), objective_test_required=True,
            critical_rejection_blocks=True, minimum_confidence_threshold=oma.get("minimum_confidence_threshold",.75),
            min_release_score=_release_score(oma), require_explicit_scores=True),
        "anti_explosion_config": AntiExplosionConfig(global_task_budget=oma.get("global_task_budget",200),
            branching_factor_limit=oma.get("branching_factor_limit",5), max_depth=oma.get("max_depth",5)),
        "compute_policy": compute_policy_from_config(oma.get("compute_policy")),
        "fixed_conversations": bool(oma.get("fixed_conversations", False)),
        "inter_call_delay_s": float(delay),
        "max_seats": max_seats,
        "transient_max_retries": transient_max_retries,
        "transient_backoff_base_s": float(transient_backoff),
    }


async def close_router(router):
    seen = set()
    for provider in router.providers.values():
        if id(provider) in seen:
            continue
        seen.add(id(provider))
        client = getattr(provider, "client", None)
        if client is not None:
            await client.close()
