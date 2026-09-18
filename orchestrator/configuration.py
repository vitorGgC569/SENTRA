"""Operator-owned settings and explicit provider routing for the operational CLI."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from .agents.router import ModelRouter
from .anti_explosion import AntiExplosionConfig
from .quality_gate import QuorumPolicy


DEFAULT_BOT_PROFILE_DIR = "browser_profiles/edge-bot"
DEFAULT_LAUNCH_FLAGS: List[str] = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]


def browser_bot_settings(browser_cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Validate ``browser.bot_profile_dir / launch_flags / bot_headless``.

    Returns ``{"bot_profile_dir", "launch_flags", "bot_headless"}`` with
    defaults applied. Raises ``ValueError`` mentioning the offending key.
    """
    cfg = browser_cfg or {}
    if not isinstance(cfg, dict):
        raise ValueError("browser must be a mapping")
    bot_profile_dir = cfg.get("bot_profile_dir", DEFAULT_BOT_PROFILE_DIR)
    launch_flags = cfg.get("launch_flags", list(DEFAULT_LAUNCH_FLAGS))
    bot_headless = cfg.get("bot_headless", False)

    if not isinstance(bot_profile_dir, str) or not bot_profile_dir.strip():
        raise ValueError("browser.bot_profile_dir must be a nonempty path string")
    profile = os.path.expandvars(os.path.expanduser(bot_profile_dir.strip()))
    if len(profile) > 500:
        raise ValueError("browser.bot_profile_dir must be <= 500 characters")
    if any(c in profile for c in ("\n", "\r", "\x00")):
        raise ValueError("browser.bot_profile_dir must not contain control characters")
    parsed = Path(profile)
    # Caminhos absolutos sao permitidos (ex.: perfil fora do OneDrive);
    # o que continua proibido e OneDrive, traversal ".." e controles.
    if "onedrive" in profile.lower():
        raise ValueError("browser.bot_profile_dir must not point inside OneDrive")
    if ".." in parsed.parts:
        raise ValueError("browser.bot_profile_dir must not contain parent traversal '..'")

    if launch_flags is None:
        launch_flags = list(DEFAULT_LAUNCH_FLAGS)
    if not isinstance(launch_flags, list):
        raise ValueError("browser.launch_flags must be a list of Chromium flags")
    if len(launch_flags) > 32:
        raise ValueError("browser.launch_flags must contain at most 32 flags")
    cleaned: List[str] = []
    for flag in launch_flags:
        if (not isinstance(flag, str) or not flag.startswith("--")
                or not 3 <= len(flag) <= 200):
            raise ValueError("browser.launch_flags entries must be strings starting with '--' (3..200 chars)")
        if any(c in flag for c in ("\n", "\r", "\x00")):
            raise ValueError("browser.launch_flags entries must not contain control characters")
        cleaned.append(flag)

    if not isinstance(bot_headless, bool):
        raise ValueError("browser.bot_headless must be a boolean")
    return {"bot_profile_dir": profile, "launch_flags": cleaned, "bot_headless": bot_headless}


def build_router(config, *, worker=None, reviewer=None, mock=False, root=None):
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
    if "browser" in selected:
        # Fail fast even in --demo: invalid bot config never becomes a live default.
        browser_bot_settings(config.get("browser", {}) or {})
    providers = {}
    for name in selected:
        if name not in {"local", "extension", "openai", "browser"}:
            raise ValueError(f"unknown provider '{name}'; choose local, extension, openai or browser")
        if mock:
            from .providers.mock_provider import MockProvider
            providers[name] = MockProvider(model_name="scripted-demo-" + name)
        elif name == "browser":
            from .providers.browser_provider import BrowserProvider
            from browser.bot_profile import (
                get_bot_headless,
                get_browser_channel,
                get_storage_state_path,
                resolve_bot_profile_dir,
            )
            from browser.session import BrowserSession
            from browser.pool import BrowserPool
            bcfg = browser_bot_settings(config.get("browser", {}) or {})
            base = Path(root).resolve() if root is not None else Path.cwd()
            profile_dir = resolve_bot_profile_dir(config, base)
            storage = get_storage_state_path(config, base)
            session = BrowserSession(
                role="worker",
                headless=bcfg["bot_headless"],
                storage_state_path=str(storage) if storage else None,
                browser_channel=get_browser_channel(config),
                user_data_dir=str(profile_dir),
                target_url=(config.get("browser", {}) or {}).get("target_url", "https://chatgpt.com"),
                launch_args=bcfg["launch_flags"],
            )
            providers[name] = BrowserProvider(
                pool=BrowserPool({"worker": session}),
                bot_profile_dir=str(profile_dir),
                launch_flags=bcfg["launch_flags"],
                bot_headless=bcfg["bot_headless"],
            )
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
        pool = getattr(provider, "pool", None)
        if pool is not None and hasattr(pool, "close_all"):
            try:
                await pool.close_all()
            except Exception:
                pass
        else:
            session = getattr(provider, "session", None)
            if session is not None and hasattr(session, "close"):
                try:
                    await session.close()
                except Exception:
                    pass
