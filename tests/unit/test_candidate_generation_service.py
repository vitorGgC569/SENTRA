from __future__ import annotations

import asyncio

import pytest

from orchestrator.agents.router import ModelRouter
from orchestrator.providers.base import AgentResponse
from orchestrator.providers.mock_provider import MockProvider
from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import MCPConfig
from sentra_mcp.services import candidate as candidate_mod
from sentra_mcp.services.candidate import CandidateGenerationService
from workspace.sandbox import fingerprint, source_files


class Workspaces:
    def __init__(self, root):
        self.root = root
        self.calls = []

    def resolve(self, workspace, owner, permission):
        self.calls.append((workspace, owner, permission))
        if permission != "execute":
            raise AssertionError(permission)
        return {
            "workspace_id": "ws:test",
            "alias": "project",
            "path": str(self.root),
            "permissions": ["read", "execute"],
        }


def _router():
    def handler(request):
        assert request.role == "executor"
        return AgentResponse(
            content=(
                "BEGIN_RESULT\n"
                "STATUS: COMPLETE\n"
                "SUMMARY: remote candidate only\n"
                "PATCH:\n"
                "```diff\n"
                "--- /dev/null\n"
                "+++ b/generated.txt\n"
                "@@ -0,0 +1 @@\n"
                "+generated remotely\n"
                "```\n"
                "VALIDATION_COMMANDS:\n"
                "- [[TEST|all]]\n"
                "END_RESULT"
            ),
            success=True,
            model="mock",
        )
    provider = MockProvider(custom_handler=handler, model_name="mock")
    return ModelRouter(
        {"primary": provider, "master": provider},
        primary_provider_name="primary",
        fallback_provider_name="master",
    )


def test_candidate_generation_is_read_only_and_returns_base_hash(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    before = fingerprint(source_files(root))
    workspaces = Workspaces(root)
    service = CandidateGenerationService(
        MCPConfig(
            allowed_roots=(root,),
            audit_log=tmp_path / "audit.jsonl",
            state_root=tmp_path / "state",
        ),
        AuditLogger(tmp_path / "audit.jsonl"),
        workspaces,
    )
    router = _router()
    monkeypatch.setattr(candidate_mod, "build_router", lambda *a, **k: router)

    async def close(_router):
        return None

    monkeypatch.setattr(candidate_mod, "close_router", close)

    result = asyncio.run(service.generate(
        "owner",
        workspace="project",
        task={
            "id": "T-1",
            "run_id": "run-1",
            "objective": "create generated output",
            "target_files": ["app.py"],
        },
        context_summary="bounded shared context",
    ))

    assert result["status"] == "CANDIDATE_READY"
    assert result["base_hash"] == before
    assert result["source_unchanged"] is True
    assert result["candidate"]["task_id"] == "T-1"
    assert "generated.txt" in result["candidate"]["patch"]
    assert fingerprint(source_files(root)) == before
    assert workspaces.calls == [("project", "owner", "execute")]


def test_candidate_generation_rejects_private_or_oversized_scope(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / ".env").write_text("SECRET=x\n", encoding="utf-8")
    service = CandidateGenerationService(
        MCPConfig(
            allowed_roots=(root,),
            audit_log=tmp_path / "audit.jsonl",
            state_root=tmp_path / "state",
        ),
        AuditLogger(tmp_path / "audit.jsonl"),
        Workspaces(root),
    )

    with pytest.raises(PermissionError):
        asyncio.run(service.generate(
            "owner",
            workspace="project",
            task={
                "id": "T-1",
                "run_id": "run-1",
                "objective": "read private file",
                "target_files": [".env"],
            },
        ))

    with pytest.raises(ValueError, match="at most"):
        asyncio.run(service.generate(
            "owner",
            workspace="project",
            task={
                "id": "T-2",
                "run_id": "run-1",
                "objective": "too broad",
                "target_files": [f"f{i}.py" for i in range(21)],
            },
        ))
