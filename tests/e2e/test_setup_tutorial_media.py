"""Playback of the actual bundled MP4s in Edge; no simulated page or requests."""
import os
import pytest
from sentra_remote.installer import docs_source

@pytest.mark.skipif(os.name != "nt", reason="actual Edge playback on Windows")
def test_bundled_setup_guide_loads_and_plays_both_local_videos():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page()
            page.goto((docs_source() / "onboarding_media/SENTRA_SETUP_GUIDE.html").resolve().as_uri())
            page.wait_for_function("[...document.querySelectorAll('video')].length === 2 && [...document.querySelectorAll('video')].every(v => v.readyState >= 1 && v.duration > 0 && Number.isFinite(v.duration))")
            page.evaluate("async () => {for (const v of document.querySelectorAll('video')) {v.muted=true; await v.play();}}")
            page.wait_for_function("[...document.querySelectorAll('video')].every(v => v.currentTime > 0 && !v.paused && !v.error)")
        finally:
            browser.close()
