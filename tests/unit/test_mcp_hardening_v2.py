from __future__ import annotations

import asyncio
import base64
import json
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import MCPConfig
from sentra_mcp.identity import request_identity
from sentra_mcp.services.browser import BrowserControlService
from sentra_mcp.services.documents import DocumentService
from sentra_mcp.services.filesystem import FilesystemService
from sentra_mcp.services.jobs import JobService
from sentra_mcp.services.process import ProcessService
from sentra_mcp.services.research import ResearchService
from sentra_mcp.services.workspaces import WorkspaceRegistry


def _config(root: Path, **kwargs) -> MCPConfig:
    return MCPConfig(
        allowed_roots=(root,),
        audit_log=root / ".sentra" / "audit.jsonl",
        remote_store_path=root / ".sentra" / "remote.sqlite3",
        **kwargs,
    )


def _approve_add(
    registry: WorkspaceRegistry,
    *,
    path: Path,
    owner: str,
    alias: str,
    permissions: tuple[str, ...],
    lifetime: str,
) -> dict:
    requested = registry.request_add(
        path=str(path),
        owner=owner,
        alias=alias,
        permissions=permissions,
        lifetime=lifetime,
    )
    assert requested["already_allowed"] is False
    registry.approve_local(requested["request_id"])
    return registry.resolve(alias, owner, "read")


