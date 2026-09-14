"""Real headless-Edge capture. Gated: skips honestly when Edge is absent
(CI has no Edge). Proves the exact production path, not a stub."""
import pytest

from orchestrator.visual_evidence import capture_html_screenshot, find_edge

pytestmark = pytest.mark.skipif(not find_edge(), reason="headless Edge unavailable")


def test_real_capture_produces_valid_png(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(
        "<!doctype html><html><body><h1 id='hero'>Oi</h1></body></html>",
        encoding="utf-8")
    out = tmp_path / "render-1.png"
    rec = capture_html_screenshot(html, out, width=800, height=600, timeout_s=120)
    assert rec["ok"] is True, rec
    raw = out.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) == rec["bytes"]
