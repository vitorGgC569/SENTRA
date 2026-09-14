"""Adversarial regressions for actual filesystem and subprocess boundaries."""
import asyncio
import sys

import pytest

from repository.gateway import CommandGateway
from repository.parser import parse
from workspace.command_runner import CommandRunner
from workspace.patch_manager import PatchManager
from workspace.tool_gateway import SecurityPolicyError, ToolGateway


def change(path, old, new):
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-{old}\n+{new}\n"


def test_patch_rejects_stale_context_without_changing_either_file(tmp_path):
    (tmp_path / "one.py").write_text("one = 1\n")
    (tmp_path / "two.py").write_text("two = 2\n")
    patch = change("one.py", "one = 1", "one = 3") + change("two.py", "stale = 1", "two = 4")
    result = PatchManager.apply_patch(tmp_path, patch)
    assert not result["success"] and "context mismatch" in result["error"]
    assert (tmp_path / "one.py").read_text() == "one = 1\n"
    assert (tmp_path / "two.py").read_text() == "two = 2\n"


@pytest.mark.parametrize("header,body", [("@@ -1,4 +1,1 @@", "-x\n+y\n"),
                                         ("@@ -99 +99 @@", "-x\n+y\n"),
                                         ("@@ -1 +2 @@", "-x\n+y\n")])
def test_bad_hunk_counts_and_positions_rejected(tmp_path, header, body):
    (tmp_path / "a").write_text("x\n")
    result = PatchManager.apply_patch(tmp_path, f"--- a/a\n+++ b/a\n{header}\n{body}")
    assert not result["success"]
    assert (tmp_path / "a").read_text() == "x\n"