def test_workspace_registry_permissions_lifetimes_upgrade_nested_and_remove(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    research = tmp_path / "research"
    nested = research / "nested"
    session_only = tmp_path / "session-only"
    primary.mkdir()
    research.mkdir()
    nested.mkdir()
    session_only.mkdir()

    clock = [1_000_000.0]
    config = _config(primary)
    registry = WorkspaceRegistry(
        config,
        AuditLogger(config.audit_log),
        state_path=primary / ".sentra" / "workspaces.json",
        clock=lambda: clock[0],
    )

    read_view = _approve_add(
        registry,
        path=research,
        owner="mcp:A",
        alias="research",
        permissions=("read",),
        lifetime="24h",
    )
    assert read_view["permissions"] == ["read"]
    assert registry.resolve("research", "mcp:B", "read")["alias"] == "research"
    with pytest.raises(PermissionError, match="does not grant write"):
        registry.resolve("research", "mcp:A", "write")

    # Upgrade same path/alias and lifetime after local approval; stable workspace_id.
    old_id = read_view["workspace_id"]
    upgrade = registry.request_add(
        path=str(research),
        owner="mcp:A",
        alias="research",
        permissions=("read", "write", "execute"),
        lifetime="permanent",
    )
    assert upgrade["already_allowed"] is False
    registry.approve_local(upgrade["request_id"])
    upgraded = registry.resolve("research", "mcp:B", "execute")
    assert upgraded["workspace_id"] == old_id
    assert set(upgraded["permissions"]) == {"read", "write", "execute"}
    assert upgraded["scope"] == "permanent"

    # Most-specific nested root wins for absolute path resolution.
    nested_request = registry.request_add(
        path=str(nested),
        owner="mcp:A",
        alias="nested-read",
        permissions=("read",),
        lifetime="permanent",
    )
    registry.approve_local(nested_request["request_id"])
    nested_view = registry.resolve_path(nested / "file.txt", "mcp:A", "read")
    assert nested_view["alias"] == "nested-read"

    # Session grants are invisible to a different MCP session.
    session_req = registry.request_add(
        path=str(session_only),
        owner="mcp:A",
        alias="session-research",
        permissions=("read",),
        lifetime="session",
    )
    registry.approve_local(session_req["request_id"])
    assert registry.resolve("session-research", "mcp:A", "read")["scope"] == "session"
    with pytest.raises(PermissionError):
        registry.resolve("session-research", "mcp:B", "read")

    # TTL grant expires without mutating the persistent registry.
    ttl_dir = tmp_path / "ttl"
    ttl_dir.mkdir()
    ttl_req = registry.request_add(
        path=str(ttl_dir),
        owner="mcp:A",
        alias="ttl",
        permissions=("read",),
        lifetime="1m",
    )
    registry.approve_local(ttl_req["request_id"])
    assert registry.resolve("ttl", "mcp:A", "read")["alias"] == "ttl"
    clock[0] += 61
    with pytest.raises(PermissionError):
        registry.resolve("ttl", "mcp:A", "read")

    # Removal is also request -> local approval and configured root cannot be removed.
    remove = registry.request_remove("research", "mcp:A")
    assert registry.resolve("research", "mcp:A", "read")
    registry.approve_local(remove["request_id"])
    with pytest.raises(PermissionError):
        registry.resolve("research", "mcp:A", "read")
    with pytest.raises(PermissionError, match="configured workspaces"):
        registry.request_remove("sentra", "mcp:A")


def test_workspace_permissions_are_shared_by_filesystem_and_process_gate(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    dataset = tmp_path / "dataset"
    primary.mkdir()
    dataset.mkdir()
    (dataset / "data.txt").write_text("research-data\n", encoding="utf-8")

    config = _config(primary, process_mode="unrestricted")
    audit = AuditLogger(config.audit_log)
    registry = WorkspaceRegistry(
        config,
        audit,
        state_path=primary / ".sentra" / "workspaces.json",
    )
    _approve_add(
        registry,
        path=dataset,
        owner="mcp:A",
        alias="dataset",
        permissions=("read",),
        lifetime="permanent",
    )
    filesystem = FilesystemService(config, audit, registry)
    processes = ProcessService(config, audit, registry)

    read = filesystem.read_file(
        "data.txt",
        workspace="dataset",
        owner="mcp:A",
    )
    assert "research-data" in read["content"]
    with pytest.raises(PermissionError, match="does not grant write"):
        filesystem.write_file(
            "data.txt",
            "changed",
            workspace="dataset",
            owner="mcp:A",
        )
    with pytest.raises(PermissionError, match="does not grant execute"):
        processes.start_process(
            ["python", "-c", "print('no')"],
            "mcp:A",
            workspace="dataset",
            mode="unrestricted",
        )


def test_process_privilege_ceiling_never_falls_back_to_host(tmp_path: Path) -> None:
    config = _config(tmp_path, process_mode="sandbox")
    service = ProcessService(config)
    with pytest.raises(PermissionError, match="exceeds configured privilege ceiling"):
        service.start_process(
            ["python", "-c", "print('host')"],
            "owner",
            mode="workspace",
        )
    with pytest.raises(PermissionError, match="exceeds configured privilege ceiling"):
        service.start_process(
            ["python", "-c", "print('host')"],
            "owner",
            mode="unrestricted",
        )


def test_http_mcp_session_identity_is_stable_and_isolated() -> None:
    def ctx(session_id: str):
        request = SimpleNamespace(headers={"mcp-session-id": session_id})
        request_context = SimpleNamespace(request=request, meta={})
        return SimpleNamespace(request_context=request_context)

    first_a = request_identity(ctx("session-A"))[0]
    first_b = request_identity(ctx("session-A"))[0]
    second = request_identity(ctx("session-B"))[0]
    assert first_a == first_b
    assert first_a.startswith("mcp:")
    assert second.startswith("mcp:")
    assert first_a != second
    assert "session-A" not in first_a


class _FakeRepository:
    async def run_registered(self, operation, target, workspace, owner):
        if target == "slow":
            await asyncio.sleep(5)
        else:
            await asyncio.sleep(0.15)
        return {
            "operation": operation.lower(),
            "target": target or None,
            "passed": True,
            "result": "PASS exit=0",
            "workspace": workspace or "root:0",
            "workspace_alias": "sentra",
        }


def test_async_jobs_return_immediately_wait_result_and_cancel(tmp_path: Path) -> None:
    config = _config(tmp_path, process_mode="unrestricted")
    jobs = JobService(
        config,
        AuditLogger(config.audit_log),
        _FakeRepository(),
        db_path=tmp_path / ".sentra" / "jobs.sqlite3",
    )
    try:
        started_at = time.monotonic()
        job = jobs.start("TEST", "mcp:A", target="unit")
        assert time.monotonic() - started_at < 0.5
        early = jobs.wait(job["job_id"], "mcp:A", 0.02)
        assert early["state"] in {"PENDING", "RUNNING"}
        assert early["timed_out"] is True

        deadline = time.monotonic() + 3
        result = None
        while time.monotonic() < deadline:
            status = jobs.status(job["job_id"], "mcp:A")
            if status["state"] == "COMPLETED":
                result = jobs.result(job["job_id"], "mcp:A")
                break
            time.sleep(0.02)
        assert result is not None
        assert result["result"]["passed"] is True

        slow = jobs.start("TEST", "mcp:A", target="slow")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if jobs.status(slow["job_id"], "mcp:A")["state"] == "RUNNING":
                break
            time.sleep(0.01)
        jobs.cancel(slow["job_id"], "mcp:A")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = jobs.status(slow["job_id"], "mcp:A")["state"]
            if state == "CANCELLED":
                break
            time.sleep(0.02)
        assert jobs.status(slow["job_id"], "mcp:A")["state"] == "CANCELLED"
        with pytest.raises(PermissionError):
            jobs.status(job["job_id"], "mcp:B")
    finally:
        jobs.close()


def _make_docx(path: Path) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>Hello DOCX</w:t></w:r></w:p></w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)


def test_structured_documents_cover_research_formats(tmp_path: Path) -> None:
    config = _config(tmp_path)
    audit = AuditLogger(config.audit_log)
    fs = FilesystemService(config, audit)
    docs = DocumentService(fs, audit)

    (tmp_path / "table.csv").write_text(
        "name,value\nalpha,1\nbeta,2\n",
        encoding="utf-8",
    )
    (tmp_path / "items.jsonl").write_text(
        '{"name":"alpha"}\n{"name":"beta"}\n',
        encoding="utf-8",
    )
    (tmp_path / "notebook.ipynb").write_text(
        json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {},
                "cells": [
                    {
                        "cell_type": "code",
                        "source": ["print('hello')\n"],
                        "metadata": {},
                        "outputs": [],
                        "execution_count": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _make_docx(tmp_path / "doc.docx")
    docs.write_pdf("doc.pdf", "Hello PDF", "Research PDF")

    csv_data = docs.read_document("table.csv")
    assert csv_data["rows"][0]["name"] == "alpha"
    jsonl = docs.read_document("items.jsonl")
    assert jsonl["items"][1]["value"]["name"] == "beta"
    notebook = docs.read_document("notebook.ipynb")
    assert "print('hello')" in notebook["cells"][0]["source"]
    docx = docs.read_document("doc.docx")
    assert docx["blocks"][0]["text"] == "Hello DOCX"
    pdf = docs.read_document("doc.pdf")
    assert "Hello PDF" in pdf["pages"][0]["text"]

    pyarrow = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    table = pyarrow.table({"name": ["alpha", "beta"], "value": [1, 2]})
    pq.write_table(table, tmp_path / "table.parquet")
    parquet = docs.read_document("table.parquet")
    assert parquet["rows"][1]["name"] == "beta"


class _FakeBrowser:
    def __init__(self, *, slow: bool = False, collect_failures: int = 0) -> None:
        self.counter = 0
        self.deleted: list[str] = []
        self.slow = slow
        self.collect_failures = collect_failures
        self.collect_attempts = 0
        self._prompts: dict[str, str] = {}

    async def chat_start(
        self,
        owner: str,
        prompt: str,
        *,
        timeout_s: int,
    ) -> dict:
        self.counter += 1
        conversation_id = f"fake-{self.counter}"
        self._prompts[conversation_id] = prompt
        return {
            "started": True,
            "text": "",
            "conversation_url": f"https://chatgpt.com/c/{conversation_id}",
            "conversation_id": conversation_id,
        }

    async def chat_collect(
        self,
        owner: str,
        conversation_url: str,
        *,
        timeout_s: int,
    ) -> dict:
        self.collect_attempts += 1
        if self.collect_failures > 0:
            self.collect_failures -= 1
            raise RuntimeError(
                "TAB_ERROR: The page keeping the extension port is moved into "
                "back/forward cache, so the message channel is closed."
            )
        if self.slow:
            await asyncio.sleep(10)
        conversation_id = conversation_url.rstrip("/").split("/")[-1]
        prompt = self._prompts[conversation_id]
        if "STRICT JSON" in prompt:
            text = '{"selected":[0,1],"reason":"evidence"}'
        else:
            text = f"research-{conversation_id}"
        return {
            "text": text,
            "conversation_url": conversation_url,
            "conversation_id": conversation_id,
        }

    async def delete_chat(
        self,
        owner: str,
        conversation_url: str,
        *,
        timeout_s: int,
    ) -> dict:
        self.deleted.append(conversation_url)
        return {"deleted": True}


def test_research_parallel_and_mcts_are_bounded_and_clean_temporary_chats(
    tmp_path: Path,
) -> None:
    async def probe() -> None:
        config = _config(tmp_path)
        browser = _FakeBrowser()
        service = ResearchService(
            config,
            AuditLogger(config.audit_log),
            browser,
            db_path=tmp_path / ".sentra" / "research.sqlite3",
        )
        parallel = await service.start(
            "compare two approaches",
            "mcp:A",
            strategy="parallel",
            temporary=True,
            branches=2,
            timeout_s=30,
        )
        done = await service.wait(parallel["run_id"], "mcp:A", 5)
        assert done["state"] == "COMPLETED"
        result = done["result"]
        assert result["algorithm"] == "bounded-parallel-subagents"
        assert result["conversations_created"] == 3
        assert all(item["deleted"] for item in result["cleanup"])

        mcts = await service.start(
            "explore architecture",
            "mcp:A",
            strategy="mcts",
            temporary=True,
            branches=2,
            max_depth=2,
            beam_width=1,
            timeout_s=30,
        )
        done = await service.wait(mcts["run_id"], "mcp:A", 5)
        assert done["state"] == "COMPLETED"
        result = done["result"]
        assert result["algorithm"] == "bounded-mcts-inspired-beam-search"
        assert any(node["kind"] == "judge" for node in result["nodes"])
        with pytest.raises(PermissionError):
            service.status(mcts["run_id"], "mcp:B")
        await service.close()

    asyncio.run(probe())


def test_research_collect_retries_transient_bfcache_without_restarting_chat(
    tmp_path: Path,
) -> None:
    async def probe() -> None:
        config = _config(tmp_path)
        browser = _FakeBrowser(collect_failures=1)
        service = ResearchService(
            config,
            AuditLogger(config.audit_log),
            browser,
            db_path=tmp_path / ".sentra" / "research-bfcache.sqlite3",
        )
        run = await service.start(
            "retry read-only collection",
            "mcp:A",
            strategy="single",
            temporary=True,
            timeout_s=30,
        )
        done = await service.wait(run["run_id"], "mcp:A", 5)
        assert done["state"] == "COMPLETED"
        assert browser.counter == 1
        assert browser.collect_attempts == 2
        assert done["result"]["conversations_created"] == 1
        assert done["result"]["cleanup"][0]["deleted"] is True
        await service.close()

    asyncio.run(probe())


def test_research_cancel_cancels_task(tmp_path: Path) -> None:
    async def probe() -> None:
        config = _config(tmp_path)
        browser = _FakeBrowser(slow=True)
        service = ResearchService(
            config,
            AuditLogger(config.audit_log),
            browser,
            db_path=tmp_path / ".sentra" / "research-cancel.sqlite3",
        )
        run = await service.start(
            "slow objective",
            "mcp:A",
            strategy="single",
            temporary=True,
            timeout_s=30,
        )
        await asyncio.sleep(0.05)
        service.cancel(run["run_id"], "mcp:A")
        result = await service.wait(run["run_id"], "mcp:A", 3)
        assert result["state"] == "CANCELLED"
        await service.close()

    asyncio.run(probe())


def test_edge_workers_require_ready_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def probe() -> None:
        config = _config(tmp_path)
        service = BrowserControlService(config, AuditLogger(config.audit_log))

        async def workers():
            return ["ready", "connected", "stale", "unhealthy"]

        def cached_status(worker: str):
            if worker == "ready":
                return {
                    "online": True,
                    "last_seen": 100.0,
                    "status": {
                        "url": "https://chatgpt.com/",
                        "composer_found": True,
                    },
                }
            if worker == "connected":
                return {
                    "online": True,
                    "last_seen": 100.0,
                    "status": {
                        "url": "https://chatgpt.com/",
                        "composer_found": False,
                    },
                }
            if worker == "stale":
                return {
                    "online": False,
                    "last_seen": 1.0,
                    "status": {},
                }
            return {
                "online": True,
                "last_seen": 100.0,
                "status": {"error": "bad"},
            }

        monkeypatch.setattr(service, "_edge_workers", workers)
        monkeypatch.setattr(service, "_edge_cached_status_sync", cached_status)
        inventory = await service._edge_worker_inventory()
        states = {item["worker"]: item["worker_state"] for item in inventory}
        assert states == {
            "ready": "READY",
            "connected": "CONNECTED",
            "stale": "STALE",
            "unhealthy": "UNHEALTHY",
        }
        assert [item["worker"] for item in inventory if item["usable"]] == ["ready"]
        await service.shutdown()

    asyncio.run(probe())


def test_edge_bridge_idle_is_visible_without_controller_tabs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe() -> None:
        config = _config(tmp_path)
        service = BrowserControlService(config, AuditLogger(config.audit_log))

        async def health():
            return {
                "ok": True,
                "workers_online": [],
                "pool": {"active": True, "owner": "POOL-test"},
            }

        async def inventory():
            return []

        monkeypatch.setattr(service, "_edge_health", health)
        monkeypatch.setattr(service, "_edge_worker_inventory", inventory)
        result = await service.tabs("mcp:A")
        assert result["tabs"] == []
        assert result["edge_bridge"] == {
            "state": "IDLE",
            "lazy_controller": True,
            "controller_tabs": 0,
            "max_controller_tabs": 1,
            "pool_active": True,
            "workers_online": [],
        }
        await service.shutdown()

    asyncio.run(probe())


def test_chatgpt_edge_open_bootstraps_lazy_controller_without_playwright(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe() -> None:
        config = _config(tmp_path)
        playwright_calls = []
        edge_calls = []

        def forbidden_factory(**kwargs):
            playwright_calls.append(kwargs)
            raise AssertionError("Playwright must not be created for chatgpt.com")

        service = BrowserControlService(
            config,
            AuditLogger(config.audit_log),
            session_factory=forbidden_factory,
        )

        async def no_workers():
            return []

        async def allow_url(url: str):
            return url

        async def edge_action(worker, action, args, *, timeout_s=20):
            edge_calls.append((worker, action, dict(args), timeout_s))
            if action == "navigate":
                assert worker is None
                return {
                    "url": "https://chatgpt.com/",
                    "worker": "TAB-42",
                }
            assert action == "close"
            assert worker == "TAB-42"
            return {
                "closed": True,
                "tab_preserved": True,
                "controller_released": True,
            }

        monkeypatch.setattr(service, "_edge_worker_inventory", no_workers)
        monkeypatch.setattr(service, "_validate_url", allow_url)
        monkeypatch.setattr(service, "_edge_action", edge_action)

        opened = await service.open(
            "mcp:A",
            "https://chatgpt.com/",
            backend="auto",
        )
        assert opened["session_id"] == "edge:TAB-42"
        assert opened["backend"] == "edge"
        assert service.edge_sessions["edge:TAB-42"]["worker"] == "TAB-42"
        assert edge_calls == [
            (None, "navigate", {"url": "https://chatgpt.com/"}, 30)
        ]
        assert playwright_calls == []
        await service.shutdown()
        assert edge_calls == [
            (None, "navigate", {"url": "https://chatgpt.com/"}, 30),
            ("TAB-42", "close", {}, 20),
        ]
        assert service.edge_sessions == {}

    asyncio.run(probe())


def test_edge_close_and_shutdown_release_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe() -> None:
        config = _config(tmp_path)
        service = BrowserControlService(config, AuditLogger(config.audit_log))
        calls = []

        async def edge_action(worker, action, args, *, timeout_s=20):
            calls.append((worker, action, dict(args), timeout_s))
            assert action == "close"
            return {
                "closed": True,
                "tab_preserved": True,
                "controller_released": True,
                "worker": worker,
            }

        monkeypatch.setattr(service, "_edge_action", edge_action)

        service.edge_sessions["edge:TAB-41"] = {
            "owner": "mcp:A",
            "worker": "TAB-41",
            "created": 1.0,
        }
        closed = await service.close("edge:TAB-41", "mcp:A")
        assert closed == {
            "session_id": "edge:TAB-41",
            "backend": "edge",
            "closed": True,
            "tab_preserved": True,
        }
        assert "edge:TAB-41" not in service.edge_sessions

        service.edge_sessions["edge:TAB-42"] = {
            "owner": "mcp:A",
            "worker": "TAB-42",
            "created": 2.0,
        }
        await service.shutdown()
        assert service.edge_sessions == {}
        assert calls == [
            ("TAB-41", "close", {}, 20),
            ("TAB-42", "close", {}, 20),
        ]

    asyncio.run(probe())


def test_chatgpt_auto_backend_never_falls_back_to_playwright(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe() -> None:
        config = _config(tmp_path)
        calls = []

        def forbidden_factory(**kwargs):
            calls.append(kwargs)
            raise AssertionError("Playwright fallback must not be created for chatgpt.com")

        service = BrowserControlService(
            config,
            AuditLogger(config.audit_log),
            session_factory=forbidden_factory,
        )

        async def no_workers():
            return []

        async def allow_url(url: str):
            return url

        async def bootstrap_fails(worker, action, args, *, timeout_s=20):
            assert worker is None
            raise RuntimeError("no inactive principal ChatGPT tab")

        monkeypatch.setattr(service, "_edge_worker_inventory", no_workers)
        monkeypatch.setattr(service, "_validate_url", allow_url)
        monkeypatch.setattr(service, "_edge_action", bootstrap_fails)

        with pytest.raises(RuntimeError, match="principal Edge bridge is required"):
            await service.open(
                "mcp:A",
                "https://chatgpt.com/",
                backend="auto",
            )

        assert calls == []
        await service.shutdown()

    asyncio.run(probe())


def test_edge_viewport_screenshot_uses_relay_and_writes_jpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe() -> None:
        config = _config(tmp_path)
        service = BrowserControlService(config, AuditLogger(config.audit_log))
        service.edge_sessions["edge:TAB-55"] = {
            "owner": "mcp:A",
            "worker": "TAB-55",
            "created": 1.0,
        }
        jpeg = b"\xff\xd8\xffedge-test"
        calls = []

        async def edge_action(worker, action, args, *, timeout_s=20):
            calls.append((worker, action, dict(args), timeout_s))
            if action == "screenshot":
                return {
                    "image_base64": base64.b64encode(jpeg).decode("ascii"),
                    "mime_type": "image/jpeg",
                    "url": "https://chatgpt.com/",
                    "full_page": False,
                }
            if action == "close":
                return {
                    "closed": True,
                    "tab_preserved": True,
                    "controller_released": True,
                }
            raise AssertionError(action)

        monkeypatch.setattr(service, "_edge_action", edge_action)

        saved = await service.screenshot(
            "edge:TAB-55",
            "mcp:A",
            full_page=False,
            include_base64=False,
        )
        assert saved["backend"] == "edge"
        assert saved["full_page"] is False
        assert saved["mime_type"] == "image/jpeg"
        assert saved["bytes"] == len(jpeg)
        assert "image_base64" not in saved
        assert Path(saved["path"]).read_bytes() == jpeg
        assert calls[0] == ("TAB-55", "screenshot", {"full_page": False}, 30)

        with pytest.raises(ValueError, match="viewport screenshots only"):
            await service.screenshot(
                "edge:TAB-55",
                "mcp:A",
                full_page=True,
                include_base64=False,
            )

        await service.close("edge:TAB-55", "mcp:A")
        assert calls[-1] == ("TAB-55", "close", {}, 20)

    asyncio.run(probe())


def test_edge_open_reclaims_offline_orphan_before_lazy_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def probe() -> None:
        config = _config(tmp_path)
        service = BrowserControlService(config, AuditLogger(config.audit_log))
        service.edge_sessions["edge:TAB-OLD"] = {
            "owner": "mcp:lost",
            "worker": "TAB-OLD",
            "created": 1.0,
        }
        calls = []

        async def no_workers():
            return []

        async def allow_url(url: str):
            return url

        async def edge_action(worker, action, args, *, timeout_s=20):
            calls.append((worker, action, dict(args), timeout_s))
            assert action == "navigate"
            assert worker is None
            return {"url": "https://chatgpt.com/", "worker": "TAB-NEW"}

        monkeypatch.setattr(service, "_edge_worker_inventory", no_workers)
        monkeypatch.setattr(service, "_validate_url", allow_url)
        monkeypatch.setattr(service, "_edge_action", edge_action)

        opened = await service.open(
            "mcp:new",
            "https://chatgpt.com/",
            backend="edge",
        )
        assert opened["session_id"] == "edge:TAB-NEW"
        assert "edge:TAB-OLD" not in service.edge_sessions
        assert service.edge_sessions["edge:TAB-NEW"]["owner"] == "mcp:new"
        assert calls == [
            (None, "navigate", {"url": "https://chatgpt.com/"}, 30)
        ]

    asyncio.run(probe())
