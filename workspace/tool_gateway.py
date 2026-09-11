from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .command_runner import CommandRunner
from .git_manager import GitManager
from .patch_manager import PatchManager


class Permission(str, Enum):
    READ_WORKSPACE = "READ_WORKSPACE"
    APPLY_PATCH = "APPLY_PATCH"
    RUN_COMMANDS = "RUN_COMMANDS"
    GIT_COMMIT = "GIT_COMMIT"
    NETWORK_ACCESS = "NETWORK_ACCESS"


ROLE_PERMISSIONS: Dict[str, Set[Permission]] = {
    "executor": {Permission.READ_WORKSPACE, Permission.APPLY_PATCH, Permission.RUN_COMMANDS},
    "validator": {Permission.READ_WORKSPACE, Permission.RUN_COMMANDS},
    "repair": {Permission.READ_WORKSPACE, Permission.APPLY_PATCH, Permission.RUN_COMMANDS},
    "master": {Permission.READ_WORKSPACE, Permission.APPLY_PATCH, Permission.GIT_COMMIT, Permission.RUN_COMMANDS},
    "planner": {Permission.READ_WORKSPACE},
    "judge": {Permission.READ_WORKSPACE},
    "read_only": {Permission.READ_WORKSPACE},
}


class SecurityPolicyError(PermissionError):
    """Raised when an agent attempts an unauthorized tool operation."""
    pass


class ToolGateway:
    """
    Controlled Tool Gateway with Least Privilege, Permission Enforcement,
    Idempotency Key Tracking, and Prompt Injection Defense as specified in
    Sections 51-55 and 63 of OMA.
    """

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path).resolve()
        self.cmd_runner = CommandRunner(self.workspace_path)
        self.git_manager = GitManager(self.workspace_path)
        self._idempotency_cache: Dict[str, Any] = {}
        self._execution_audit_log: List[Dict[str, Any]] = []

    def check_permission(self, role: str, permission: Permission) -> None:
        allowed = ROLE_PERMISSIONS.get(role.lower(), {Permission.READ_WORKSPACE})
        if permission not in allowed:
            raise SecurityPolicyError(
                f"Role '{role}' is not authorized for permission '{permission.value}'"
            )

    def sanitize_untrusted_data(self, content: str) -> str:
        """
        Protects against prompt injection by tagging external untrusted content
        strictly as DATA rather than INSTRUCTIONS (Section 55).
        """
        safe = content.replace("```", "'''")
        return f"\n<UNTRUSTED_EXTERNAL_DATA>\n{safe}\n</UNTRUSTED_EXTERNAL_DATA>\n"

    async def execute_patch(
        self,
        role: str,
        patch_text: str,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.check_permission(role, Permission.APPLY_PATCH)

        if idempotency_key and idempotency_key in self._idempotency_cache:
            return self._idempotency_cache[idempotency_key]

        res = PatchManager.apply_patch(self.workspace_path, patch_text)

        self._execution_audit_log.append({
            "action": "APPLY_PATCH",
            "role": role,
            "success": res.get("success", False),
            "idempotency_key": idempotency_key,
            "timestamp": time.time(),
        })

        if idempotency_key:
            self._idempotency_cache[idempotency_key] = res

        return res

    async def run_validation_command(
        self,
        role: str,
        command: str,
        timeout: int = 120,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.check_permission(role, Permission.RUN_COMMANDS)

        if idempotency_key and idempotency_key in self._idempotency_cache:
            return self._idempotency_cache[idempotency_key]

        res = await self.cmd_runner.run_command(command, timeout=timeout)

        self._execution_audit_log.append({
            "action": "RUN_COMMAND",
            "role": role,
            "command": command,
            "passed": res.get("passed", False),
            "idempotency_key": idempotency_key,
            "timestamp": time.time(),
        })

        if idempotency_key:
            self._idempotency_cache[idempotency_key] = res

        return res

    async def read_file(self, role: str, rel_path: str) -> str:
        self.check_permission(role, Permission.READ_WORKSPACE)
        target = (self.workspace_path / rel_path).resolve()

        # Prevent path traversal attacks
        if not str(target).startswith(str(self.workspace_path)):
            raise SecurityPolicyError(f"Path traversal detected: {rel_path}")

        if not target.exists() or not target.is_file():
            return ""

        raw_content = target.read_text(encoding="utf-8", errors="replace")
        return raw_content

    async def commit(self, role: str, message: str) -> bool:
        self.check_permission(role, Permission.GIT_COMMIT)
        return await self.git_manager.commit_result(message)
