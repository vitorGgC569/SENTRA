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
from .paths import PathAccessError, resolve_workspace_path


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


MAX_PATCH_BYTES = 1_000_000
MAX_COMMAND_BYTES = 10_000
MAX_IDEMPOTENCY_KEY_LEN = 128
_SECRET_PATTERNS = ("sk-", "api_key", "apikey", "secret", "password", "passwd", "token=")


def _validate_idempotency_key(key: Optional[str]) -> None:
    if key is None:
        return
    import re as _re

    if len(key) > MAX_IDEMPOTENCY_KEY_LEN or not _re.fullmatch(r"[A-Za-z0-9_\-.:]+", key):
        raise SecurityPolicyError(f"Invalid idempotency key: {key!r}")


class ToolGateway:
    """
    Controlled Tool Gateway with Least Privilege, Permission Enforcement,
    Idempotency Key Tracking, and Prompt Injection Defense as specified in
    Sections 51-55 and 63 of OMA.
    """

    def __init__(self, workspace_path: Path, *, execution=None, profiles=None):
        self.workspace_path = Path(workspace_path).resolve()
        from .docker_runner import create_runner
        self.cmd_runner = create_runner(self.workspace_path, profiles, execution)
        self.git_manager = GitManager(self.workspace_path)
        self._idempotency_cache: Dict[str, Any] = {}
        self._execution_audit_log: List[Dict[str, Any]] = []

    def check_permission(self, role: str, permission: Permission) -> None:
        allowed = ROLE_PERMISSIONS.get(role.lower(), set())
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

    def assert_no_secrets(self, *texts: str) -> None:
        """Fail closed if a prompt/tool payload appears to carry credentials."""
        for t in texts:
            low = (t or "").lower()
            for pat in _SECRET_PATTERNS:
                if pat in low:
                    raise SecurityPolicyError(
                        f"Payload blocked: possible secret leakage pattern '{pat}'"
                    )

    async def execute_patch(
        self,
        role: str,
        patch_text: str,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.check_permission(role, Permission.APPLY_PATCH)
        _validate_idempotency_key(idempotency_key)
        if len(patch_text or "") > MAX_PATCH_BYTES:
            raise SecurityPolicyError(
                f"Oversized patch blocked ({len(patch_text)} > {MAX_PATCH_BYTES} bytes)"
            )

        cache_key = (role, "PATCH", idempotency_key)
        digest = hashlib.sha256(patch_text.encode("utf-8")).hexdigest()
        if idempotency_key and cache_key in self._idempotency_cache:
            before_digest, before_result = self._idempotency_cache[cache_key]
            if digest != before_digest:
                raise SecurityPolicyError("Idempotency key reused with different patch")
            return before_result

        res = PatchManager.apply_patch(self.workspace_path, patch_text)

        self._execution_audit_log.append({
            "action": "APPLY_PATCH",
            "role": role,
            "success": res.get("success", False),
            "idempotency_key": idempotency_key,
            "timestamp": time.time(),
        })

        if idempotency_key:
            self._idempotency_cache[cache_key] = (digest, res)

        return res

    async def run_validation_command(
        self,
        role: str,
        command: str,
        timeout: int = 120,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.check_permission(role, Permission.RUN_COMMANDS)
        _validate_idempotency_key(idempotency_key)
        if len(command or "") > MAX_COMMAND_BYTES:
            raise SecurityPolicyError(
                f"Oversized command blocked ({len(command)} > {MAX_COMMAND_BYTES} bytes)"
            )
        if "\x00" in (command or ""):
            raise SecurityPolicyError("Command blocked: null byte injection")

        cache_key = (role, "VALIDATE", idempotency_key)
        digest = hashlib.sha256(command.encode("utf-8")).hexdigest()
        if idempotency_key and cache_key in self._idempotency_cache:
            before_digest, before_result = self._idempotency_cache[cache_key]
            if digest != before_digest:
                raise SecurityPolicyError("Idempotency key reused with different command")
            return before_result

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
            self._idempotency_cache[cache_key] = (digest, res)

        return res

    async def read_file(self, role: str, rel_path: str) -> str:
        self.check_permission(role, Permission.READ_WORKSPACE)
        try:
            target = resolve_workspace_path(self.workspace_path, rel_path)
        except PathAccessError as exc:
            raise SecurityPolicyError(f"Path traversal detected: {rel_path}: {exc}") from exc

        if not target.exists() or not target.is_file():
            return ""

        raw_content = target.read_text(encoding="utf-8", errors="replace")
        return raw_content

    async def commit(self, role: str, message: str) -> bool:
        self.check_permission(role, Permission.GIT_COMMIT)
        return await self.git_manager.commit_result(message)
