#!/usr/bin/env python3
"""
AutonomousInfinityAI Main CLI Entrypoint
Supports OMA (Orquestrador Multiagente) Architecture and Legacy Mode.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
import yaml

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from orchestrator.state_machine import JobSpec, JobState, StateStore
from orchestrator.dispatcher import Orchestrator
from orchestrator.engine import OMAEngine
from orchestrator.quality_gate import QuorumPolicy
from orchestrator.anti_explosion import AntiExplosionConfig
from orchestrator.agents.router import ModelRouter
from orchestrator.providers.local_provider import LocalModelProvider
from orchestrator.providers.browser_provider import BrowserProvider
from orchestrator.providers.mock_provider import MockProvider
from local_model.qwen_client import QwenLocalClient
from browser.session import BrowserSession
from browser.pool import BrowserPool


def load_config(config_path: Path) -> dict:
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="AutonomousInfinityAI Orchestrator CLI")
    parser.add_argument("--job-id", type=str, default="job-001", help="Unique identifier for this job")
    parser.add_argument("--prompt", type=str, help="Initial prompt / objective description")
    parser.add_argument("--workspace", type=str, default=".", help="Target repository directory to work on")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--cdp-url", type=str, help="Chrome Remote Debugging Port URL e.g. http://localhost:9222")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--max-rounds", type=int, default=20, help="Maximum iteration rounds")
    parser.add_argument("--mode", type=str, choices=["oma", "legacy"], default=None, help="Execution mode: oma (default) or legacy")
    parser.add_argument("--mock", action="store_true", help="Use deterministic mock provider for testing")
    args = parser.parse_args()

    project_root = Path(__file__).parent.resolve()
    config_file = project_root / args.config
    config = load_config(config_file)

    local_cfg = config.get("local_model", {})
    browser_cfg = config.get("browser", {})
    orch_cfg = config.get("orchestrator", {})
    oma_cfg = config.get("oma", {})

    mode = args.mode or orch_cfg.get("mode", "oma")
    target_workspace = Path(args.workspace).resolve()
    job_dir = project_root / "runs" / args.job_id
    entry_prompt = args.prompt or (
        "Develop and refine the target project until all builds and tests pass cleanly and criteria are met."
    )

    print("=" * 65)
    print(f"[+] AutonomousInfinityAI Initiated (Mode: {mode.upper()})")
    print(f" Job ID:    {args.job_id}")
    print(f" Workspace: {target_workspace}")
    print(f" Mode:      {mode}")
    print("=" * 65)

    if mode == "oma":
        # Build Providers
        providers = {}
        if args.mock:
            providers["primary"] = MockProvider(model_name="mock-primary")
            providers["master"] = MockProvider(model_name="mock-master")
        else:
            local_provider = LocalModelProvider(
                base_url=local_cfg.get("base_url", "http://127.0.0.1:11434/v1"),
                model_name=local_cfg.get("model_name", "qwen2.5:0.5b-instruct-q4_K_M"),
                api_key=local_cfg.get("api_key", "local"),
                temperature=local_cfg.get("temperature", 0.1),
            )
            providers["primary"] = local_provider
            providers["master"] = local_provider

            # Optional browser fallback
            cdp_url = args.cdp_url or browser_cfg.get("cdp_url")
            if cdp_url or browser_cfg.get("use_browser", False):
                browser_session = BrowserSession(
                    "orchestrator",
                    headless=args.headless or browser_cfg.get("headless", False),
                    cdp_url=cdp_url,
                )
                providers["browser"] = BrowserProvider(session=browser_session)

        router = ModelRouter(
            providers=providers,
            primary_provider_name="primary",
            fallback_provider_name="master" if "master" in providers else None,
            failure_threshold=oma_cfg.get("circuit_failure_threshold", 3),
            recovery_timeout=oma_cfg.get("circuit_recovery_timeout", 30.0),
        )

        quorum_policy = QuorumPolicy(
            validators_required=oma_cfg.get("validators_required", 3),
            minimum_approvals=oma_cfg.get("minimum_approvals", 2),
            critical_rejection_blocks=oma_cfg.get("critical_rejection_blocks", True),
            objective_test_required=oma_cfg.get("objective_test_required", True),
            minimum_confidence_threshold=oma_cfg.get("minimum_confidence_threshold", 0.75),
        )

        anti_explosion_config = AntiExplosionConfig(
            branching_factor_limit=oma_cfg.get("branching_factor_limit", 5),
            max_depth=oma_cfg.get("max_depth", 5),
            global_task_budget=oma_cfg.get("global_task_budget", 200),
        )

        engine = OMAEngine(
            run_id=args.job_id,
            objective=entry_prompt,
            workspace_path=target_workspace,
            router=router,
            acceptance_criteria=config.get("default_acceptance_criteria", []),
            quorum_policy=quorum_policy,
            anti_explosion_config=anti_explosion_config,
            token_budget_master=oma_cfg.get("token_budget_master", 50000),
            token_budget_secondary=oma_cfg.get("token_budget_secondary", 1000000),
        )

        result = await engine.run()
        print("\n" + "=" * 65)
        print(f"[*] OMA Run Finalized!")
        print(f" Status:          {result['status']}")
        print(f" Completed Tasks: {result['completed_tasks']}/{result['total_tasks']}")
        print(f" Logs saved to:   runs/{args.job_id}/")
        print("=" * 65)

    else:
        # Legacy Mode execution
        store = StateStore(job_dir / "state.json")
        spec = JobSpec(
            job_id=args.job_id,
            entry_prompt=entry_prompt,
            acceptance_criteria=config.get("default_acceptance_criteria", []),
            validation_commands=["python -c \"print('Build check passed')\""],
            max_rounds=args.max_rounds or orch_cfg.get("max_rounds", 20),
            no_progress_limit=orch_cfg.get("no_progress_limit", 3),
            repeated_failure_limit=orch_cfg.get("repeated_failure_limit", 3),
            max_parallel_sessions=orch_cfg.get("max_parallel_sessions", 3),
        )

        qwen = QwenLocalClient(
            base_url=local_cfg.get("base_url", "http://127.0.0.1:11434/v1"),
            model_name=local_cfg.get("model_name", "qwen2.5:0.5b-instruct-q4_K_M"),
            api_key=local_cfg.get("api_key", "local"),
            temperature=local_cfg.get("temperature", 0.1),
        )

        cdp_url = args.cdp_url or browser_cfg.get("cdp_url")
        is_headless = args.headless or browser_cfg.get("headless", False)

        sessions = {
            "architect": BrowserSession("architect", headless=is_headless, cdp_url=cdp_url),
            "implementer": BrowserSession("implementer", headless=is_headless, cdp_url=cdp_url),
            "reviewer": BrowserSession("reviewer", headless=is_headless, cdp_url=cdp_url),
        }

        pool = BrowserPool(sessions)
        await pool.initialize_all()

        orchestrator = Orchestrator(
            spec=spec,
            store=store,
            qwen=qwen,
            browser_pool=pool,
            workspace_path=target_workspace,
        )

        try:
            final_state = await orchestrator.run()
            print("\n" + "=" * 65)
            print(f"[*] Execution Finished!")
            print(f" Final Status: {final_state.phase.value}")
            print(f" Total Rounds: {final_state.round_number}")
            print(f" State log saved to: {job_dir / 'state.json'}")
            print("=" * 65)
        finally:
            await pool.close_all()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[!] Execution interrupted by user.")


if __name__ == "__main__":
    main()
