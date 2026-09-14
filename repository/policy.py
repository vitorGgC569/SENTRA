"""PolicyEngine — quem pode o quê; PROTECTED_COMPONENTS exigem validação forte/aprovação."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Set

from .parser import Directive

# Componentes que NUNCA se autopromovem sem validação forte/aprovação externa
PROTECTED_COMPONENTS = {
    "orchestrator/master_queue.py", "orchestrator/central_exchange.py", "orchestrator/scale_gates.py",
    "orchestrator/agents/contracts.py", "orchestrator/agents/master.py", "orchestrator/agents/validators.py",
    "orchestrator/providers/openai_provider.py", "scripts/calibrate_quality.py",
    "repository/policy.py",
    "repository/gateway.py",
    "repository/registry.py",
    "workspace/tool_gateway.py",
    "orchestrator/queue.py",
    "self_improvement/promotion.py",
    "self_improvement/engine.py",
    "config.yaml",
    "repository/session.py", "repository/parser.py", "repository/transactions.py",
    "repository/result_store.py", "workspace/paths.py", "workspace/command_runner.py",
    "workspace/patch_manager.py", "workspace/git_manager.py", "self_improvement/sandbox.py",
    "self_improvement/evaluator.py", "orchestrator/engine.py", "orchestrator/quality_gate.py",
    "orchestrator/anti_explosion.py", "orchestrator/agents/router.py",
    "orchestrator/conversation_pool.py", "orchestrator/compute_policy.py",
    "orchestrator/providers/extension_provider.py", "repository/agent_loop.py",
    "browser/outcomes.py",
    "native_bridge/relay.py", "native_bridge/protocol.py",
    "native_bridge/settings.py", "native_bridge/job_store.py", "main.py",
    "orchestrator/runtime.py", "orchestrator/configuration.py", "orchestrator/budgets.py",
    "orchestrator/verification.py", "workspace/sandbox.py", "workspace/docker_runner.py",
    "sandbox_runtime/Dockerfile", "sandbox_runtime/requirements.txt", "scripts/prepare_docker.py",
    "scripts/prepare_self_improvement.py", "self_improvement/fixtures/prompt_integrity.test.cjs",
}

ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "read_only": {"R", "S", "T", "SYM", "STATUS", "DIFF", "GIT_STATUS", "GIT_DIFF", "NEXT", "RART"},
    "planner": {"R", "S", "T", "SYM", "STATUS", "DIFF", "GIT_STATUS", "GIT_DIFF", "NEXT", "RART"},
    "executor": {"R", "S", "T", "SYM", "PATCH", "TEST", "DIFF", "STATUS", "BRANCH",
                 "CHECKPOINT", "NEXT", "RART", "GIT_STATUS", "GIT_DIFF", "LINT", "BUILD", "TYPECHECK"},
    "validator": {"R", "S", "T", "SYM", "TEST", "DIFF", "STATUS", "NEXT", "RART",
                  "GIT_STATUS", "GIT_DIFF", "LINT", "TYPECHECK"},
    "critic": {"R", "S", "T", "SYM", "TEST", "DIFF", "STATUS", "NEXT", "RART",
               "GIT_STATUS", "GIT_DIFF", "LINT", "TYPECHECK"},
    "repair": {"R", "S", "T", "SYM", "PATCH", "TEST", "DIFF", "STATUS", "CHECKPOINT",
               "ROLLBACK", "NEXT", "RART", "GIT_STATUS", "GIT_DIFF", "LINT"},
    "master": {"R", "S", "T", "SYM", "PATCH", "W", "TEST", "DIFF", "STATUS", "BRANCH",
               "CHECKPOINT", "ROLLBACK", "NEXT", "RART", "GIT_STATUS", "GIT_DIFF",
               "LINT", "BUILD", "TYPECHECK"},
    "judge": {"R", "S", "T", "SYM", "STATUS", "DIFF", "NEXT", "RART"},
}


class PolicyDenied(PermissionError):
    pass


@dataclass
class PolicyEngine:
    require_external_approval_for_protected: bool = True
    raw_command_allowed: bool = False  # RUN_RAW desligado por padrão

    def validate(self, role: str, directive: Directive, targets_protected: bool = False,
                 session=None) -> None:
        if not directive.known:
            raise PolicyDenied(f"UNKNOWN_OPERATION: {directive.operation}")
        if directive.operation == "RUN_RAW" or directive.operation.startswith("DELETE"):
            raise PolicyDenied(f"RAW/privileged operation blocked: {directive.operation}")
        allowed = ROLE_PERMISSIONS.get(role.lower(), set())
        if directive.operation not in allowed:
            raise PolicyDenied(f"role '{role}' not authorized for '{directive.operation}'")
        if session is not None:
            writes = {"PATCH", "W", "BRANCH", "CHECKPOINT", "ROLLBACK"}
            runs = {"TEST", "LINT", "TYPECHECK", "BUILD"}
            permission = (session.write_permissions if directive.operation in writes else
                          session.run_permissions if directive.operation in runs else session.read_permissions)
            if not permission:
                raise PolicyDenied(f"session not authorized for '{directive.operation}'")
        if directive.operation == "W" and role.lower() != "master":
            raise PolicyDenied("full-file WRITE restricted to master")
        if targets_protected and self.require_external_approval_for_protected:
            # Não bloqueia a criação do candidato em sandbox; bloqueia a PROMOÇÃO.
            # O gateway marca needs_external_approval=True e promotion.py decide.
            return None
