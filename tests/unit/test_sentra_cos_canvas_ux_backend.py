"""Chat 5: real passive PDF rasterization and confined, debounced SHA watcher."""
import base64
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from sentra_canvas.project_review import (
    MAX_PDF_RENDER_PNG, ProjectRevisionWatcher, pdf_visual_page, project_revision,
)


def make_pdf(path: Path, *, width=240, height=160, pages=2):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width, height=height)
    with path.open("wb") as output:
        writer.write(output)
    return path


@pytest.mark.parametrize(("dpi", "width", "height"), [(72, 240, 160), (90, 300, 200), (108, 360, 240)])
def test_pdf_visual_renders_actual_png_at_supported_windows_dpi(tmp_path, dpi, width, height):
    pytest.importorskip("pypdfium2")
    source = make_pdf(tmp_path / "layout.pdf")
    original = source.read_bytes()
    page = pdf_visual_page(tmp_path, "layout.pdf", page=2, dpi=dpi)
    png = base64.b64decode(page["image_base64"], validate=True)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert int.from_bytes(png[16:20], "big") == width
    assert int.from_bytes(png[20:24], "big") == height
    assert page["width"] == width and page["height"] == height
    assert page["pages"] == 2 and page["page"] == 2
    assert page["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert page["mime"] == "image/png" and page["rendered"] and page["read_only"]
    assert page["ocr_used"] is False and page["grants_created"] is False
    assert source.read_bytes() == original


def test_pdf_rejects_traversal_invalid_page_dpi_password_binary_and_pixel_bombs(tmp_path):
    pytest.importorskip("pypdfium2")
    make_pdf(tmp_path / "small.pdf")
    for filename in ("../small.pdf", "C:/Windows/system32/target.pdf"):
        with pytest.raises(PermissionError):
            pdf_visual_page(tmp_path, filename)
    for page, dpi in ((0, 72), (201, 72), (True, 72), (1, 144), (1, 90.0)):
        with pytest.raises(ValueError):
            pdf_visual_page(tmp_path, "small.pdf", page=page, dpi=dpi)
    (tmp_path / "invalid.pdf").write_bytes(b"%PDF-not-valid")
    with pytest.raises((ValueError, RuntimeError)):
        pdf_visual_page(tmp_path, "invalid.pdf")
    make_pdf(tmp_path / "huge.pdf", width=100000, height=100000, pages=1)
    with pytest.raises(RuntimeError, match="rejected"):
        pdf_visual_page(tmp_path, "huge.pdf")
    (tmp_path / ".env").write_text("hidden", encoding="utf-8")
    with pytest.raises(PermissionError):
        project_revision(tmp_path, ".env")
    with pytest.raises(PermissionError):
        project_revision(tmp_path, "small.pdf/../small.pdf")


def test_pdf_render_timeout_and_invalid_child_envelope_fail_closed(tmp_path, monkeypatch):
    make_pdf(tmp_path / "document.pdf", pages=1)
    def fail_timeout(*args, **kwargs):
        assert kwargs["timeout"] <= 5 and kwargs["input"].startswith(b"%PDF")
        assert args[0][1] == "-I"
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(subprocess, "run", fail_timeout)
    with pytest.raises(TimeoutError):
        pdf_visual_page(tmp_path, "document.pdf")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kw: SimpleNamespace(
        returncode=0, stdout=b"200,100,1\nnot-a-png"))
    with pytest.raises(ValueError, match="invalid PDF renderer output"):
        pdf_visual_page(tmp_path, "document.pdf")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kw: SimpleNamespace(
        returncode=0, stdout=b"100,100,1\n" + b"x" * (MAX_PDF_RENDER_PNG + 1)))
    with pytest.raises(ValueError, match="budget|invalid PDF renderer"):
        pdf_visual_page(tmp_path, "document.pdf")


