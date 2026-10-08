"""Generate OMA candidates without mutating or executing project code."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from orchestrator.agents.executor import ExecutorAgent
from orchestrator.agents.router import ModelRouter
from orchestrator.configuration import build_router, close_router
from orchestrator.models import Task
from workspace.paths import resolve_workspace_path
from workspace.sandbox import fingerprint, source_files

from ..audit import AuditLogger
from ..config import MCPConfig, PROJECT_ROOT
from .workspaces import WorkspaceRegistry


_ALLOWED_PROVIDERS = {"extension", "gemini_web", "local", "openai", "browser"}
_MAX_TARGET_FILES = 20
_MAX_FILE_CHARS = 200_000
_MAX_TOTAL_CHARS = 1_000_000
_MAX_CONTEXT_CHARS = 12_000


class CandidateGenerationService:
    """Produce a typed patch proposal while keeping the checkout read-only.

    This service deliberately does not validate, apply, promote, or execute the
    candidate. The project Integration Coordinator remains the only writer.
    """

    def __init__(
        self,
        config: MCPConfig,
        audit: AuditLogger,
        workspaces: WorkspaceRegistry,
    ) -> None:
        self.config = config
        self.audit = audit
        self.workspaces = workspaces

    def update_config(self, config: MCPConfig) -> None:
        self.config = config

    @staticmethod
    def _load_oma_config() -> dict[str, Any]:
        path = PROJECT_ROOT / "config.yaml"
        if not path.is_file():
            raise FileNotFoundError("OMA config.yaml is not installed")
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        if not isinstance(data, dict):
            raise ValueError("OMA configuration must be a mapping")
        return data

    @staticmethod
    def _task(payload: dict[str, Any]) -> Task:
        if not isinstance(payload, dict):
            raise TypeError("task must be an object")
        task = Task.from_dict(payload)
        if not task.id or len(task.id) > 80:
            raise ValueError("task.id must be 1..80 characters")
        if not task.run_id or len(task.run_id) > 120:
            raise ValueError("task.run_id must be 1..120 characters")
        if not task.objective or len(task.objective) > 20_000:
            raise ValueError("task.objective must be 1..20000 characters")
        if len(task.target_files) > _MAX_TARGET_FILES:
            raise ValueError(
                f"candidate generation accepts at most {_MAX_TARGET_FILES} target files"
            )
        if any(not isinstance(item, str) or not item.strip() for item in task.target_files):
            raise ValueError("task.target_files must contain non-empty strings")
        return task

    @staticmethod
    def _provider(value: str | None) -> str | None:
        if value is None:
            return None
        provider = str(value).strip().lower()
        if provider not in _ALLOWED_PROVIDERS:
            raise ValueError(
                "provider must be one of " + ",".join(sorted(_ALLOWED_PROVIDERS))
            )
        return provider

    @staticmethod
    def _target_contents(root: Path, task: Task) -> tuple[dict[str, str], dict[str, str | None]]:
        out: dict[str, str] = {}
        hashes: dict[str, str | None] = {}
        total = 0
        for relative in task.target_files:
            path = resolve_workspace_path(root, relative)
            if not path.exists():
                hashes[relative] = None
                continue
            if not path.is_file():
                raise ValueError(f"target file is not a regular file: {relative}")
            raw = path.read_bytes()
            if len(raw) > _MAX_FILE_CHARS * 4:
                raise ValueError(f"target file exceeds candidate context limit: {relative}")
            text = raw.decode("utf-8", errors="strict")
            if len(text) > _MAX_FILE_CHARS:
                raise ValueError(f"target file exceeds candidate context limit: {relative}")
            total += len(text)
            if total > _MAX_TOTAL_CHARS:
                raise ValueError("combined target-file context exceeds limit")
            out[relative] = text
            hashes[relative] = hashlib.sha256(raw).hexdigest()
        return out, hashes

    async def generate(
        self,
        owner: str,
        *,
        workspace: str | None,
        task: dict[str, Any],
        context_summary: str = "",
        provider: str | None = None,
    ) -> dict[str, Any]:
        view = self.workspaces.resolve(workspace, owner, "execute")
        root = Path(view["path"]).resolve(strict=True)
        item = self._task(task)
        summary = str(context_summary or "")
        if len(summary) > _MAX_CONTEXT_CHARS:
            raise ValueError(
                f"context_summary exceeds {_MAX_CONTEXT_CHARS} characters"
            )
        selected_provider = self._provider(provider)
        contents, target_hashes = self._target_contents(root, item)
        base_hash = fingerprint(source_files(root))
        config = self._load_oma_config()
        router: ModelRouter = build_router(
            config,
            worker=selected_provider,
            reviewer=selected_provider,
            mock=False,
            root=PROJECT_ROOT,
        )
        self.audit.emit(
            "oma.candidate_generate",
            "started",
            {
                "workspace_id": view.get("workspace_id"),
                "task_id": item.id,
                "run_id": item.run_id,
                "provider": selected_provider or router.primary_name,
                "target_files": list(item.target_files),
                "base_hash": base_hash,
            },
        )
        try:
            executor = ExecutorAgent(
                router,
                agent_id=f"candidate.remote.{selected_provider or router.primary_name}",
            )
            with router.repository_scope(root, lambda _entry: None):
                candidate = await executor.execute_task(
                    item,
                    context_summary=summary,
                    target_files_content=contents,
                )
            result = {
                "status": "CANDIDATE_READY",
                "candidate": candidate.to_dict(),
                "base_hash": base_hash,
                "target_hashes": target_hashes,
                "workspace_id": view.get("workspace_id"),
                "workspace_alias": view.get("alias"),
                "provider": selected_provider or router.primary_name,
                "source_unchanged": fingerprint(source_files(root)) == base_hash,
            }
            if not result["source_unchanged"]:
                raise RuntimeError(
                    "REMOTE_BASE_CHANGED: workspace changed during candidate generation"
                )
            self.audit.emit(
                "oma.candidate_generate",
                "ok",
                {
                    "workspace_id": view.get("workspace_id"),
                    "task_id": item.id,
                    "candidate_id": candidate.candidate_id,
                    "base_hash": base_hash,
                },
            )
            return result
        except Exception:
            self.audit.emit(
                "oma.candidate_generate",
                "failed",
                {
                    "workspace_id": view.get("workspace_id"),
                    "task_id": item.id,
                    "run_id": item.run_id,
                },
            )
            raise
        finally:
            await close_router(router)
