"""Centrally authorized UTF-8 workspace files machine (never auto-granted).

Every operation travels through a configured Machine, bound WorkItem, policy
and durable physical-effect fence. Paths are relative to the host-owned root.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ._base import GuardedExecutor
from .rpa import AuthorizedPaths, OutputPathLock, atomic_output, digest, effect_checkpoint

FILE_CAPABILITIES = {
    "workspace:file.read": ("read", "stat"),
    "workspace:file.write": ("write", "edit"),
    "workspace:file.delete": ("delete",),
}


@dataclass(frozen=True)
class WorkspaceFilesBinding:
    capability_id: str
    paths: AuthorizedPaths
    actions: tuple[str, ...]
    timeout_seconds: float = 30.0
    max_file_bytes: int = 1_048_576

    def __post_init__(self):
        if (self.capability_id not in FILE_CAPABILITIES or
                tuple(self.actions) != FILE_CAPABILITIES[self.capability_id] or
                not self.paths.read_roots or not self.paths.write_roots or
                not 1 <= self.max_file_bytes <= 8_388_608):
            raise ValueError("invalid_scoped_workspace_file_binding")


class WorkspaceFilesExecutor(GuardedExecutor):
    kind = "workspace-files"

    def __init__(self, *, machine_id, owner_principal_id, bindings, policy):
        super().__init__(machine_id=machine_id, owner_principal_id=owner_principal_id,
                         bindings={binding.capability_id: binding for binding in bindings}, policy=policy)

    @staticmethod
    def _path(binding, raw, *, write):
        if not isinstance(raw, str) or not 1 <= len(raw) <= 512 or chr(0) in raw or ":" in raw:
            raise ValueError("relative_workspace_file_path_required")
        relative = raw.replace(chr(92), "/")
        if relative.startswith("/") or any(part in ("", ".", "..") for part in relative.split("/")):
            raise ValueError("relative_workspace_file_path_required")
        root = Path(binding.paths.read_roots[0])
        return binding.paths.resolve(str(root / relative), write=write)

    def _validate(self, request, binding):
        args = request.arguments
        action = args.get("action")
        if action not in binding.actions:
            raise ValueError("workspace_file_action_not_granted")
        fields = {"read": {"action", "path"}, "stat": {"action", "path"},
                  "write": {"action", "path", "content"},
                  "edit": {"action", "path", "content", "expected_sha256"},
                  "delete": {"action", "path", "expected_sha256"}}[action]
        if set(args) != fields:
            raise ValueError("workspace_file_argument_schema")
        is_write = action in {"write", "edit", "delete", "stat"}
        target = self._path(binding, args["path"], write=is_write)
        if action in {"read", "edit", "delete"} and (not target.is_file() or
                target.stat().st_size > binding.max_file_bytes):
            raise ValueError("workspace_file_missing_or_too_large")
        if action in {"write", "edit"}:
            content = args["content"]
            if not isinstance(content, str) or len(content.encode("utf-8")) > binding.max_file_bytes:
                raise ValueError("workspace_file_content_limit")
        if action in {"edit", "delete"}:
            expected = args["expected_sha256"]
            if (not isinstance(expected, str) or len(expected) != 64 or
                    any(char not in "0123456789abcdef" for char in expected)):
                raise ValueError("workspace_file_expected_digest_required")
        return {**dict(args), "absolute_path": str(target)}

    def _execute(self, binding, args):
        action, path = args["action"], args["absolute_path"]
        if action == "stat":
            target = self._path(binding, args["path"], write=True)
            if not target.is_file():
                return {"path": args["path"], "exists": False}
            if target.stat().st_size > binding.max_file_bytes:
                raise ValueError("workspace_file_size_limit")
            return {"path": args["path"], "exists": True,
                    "bytes": target.stat().st_size, "sha256": digest(target)}
        if action == "read":
            target = self._path(binding, args["path"], write=False)
            content = target.read_text(encoding="utf-8", errors="strict")
            if len(content.encode("utf-8")) > binding.max_file_bytes:
                raise ValueError("workspace_file_size_limit")
            return {"path": args["path"], "content": content,
                    "sha256": digest(target), "bytes": target.stat().st_size}
        if action in {"write", "edit"}:
            encoded = args["content"].encode("utf-8")
            def producer(temp):
                if action == "edit":
                    target = self._path(binding, args["path"], write=False)
                    if digest(target) != args["expected_sha256"]:
                        raise ValueError("workspace_file_revision_conflict")
                effect_checkpoint()
                temp.write_bytes(encoded)
            def verify(temp):
                if hashlib.sha256(temp.read_bytes()).digest() != hashlib.sha256(encoded).digest():
                    raise ValueError("workspace_file_verification_failed")
            result = atomic_output(binding.paths, path, producer, verify,
                overwrite=action == "edit", max_output_bytes=binding.max_file_bytes)
            return {"path": args["path"], "action": action, "exists": True,
                    "sha256": result["sha256"], "bytes": result["bytes"],
                    "artifact_id": result.get("artifact_id"), "durable_capture": result.get("durable_capture", False)}
        target = self._path(binding, args["path"], write=True)
        with OutputPathLock(target, timeout_seconds=10):
            target = self._path(binding, args["path"], write=False)
            if digest(target) != args["expected_sha256"]:
                raise ValueError("workspace_file_revision_conflict")
            effect_checkpoint()
            target.unlink()
            return {"path": args["path"], "action": "delete", "exists": target.exists(),
                    "deleted_sha256": args["expected_sha256"]}


def declare_workspace_files_machine(*, machine_id, owner_principal_id, bindings, policy):
    from sentra_runtime.contracts import Capability, Machine
    from .discovery import MachineDeclaration
    executor = WorkspaceFilesExecutor(machine_id=machine_id,
        owner_principal_id=owner_principal_id, bindings=bindings, policy=policy)
    capabilities = tuple(Capability(binding.capability_id,
        "Explicit, bounded UTF-8 file access inside one workspace", "high")
        for binding in bindings)
    return MachineDeclaration(Machine(machine_id, executor.kind, owner_principal_id, capabilities), executor)