def test_watcher_debounces_sha_revisions_and_never_writes(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("before\n", encoding="utf-8")
    watcher = ProjectRevisionWatcher(tmp_path, "notes.md", debounce_seconds=.35)
    assert watcher.poll(now=1.0)["state"] == "initial"
    assert watcher.poll(now=1.1)["state"] == "unchanged"
    source.write_text("in progress", encoding="utf-8")
    assert watcher.poll(now=1.2)["state"] == "pending"
    source.write_text("completed", encoding="utf-8")
    assert watcher.poll(now=1.3)["state"] == "pending"
    assert watcher.poll(now=1.5)["state"] == "pending"
    result = watcher.poll(now=1.7)
    assert result["state"] == "changed" and result["read_only"]
    assert result["grants_created"] is False
    assert source.read_text(encoding="utf-8") == "completed"
    assert watcher.poll(now=2.0)["state"] == "unchanged"
    source.write_text("before\n", encoding="utf-8")
    assert watcher.poll(now=2.1)["state"] == "pending"
    assert watcher.poll(now=2.5)["state"] == "changed"


def test_watcher_disallows_secrets_linked_paths_unsupported_files_and_oversize(tmp_path):
    (tmp_path / ".env").write_text("protected", encoding="utf-8")
    (tmp_path / "file.bin").write_bytes(b"abc")
    (tmp_path / "large.md").write_bytes(b"z" * (128 * 1024 + 1))
    for candidate in (".env", "file.bin", "../file.bin", "large.md"):
        with pytest.raises((PermissionError, ValueError)):
            ProjectRevisionWatcher(tmp_path, candidate).poll(now=1)
    with pytest.raises(ValueError):
        ProjectRevisionWatcher(tmp_path, "file.bin", debounce_seconds=0)
    (tmp_path / "normal.md").write_text("ok", encoding="utf-8")
    link = tmp_path / "sym.md"
    try:
        link.symlink_to(tmp_path / "normal.md")
    except (OSError, NotImplementedError):
        return
    with pytest.raises(PermissionError):
        ProjectRevisionWatcher(tmp_path, "sym.md").poll(now=1)


def test_pdf_missing_parser_does_not_install_or_escape_to_raw_browser(tmp_path, monkeypatch):
    import importlib.util
    from sentra_canvas.project_review import pdf_text_page
    source = make_pdf(tmp_path / "fallback.pdf", pages=2)
    sha_before = hashlib.sha256(source.read_bytes()).hexdigest()
    original = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name: None if name == "pypdfium2" else original(name))
    with pytest.raises(RuntimeError, match="not installed"):
        pdf_visual_page(tmp_path, "fallback.pdf", page=1)
    fallback = pdf_text_page(tmp_path, "fallback.pdf", page=1)
    assert fallback["read_only"] and not fallback["rendered"] and not fallback["ocr_used"]
    assert fallback["source_sha256"] == sha_before
    assert hashlib.sha256(source.read_bytes()).hexdigest() == sha_before