def test_multifile_io_failure_rolls_back_bytes_and_creation(tmp_path, monkeypatch):
    import workspace.patch_manager as module
    (tmp_path / "a").write_bytes(b"before\r\n")
    real_write = module._atomic_write
    calls = 0

    def fail_once(path, data, mode=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected disk failure")
        return real_write(path, data, mode)

    monkeypatch.setattr(module, "_atomic_write", fail_once)
    patch = change("a", "before", "after") + "--- /dev/null\n+++ b/sub/new\n@@ -0,0 +1 @@\n+new\n"
    result = PatchManager.apply_patch(tmp_path, patch)
    assert not result["success"]
    assert (tmp_path / "a").read_bytes() == b"before\r\n"
    assert not (tmp_path / "sub").exists()


def test_check_applies_rejects_overlapping_hunks_without_touching_disk(tmp_path):
    (tmp_path / "a.py").write_text("l1\nl2\nl3\nl4\nl5\nl6\n")
    overlapping = ("--- a/a.py\n+++ b/a.py\n"
                   "@@ -1,3 +1,3 @@\n l1\n-l2\n+X\n l3\n"
                   "@@ -3,3 +3,3 @@\n l3\n-l4\n+Y\n l5\n")
    with pytest.raises(ValueError, match="overlapping"):
        PatchManager.check_applies(tmp_path, overlapping)
    assert (tmp_path / "a.py").read_text() == "l1\nl2\nl3\nl4\nl5\nl6\n"


def test_check_applies_names_new_file_misuse(tmp_path):
    bad2 = ("--- a/newmod.py\n+++ b/newmod.py\n"
            "@@ -1,2 +1,2 @@\n ctx\n-old\n+new\n")
    with pytest.raises(ValueError, match="/dev/null"):
        PatchManager.check_applies(tmp_path, bad2)


def test_check_applies_accepts_clean_patch_without_writing(tmp_path):
    (tmp_path / "a.py").write_text("l1\nl2\n")
    PatchManager.check_applies(tmp_path, change("a.py", "l1", "L1"))
    assert (tmp_path / "a.py").read_text() == "l1\nl2\n"


def test_patch_creation_deletion_and_no_final_newline(tmp_path):
    created = "--- /dev/null\n+++ b/new\n@@ -0,0 +1 @@\n+x\n\\ No newline at end of file\n"
    assert PatchManager.apply_patch(tmp_path, created)["success"]
    assert (tmp_path / "new").read_bytes() == b"x"
    deleted = "--- a/new\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n\\ No newline at end of file\n"
    assert PatchManager.apply_patch(tmp_path, deleted)["success"]
    assert not (tmp_path / "new").exists()


async def test_creation_syntax_failure_leaves_no_empty_file(tmp_path):
    gw = CommandGateway(tmp_path)
    session = gw.open_session()
    patch = gw.stage_patch(session, "--- /dev/null\n+++ b/bad.py\n@@ -0,0 +1 @@\n+def broken(:\n")
    result = await gw.execute(session, f"[[PATCH|{patch}]]")
    assert "ROLLBACK" in result
    assert not (tmp_path / "bad.py").exists()
    assert gw.audit[-1]["status"] == "FAILED"
    assert gw.audit[-1]["before_hash"]


async def test_rollback_alias_is_owned_and_never_falls_back(tmp_path):
    (tmp_path / "code.py").write_text("x = 1\n")
    gw = CommandGateway(tmp_path)
    session, other = gw.open_session(), gw.open_session()
    patch = gw.stage_patch(session, change("code.py", "x = 1", "x = 2"))
    assert "PATCH OK" in await gw.execute(session, f"[[PATCH|{patch}]]")
    txn = session.transaction_aliases["T01"]
    assert "DENIED" in await gw.execute(other, f"[[ROLLBACK|{txn}]]", role="repair")
    assert "DENIED" in await gw.execute(session, "[[ROLLBACK|unknown]]", role="repair")
    assert (tmp_path / "code.py").read_text() == "x = 2\n"
    assert "ROLLBACK OK" in await gw.execute(session, "[[ROLLBACK|T01]]", role="repair")
    assert (tmp_path / "code.py").read_text() == "x = 1\n"


async def test_rollback_will_not_overwrite_later_edit(tmp_path):
    (tmp_path / "a").write_text("one\n")
    gw = CommandGateway(tmp_path)
    session = gw.open_session()
    patch = gw.stage_patch(session, change("a", "one", "two"))
    await gw.execute(session, f"[[PATCH|{patch}]]")
    (tmp_path / "a").write_text("user changed this\n")
    assert "ROLLBACK_CONFLICT" in await gw.execute(session, "[[ROLLBACK|T01]]", role="repair")
    assert (tmp_path / "a").read_text() == "user changed this\n"


async def test_session_permissions_idempotency_and_shared_aliases(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    gw = CommandGateway(tmp_path)
    session = gw.open_session(read=False, write=False, run=False)
    for directive in ("[[R|a.py]]", "[[TEST|all]]", "[[PATCH|P01]]"):
        assert "DENIED" in await gw.execute(session, directive)
    session = gw.open_session()
    assert "F01" in await gw.execute(session, "[[R|a.py|1|1]]")
    assert "F01" in await gw.execute(session, "[[R|F01|1|2]]")
    assert len(session.file_aliases) == 1
    patch = gw.stage_patch(session, change("a.py", "x = 1", "x = 2"))
    directive = f"[[PATCH|{patch}]]"
    first = await gw.execute(session, directive, idempotency_key="retry-1")
    assert await gw.execute(session, directive, idempotency_key="retry-1") == first
    assert len(gw.txns._txns) == 1
    assert "DENIED" in await gw.execute(session, "[[R|a.py]]", idempotency_key="retry-1")


async def test_paths_secrets_symlinks_and_sibling_prefix(tmp_path):
    root = tmp_path / "repo"
    sibling = tmp_path / "repo-extra"
    root.mkdir()
    sibling.mkdir()
    (sibling / "private").write_text("private")
    with pytest.raises(SecurityPolicyError):
        await ToolGateway(root).read_file("executor", "../repo-extra/private")
    (root / "auth.json").write_text('{"SECRET_SENTINEL": true}')
    (root / ".env").write_text("SECRET_SENTINEL=yes")
    (root / "code.py").write_text("public = True\n")
    gw = CommandGateway(root)
    session = gw.open_session()
    for path in ("auth.json", ".env", "C:/Windows/file", "NUL", "code.py:secret", "..\\repo-extra\\private"):
        assert "DENIED" in await gw.execute(session, f"[[R|{path}]]")
    assert "SECRET_SENTINEL" not in await gw.execute(session, "[[S|SECRET_SENTINEL|.]]")
    assert "auth.json" not in await gw.execute(session, "[[T]]")
    try:
        (root / "link").symlink_to(sibling, target_is_directory=True)
    except OSError:
        return  # Remaining non-symlink assertions always run, including on Windows.
    assert "DENIED" in await gw.execute(session, "[[R|link/private]]")


async def test_result_pagination_is_bounded_owned_and_advances(tmp_path):
    gw = CommandGateway(tmp_path)
    owner, other = gw.open_session(), gw.open_session()
    rid, page, more = gw.results.store("x" * 100000 + "\nEND_OF_RESULT", owner)
    assert len(page) <= 16000 and more
    assert "NOT_FOUND" in await gw.execute(other, f"[[NEXT|{rid}]]")
    assert "not found" in await gw.execute(other, f"[[RART|{rid}]]")
    pages = [page]
    while "MORE=true" in pages[-1]:
        pages.append(await gw.execute(owner, "[[NEXT|R01]]"))
        assert len(pages[-1]) <= 16000
        assert len(pages) < 100
    assert "END_OF_RESULT" in pages[-1]
    assert len(set(pages)) == len(pages)


@pytest.mark.parametrize("command", ["echo hi", "python -c \"print('fake pass')\"",
                                     "[[TEST|all]]; echo hello", "[[DELETE_WINDOWS]]",
                                     "[[TEST|all|--override]]", "[[TEST|../../escape]]"])
async def test_model_shell_and_unregistered_commands_are_rejected(tmp_path, command):
    result = await CommandRunner(tmp_path).run_command(command)
    assert not result["passed"] and "POLICY_DENIED" in result["stderr"]


async def test_timeout_cleans_up_process_and_output_is_bounded(tmp_path):
    runner = CommandRunner(tmp_path)
    late_file = tmp_path / "should-not-exist"
    script = "import time,pathlib; time.sleep(.7); pathlib.Path('should-not-exist').touch()"
    result = await runner.run_argv([sys.executable, "-c", script], timeout=.1)
    assert not result["passed"] and "timed out" in result["stderr"]
    await asyncio.sleep(.8)
    assert not late_file.exists()
    result = await runner.run_argv([sys.executable, "-c", "print('x'*100000)"])
    assert result["passed"] and result["output_truncated"]
    assert len(result["stdout"]) <= 64000


def test_parser_rejects_embedded_or_multiline_directives():
    assert parse("[[R|file]]\n[[DELETE_WINDOWS]]") is None
    assert parse("[[R|file\nmore]]") is None
    assert parse("[[R|file|[[DELETE_WINDOWS]]]]") is None
