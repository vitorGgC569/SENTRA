from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest
from mcp import Client

from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import MCPConfig
from sentra_mcp.models import ResponseEnvelope
from sentra_mcp.server import SentraMCPServer
from sentra_mcp.services.filesystem import FilesystemService, MAX_LIST_DEPTH
from sentra_mcp.tools.filesystem import register_filesystem_tools
from workspace.paths import PathAccessError


def make_service(
    tmp_path: Path,
    *,
    read_limit: int = 4096,
    write_limit: int = 4096,
) -> FilesystemService:
    config = MCPConfig(
        allowed_roots=(tmp_path,),
        max_read_bytes=read_limit,
        max_write_bytes=write_limit,
        audit_log=tmp_path / "audit.jsonl",
    )
    return FilesystemService(config, AuditLogger(config.audit_log))


def test_relative_and_absolute_paths_within_allowed_root(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    target = tmp_path / "hello.txt"
    target.write_text("a\nb\nc\n", encoding="utf-8")

    relative = service.read_file("hello.txt", offset=1, length=1)
    absolute = service.read_file(str(target), offset=0, length=2)

    assert relative["content"] == "b\n"
    assert relative["line_count"] == 1
    assert absolute["content"] == "a\nb\n"
    assert absolute["path"] == "hello.txt"


def test_path_escape_absolute_outside_and_private_paths_are_blocked(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("no", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")

    with pytest.raises(PathAccessError):
        service.read_file("../outside.txt")
    with pytest.raises(PathAccessError):
        service.read_file(str(outside))
    with pytest.raises(PathAccessError):
        service.read_file(".env")


def test_symlink_or_junction_escape_is_blocked(tmp_path: Path) -> None:
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("hidden", encoding="utf-8")
    link = tmp_path / "escape"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        link.symlink_to(outside_dir, target_is_directory=True)

    try:
        service = make_service(tmp_path)
        with pytest.raises(PathAccessError):
            service.read_file("escape/secret.txt")
        listing = service.list_directory(".", depth=2)
        assert "escape/secret.txt" not in {item["path"] for item in listing["entries"]}
    finally:
        if link.exists() or link.is_symlink():
            if os.name == "nt":
                subprocess.run(["cmd", "/c", "rmdir", str(link)], check=False, capture_output=True)
            else:
                link.unlink()


def test_read_and_write_limits_are_deterministic(tmp_path: Path) -> None:
    service = make_service(tmp_path, read_limit=5, write_limit=5)
    (tmp_path / "read.txt").write_text("123\n456\n", encoding="utf-8")

    assert service.read_file("read.txt", offset=0, length=1)["content"] == "123\n"
    with pytest.raises(ValueError, match="read exceeds"):
        service.read_file("read.txt")
    with pytest.raises(ValueError, match="write exceeds"):
        service.write_file("write.txt", "123456")

    service.write_file("write.txt", "123", mode="rewrite")
    with pytest.raises(ValueError, match="resulting file exceeds"):
        service.write_file("write.txt", "456", mode="append")


def test_list_directory_depth_is_bounded_and_private_entries_are_hidden(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "deep.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("hidden", encoding="utf-8")

    shallow = service.list_directory(".", depth=1)
    paths = {entry["path"] for entry in shallow["entries"]}
    assert "a" in paths
    assert "a/b" not in paths
    assert ".git" not in paths

    with pytest.raises(ValueError, match="depth"):
        service.list_directory(".", depth=MAX_LIST_DEPTH + 1)


def test_search_literal_regex_context_and_result_limit(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    (tmp_path / "alpha.txt").write_text("zero\nneedle one\nend\n", encoding="utf-8")
    (tmp_path / "beta.txt").write_text("needle two\n", encoding="utf-8")
    (tmp_path / "gamma.py").write_text("nothing\n", encoding="utf-8")

    names = service.search(
        ".",
        r".*\.txt$",
        search_type="names",
        literal=False,
        max_results=1,
    )
    assert len(names["results"]) == 1

    content = service.search(
        ".",
        "needle",
        search_type="content",
        literal=True,
        max_results=2,
        context=1,
    )
    assert len(content["results"]) == 2
    assert content["results"][0]["line"] in {1, 2}
    assert "context" in content["results"][0]


def test_read_multiple_files_keeps_individual_failures(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    (tmp_path / "ok.txt").write_text("ok\n", encoding="utf-8")

    result = service.read_multiple_files(["ok.txt", "../blocked.txt"])

    assert result["results"][0]["ok"] is True
    assert result["results"][0]["content"] == "ok\n"
    assert result["results"][1]["ok"] is False


def test_create_move_file_info_and_edit_block(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.create_directory("nested")
    service.write_file("nested/a.txt", "one\ntwo\n", mode="rewrite")

    info = service.file_info("nested/a.txt")
    assert info["type"] == "file"
    assert info["line_count"] == 2

    service.move_file("nested/a.txt", "nested/b.txt")
    assert not (tmp_path / "nested" / "a.txt").exists()
    assert (tmp_path / "nested" / "b.txt").exists()

    edited = service.edit_block("nested/b.txt", "two", "three", expected_replacements=1)
    assert edited["replacements"] == 1
    assert (tmp_path / "nested" / "b.txt").read_text(encoding="utf-8") == "one\nthree\n"


def test_edit_block_rejects_ambiguous_and_count_mismatch(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    (tmp_path / "edit.txt").write_text("same same", encoding="utf-8")

    with pytest.raises(ValueError, match="ambiguous replacement"):
        service.edit_block("edit.txt", "same", "x")
    with pytest.raises(ValueError, match="count mismatch"):
        service.edit_block("edit.txt", "same", "x", expected_replacements=3)

    assert (tmp_path / "edit.txt").read_text(encoding="utf-8") == "same same"


def test_mutation_audit_never_logs_file_content(tmp_path: Path) -> None:
    secret = "CONTENT-SHOULD-NOT-LEAK"
    service = make_service(tmp_path)
    service.write_file("audit-target.txt", secret)

    audit_text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    record = json.loads(audit_text)
    assert record["action"] == "filesystem.write_file"
    assert record["outcome"] == "ok"
    assert record["details"]["bytes"] == len(secret.encode("utf-8"))
    assert secret not in audit_text


def test_tools_return_response_envelopes_and_register_on_server(tmp_path: Path) -> None:
    async def probe() -> None:
        config = MCPConfig(
            allowed_roots=(tmp_path,),
            audit_log=tmp_path / "audit.jsonl",
        )
        runtime = SentraMCPServer(config)
        (tmp_path / "file.txt").write_text("hello\n", encoding="utf-8")

        async with Client(runtime.mcp) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            expected = {
                "sentra_health",
                "sentra_list_directory",
                "sentra_read_file",
                "sentra_read_multiple_files",
                "sentra_file_info",
                "sentra_search",
                "sentra_create_directory",
                "sentra_move_file",
                "sentra_write_file",
                "sentra_edit_block",
            }
            assert expected <= names

            success = await client.call_tool("sentra_read_file", {"path": "file.txt"})
            assert success.structured_content is not None
            envelope = ResponseEnvelope.model_validate(success.structured_content)
            assert envelope.ok is True
            assert envelope.data is not None
            assert envelope.data["content"] == "hello\n"

            denied = await client.call_tool(
                "sentra_read_file",
                {"path": "../blocked.txt"},
            )
            assert denied.structured_content is not None
            error = ResponseEnvelope.model_validate(denied.structured_content)
            assert error.ok is False
            assert error.error is not None
            assert error.error.code == "path_denied"

    asyncio.run(probe())


def test_register_filesystem_tools_can_be_used_independently(tmp_path: Path) -> None:
    from mcp.server import MCPServer

    async def probe() -> None:
        service = make_service(tmp_path)
        mcp = MCPServer("filesystem-test")
        register_filesystem_tools(mcp, service)
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert "sentra_read_file" in {tool.name for tool in tools.tools}

    asyncio.run(probe())