def test_concurrent_poll_calls_linearize_one_change_only(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    file = tmp_path / "shared.md"
    file.write_text("initial", encoding="utf-8")
    watcher = ProjectRevisionWatcher(tmp_path, "shared.md", debounce_seconds=.1)
    assert watcher.poll(now=1)["state"] == "initial"
    file.write_text("revision two", encoding="utf-8")

    def batch(now):
        barrier = Barrier(12)
        def read(_):
            barrier.wait(timeout=4)
            return watcher.poll(now=now)
        with ThreadPoolExecutor(max_workers=12) as pool:
            return list(pool.map(read, range(12)))

    first = batch(2)
    assert all(value["state"] == "pending" for value in first)
    second = batch(2.2)
    assert sum(value["state"] == "changed" for value in second) == 1
    assert sum(value["state"] == "unchanged" for value in second) == 11
    sha = hashlib.sha256(file.read_bytes()).hexdigest()
    assert all(value["sha256"] == sha for value in second)
    assert not any(value["grants_created"] for value in first + second)
    watcher.close()
    with pytest.raises(RuntimeError, match="closed"):
        watcher.poll(now=3)


def test_watcher_clock_reversal_nan_and_transient_disappearance_fail_closed(tmp_path):
    file = tmp_path / "race.py"
    file.write_text("initial", encoding="utf-8")
    watcher = ProjectRevisionWatcher(tmp_path, "race.py")
    assert watcher.poll(now=5)["state"] == "initial"
    for invalid in (float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="clock"):
            watcher.poll(now=invalid)
    with pytest.raises(ValueError, match="backward"):
        watcher.poll(now=4)
    # A same-directory rename is recoverable by physical file identity. A
    # disappearance outside that bounded directory must still fail closed.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    file.rename(elsewhere / "moved.py")
    with pytest.raises(FileNotFoundError):
        watcher.poll(now=6)
    assert watcher.committed == hashlib.sha256(b"initial").hexdigest()
    (elsewhere / "moved.py").rename(file)
    file.write_text("new", encoding="utf-8")
    assert watcher.poll(now=6)["state"] == "pending"
    assert watcher.poll(now=7)["state"] == "changed"


def test_watcher_recovers_a_verified_same_directory_rename_without_writing(tmp_path):
    source = tmp_path / "before.py"
    source.write_text("initial", encoding="utf-8")
    watcher = ProjectRevisionWatcher(tmp_path, source.name)
    first = watcher.poll(now=1)
    if watcher._identity is None:
        pytest.skip("filesystem does not expose stable rename identity")
    moved = source.rename(tmp_path / "after.py")
    renamed = watcher.poll(now=2)
    assert renamed["state"] == "renamed"
    assert renamed["path"] == "after.py" and renamed["previous_path"] == "before.py"
    assert renamed["read_only"] is True and renamed["grants_created"] is False
    assert renamed["sha256"] == first["sha256"] == watcher.committed
    assert moved.read_text(encoding="utf-8") == "initial"
    assert watcher.poll(now=3)["state"] == "unchanged"


def test_watcher_missing_file_identity_never_infers_a_rename_from_matching_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr("sentra_canvas.project_review._rename_identity", lambda *_: None)
    source = tmp_path / "before.py"
    source.write_text("same bytes", encoding="utf-8")
    watcher = ProjectRevisionWatcher(tmp_path, source.name)
    first = watcher.poll(now=1)
    source.rename(tmp_path / "after.py")
    with pytest.raises(FileNotFoundError):
        watcher.poll(now=2)
    assert watcher.relative == "before.py"
    assert watcher.committed == first["sha256"]


def test_watcher_unreadable_rename_preserves_original_path_and_committed_revision(tmp_path):
    source = tmp_path / "before.py"
    source.write_text("initial", encoding="utf-8")
    watcher = ProjectRevisionWatcher(tmp_path, source.name)
    first = watcher.poll(now=1)
    if watcher._identity is None:
        pytest.skip("filesystem does not expose stable rename identity")
    moved = source.rename(tmp_path / "after.py")
    moved.write_bytes(b"x" * (128 * 1024 + 1))
    with pytest.raises(ValueError, match="limit"):
        watcher.poll(now=2)
    assert watcher.relative == "before.py"
    assert watcher.committed == first["sha256"]
    assert watcher._last_now == 1
    moved.write_text("readable", encoding="utf-8")
    assert watcher.poll(now=2)["state"] == "renamed"
    assert watcher.poll(now=3)["state"] == "pending"
    assert watcher.poll(now=4)["state"] == "changed"


def test_watcher_replaced_rename_candidate_is_not_adopted(tmp_path, monkeypatch):
    from sentra_canvas import project_review
    source = tmp_path / "before.py"
    source.write_text("initial", encoding="utf-8")
    watcher = ProjectRevisionWatcher(tmp_path, source.name)
    first = watcher.poll(now=1)
    if watcher._identity is None:
        pytest.skip("filesystem does not expose stable rename identity")
    moved = source.rename(tmp_path / "after.py")
    replacement = tmp_path / "replacement.py"
    replacement.write_text("unrelated", encoding="utf-8")
    original_read = project_review.project_revision

    def replaced_after_read(root, relative):
        value = original_read(root, relative)
        if relative == moved.name:
            replacement.replace(moved)
        return value

    monkeypatch.setattr(project_review, "project_revision", replaced_after_read)
    with pytest.raises(FileNotFoundError, match="identity"):
        watcher.poll(now=2)
    assert watcher.relative == "before.py"
    assert watcher.committed == first["sha256"]
    assert watcher._last_now == 1
