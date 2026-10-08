"""The actual Canvas DOM must attach to a workspace already owned by the broker."""
import os
import threading

import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas


@pytest.mark.skipif(os.name != "nt", reason="Windows ConPTY and Edge required")
def test_native_ui_initially_loads_an_existing_live_workspace(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    canvas = Canvas(tmp_path)
    server = CanvasServer(canvas)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        ws = canvas.create_workspace("existing_owner")["id"]
        terminal = canvas.create_terminal(ws, "persistent", "cmd")
        canvas.terminal_input(ws, terminal["id"], "echo EXISTING_OWNER_OUTPUT\r")
        with pw.sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1550, "height": 920})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/native.html#token={server.secret}")
                page.locator("#current-project").get_by_text("existing_owner", exact=True).wait_for(timeout=10000)
                page.locator(".term-output").get_by_text("EXISTING_OWNER_OUTPUT", exact=True).first.wait_for(timeout=10000)
                assert errors == []
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        canvas.shutdown()
