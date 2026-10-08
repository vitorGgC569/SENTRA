"""Real keyboard, ConPTY, VT color/cursor rendering, resize and page reattachment."""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas


@pytest.mark.skipif(os.name != "nt", reason="Windows ConPTY and Edge required")
def test_native_terminal_keyboard_vt_resize_and_reattachment(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    canvas = Canvas(tmp_path)
    server = CanvasServer(canvas)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        ws = canvas.create_workspace("vt_terminal")["id"]
        workspace = Path(canvas.store.workspace(ws)["path"])
        (workspace / "vt_qa.py").write_text(
            "from pathlib import Path\nimport os\n"
            "Path('keyboard-effect.txt').write_text('executed once')\n"
            "print('\\x1b[2J\\x1b[H\\x1b[31mVT_COLOR_OK\\x1b[0m', flush=True)\n"
            "print('\\x1b[3;8HVT_POSITION_OK', flush=True)\n"
            "Path('terminal-size.txt').write_text(str(os.get_terminal_size()))\n",
            encoding="utf-8",
        )
        terminal = canvas.create_terminal(ws, "interactive", "cmd")
        with pw.sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1550, "height": 920})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                url = f"http://127.0.0.1:{server.server_port}/native.html#token={server.secret}"
                page.goto(url)
                entry = page.locator(".xterm-helper-textarea")
                entry.wait_for()
                page.wait_for_timeout(250)  # Initial viewport resize is debounced.
                entry.focus()
                page.keyboard.type("python vt_qa.py")
                page.keyboard.press("Enter")
                page.locator(".term-output .xterm-fg-1").get_by_text("VT_COLOR_OK", exact=True).wait_for(timeout=10000)
                assert (workspace / "keyboard-effect.txt").read_text() == "executed once"
                page.wait_for_function("""() => {
                    const term=[...terminalViews.values()][0]?.term;
                    return term?.buffer.active.getLine(2)?.translateToString(true).startsWith('       VT_POSITION_OK');
                }""")
                before = page.evaluate("()=>{const t=[...terminalViews.values()][0].term;return [t.cols,t.rows]}")
                node = next(n for n in canvas.graph_detail(ws)["nodes"] if n["kind"] == "terminal")
                canvas.graph_resize(ws, node["id"], 800, 500)
                page.wait_for_function("([cols,rows])=>{const t=[...terminalViews.values()][0]?.term;return t&&(t.cols!==cols||t.rows!==rows)}", arg=before)
                assert (workspace / "terminal-size.txt").is_file()
                # Reload must recover the VT stream while retaining the actual process.
                pid = terminal["pid"]
                page.reload()
                page.locator(".term-output").get_by_text("VT_COLOR_OK", exact=True).first.wait_for(timeout=10000)
                assert canvas.workspace_detail(ws)["terminals"][0]["pid"] == pid
                assert errors == [], errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        canvas.shutdown()
