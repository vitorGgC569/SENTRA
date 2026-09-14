"""Visual evidence pipeline: protocol caps, provider loading, capture helper.

No browser, no network, no Edge required (capture executes only when the
Edge binary exists; failure paths are pure). Live paste is verified by the
extension reporting images_attached per job (see dashboard relay jobs).
"""
import base64
import json

from native_bridge.protocol import (
    ChatJob, ChatResult, MAX_IMAGES_PER_JOB, MAX_IMAGE_CHARS,
)


def _png(n=200):
    return b"\x89PNG\r\n\x1a\n" + b"x" * n


def _url(raw=None):
    return "data:image/png;base64," + base64.b64encode(raw or _png()).decode("ascii")


def test_job_without_images_validates():
    ChatJob(task_id="T-1", prompt="ola", timeout_s=60).validate()


def test_job_images_capped_by_count_format_and_size():
    ok = ChatJob(task_id="T-1", prompt="p", timeout_s=60, images=[_url(), _url()])
    ok.validate()
    bad_count = ChatJob(task_id="T-1", prompt="p", timeout_s=60,
                        images=[_url()] * (MAX_IMAGES_PER_JOB + 1))
    try:
        bad_count.validate()
    except ValueError:
        pass
    else:
        raise AssertionError("count cap not enforced")
    bad_fmt = ChatJob(task_id="T-1", prompt="p", timeout_s=60,
                      images=["https://example.com/a.png"])
    try:
        bad_fmt.validate()
    except ValueError:
        pass
    else:
        raise AssertionError("format not enforced")
    big = _png(MAX_IMAGE_CHARS)
    bad_size = ChatJob(task_id="T-1", prompt="p", timeout_s=60, images=[_url(big)])
    try:
        bad_size.validate()
    except ValueError:
        pass
    else:
        raise AssertionError("size cap not enforced")


def test_result_carries_images_attached_telemetry():
    r = ChatResult(job_id="j", task_id="T-1", status="COMPLETED",
                   result="ok", images_attached=1)
    r.validate()
    assert json.loads(json.dumps(r.to_dict()))["images_attached"] == 1


def test_provider_loads_png_paths_and_refuses_gracefully(tmp_path):
    from orchestrator.providers.extension_provider import _load_image_attachments
    assert _load_image_attachments(None) is None
    assert _load_image_attachments([]) is None
    good = tmp_path / "render-1.png"
    good.write_bytes(_png())
    urls = _load_image_attachments([str(good)])
    assert isinstance(urls, list) and urls[0].startswith("data:image/png;base64,")
    missing = _load_image_attachments([str(tmp_path / "nope.png")])
    assert isinstance(missing, str) and missing.startswith("[IMAGE_ERROR]")
    txt = tmp_path / "note.txt"
    txt.write_text("hello", encoding="utf-8")
    assert _load_image_attachments([str(txt)]).startswith("[IMAGE_ERROR]")
    big = tmp_path / "big.png"
    big.write_bytes(_png(MAX_IMAGE_CHARS))
    assert _load_image_attachments([str(big)]).startswith("[IMAGE_ERROR]")
    many = _load_image_attachments([str(good)] * (MAX_IMAGES_PER_JOB + 1))
    assert isinstance(many, str) and "at most" in many


def test_capture_helper_validates_without_edge(tmp_path):
    from orchestrator import visual_evidence as ve
    html = tmp_path / "index.html"
    html.write_text("<html><body>oi</body></html>", encoding="utf-8")
    # No Edge here and bogus edge path: must fail closed, never raise.
    rec = ve.capture_html_screenshot(html, tmp_path / "out.png", edge="nope.exe")
    assert rec == {"ok": False, "error": "headless Edge not found; evidence unavailable"}
    rec = ve.capture_html_screenshot(tmp_path / "missing.html", tmp_path / "o.png")
    assert rec["ok"] is False
    rec = ve.capture_html_screenshot(html, tmp_path / "o.png", width="xx")
    assert rec["ok"] is False


def test_capture_rejects_non_png_output(tmp_path, monkeypatch):
    from orchestrator import visual_evidence as ve
    import subprocess

    html = tmp_path / "index.html"
    html.write_text("<html></html>", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        out = None
        for a in cmd:
            if a.startswith("--screenshot="):
                out = a.split("=", 1)[1]
        open(out, "wb").write(b"not a png")
        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(ve, "find_edge", lambda explicit=None: "edge.exe")
    rec = ve.capture_html_screenshot(html, tmp_path / "o.png")
    assert rec["ok"] is False and "PNG" in rec["error"]


def test_capture_task_renders_caps_at_two_and_skips_failures(tmp_path, monkeypatch):
    from orchestrator import visual_evidence as ve
    monkeypatch.setattr(ve, "capture_html_screenshot",
                        lambda *a, **k: {"ok": False, "error": "x"})
    recs = ve.capture_task_renders(["a.html", "b.html", "c.html"], tmp_path)
    assert recs == []
