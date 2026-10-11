"""Project review is a read-only projection of an existing authorized workspace."""
import subprocess
from pathlib import Path

import pytest

from sentra_canvas.project_review import list_level, file_preview, git_diff
from test_sentra_runtime_canvas_center_http import running_canvas, request


def test_bounded_preview_and_directory_listing(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / ".sentra").mkdir()
    (tmp_path / ".env").write_text("SECRET=NO_PREVIEW", encoding="utf-8")
    (tmp_path / "huge.txt").write_bytes(b"x" * 131073)
    names = {x["name"] for x in list_level(tmp_path)["items"]}
    assert "src" in names and "huge.txt" in names
    assert ".sentra" not in names and ".env" not in names
    result = file_preview(tmp_path, "src/hello.py")
    assert result["read_only"] and result["content"].replace("\r\n", "\n") == "print('hello')\n"
    with pytest.raises(ValueError, match="limit"):
        file_preview(tmp_path, "huge.txt")
    with pytest.raises(PermissionError):
        file_preview(tmp_path, ".env")


def test_project_path_rejects_traversal_links_and_hidden_metadata(tmp_path):
    (tmp_path / "hello.py").write_text("abc", encoding="utf-8")
    for unsafe in ("../hello.py", ".git/config", ".sentra/owner.lock", str(tmp_path / "hello.py")):
        with pytest.raises(PermissionError):
            file_preview(tmp_path, unsafe)
    linked = tmp_path / "alias.py"
    try:
        linked.symlink_to(tmp_path / "hello.py")
    except (OSError, NotImplementedError):
        pytest.skip("local symlinks require elevated privilege")
    with pytest.raises(PermissionError):
        file_preview(tmp_path, "alias.py")


def test_git_diff_read_only_is_bounded_and_no_commit(tmp_path):
    git = subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True)
    if git.returncode:
        pytest.skip("git unavailable")
    target = tmp_path / "doc.md"
    target.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "doc.md"], check=True)
    target.write_text("after\n", encoding="utf-8")
    diff = git_diff(tmp_path, "doc.md")
    assert diff["read_only"] and "+after" in diff["diff"] and "-before" in diff["diff"]
    assert target.read_text(encoding="utf-8") == "after\n"


def test_canvas_http_project_review_checks_owner_workspace_and_bearer(tmp_path):
    with running_canvas(tmp_path) as (app, server):
        ws = app.create_workspace("ProjectFiles")["id"]
        other = app.create_workspace("ProjectOther")["id"]
        root = Path(app.store.workspace(ws)["path"])
        (root / "src").mkdir()
        (root / "src" / "feature.py").write_text("def feature(): return True\n", encoding="utf-8")
        url = f"/api/center/project-review?ws={ws}&path=src&action=list"
        status, body = request(server, url)
        assert status == 200 and body["items"][0]["name"] == "feature.py"
        status, preview = request(server, f"/api/center/project-review?ws={ws}&path=src%2Ffeature.py&action=preview")
        assert status == 200 and "return True" in preview["content"]
        status, _ = request(server, url, authorized=False)
        assert status == 401
        status, _ = request(server, f"/api/center/project-review?ws={other}&path=src%2Ffeature.py&action=preview")
        assert status != 200
        status, _ = request(server, f"/api/center/project-review?ws={ws}&path=..%2F..&action=list")
        assert status == 403
