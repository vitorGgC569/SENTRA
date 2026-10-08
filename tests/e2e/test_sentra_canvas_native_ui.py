"""End-to-end native graph surface via the same WebView2-compatible DOM runtime."""
from __future__ import annotations
import os
import threading
from pathlib import Path
import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas

@pytest.mark.skipif(os.name!="nt",reason="requires Windows/Edge")
def test_native_canvas_graph_ui(tmp_path):
    pw=pytest.importorskip("playwright.sync_api")
    canvas=Canvas(tmp_path)
    server=CanvasServer(canvas)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with pw.sync_playwright() as p:
            browser=p.chromium.launch(channel="msedge",headless=True)
            try:
                page=browser.new_page(viewport={"width":1550,"height":920},device_scale_factor=1)
                errors=[]
                page.on("pageerror",lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/native.html#token={server.secret}")
                page.locator("#onboarding-action").click()
                assert page.locator("#modal-title").inner_text()=="Novo workspace"
                page.locator('[name="name"]').fill("desktop_e2e")
                page.locator("#modal-submit").click()
                page.locator("#current-project").get_by_text("desktop_e2e").wait_for(timeout=10000)
                page.locator('[data-tool="terminal"]').click()
                assert page.locator('[name="shell"] option[value="sentra-cli"]').count()==1
                assert page.locator('[name="shell"] option[value="codex"]').count()==1
                assert page.locator('[name="shell"] option[value="antigravity-app"]').count()==1
                page.locator('[name="name"]').fill("shell_e2e")
                page.locator('[name="shell"]').select_option("cmd")
                page.locator("#modal-submit").click()
                page.locator(".node.terminal").wait_for(timeout=10000)
                assert page.locator(".node.terminal").count()==1
                page.locator("[data-terminal-input]").fill("echo NATIVE_CONPTY_OK")
                page.locator("[data-terminal-input]").press("Enter")
                page.locator(".term-output").get_by_text("NATIVE_CONPTY_OK", exact=True).first.wait_for(timeout=10000)
                page.locator('[data-tool="agent"]').click()
                page.locator('[name="name"]').fill("sentra_worker")
                page.locator('[name="start"]').uncheck()
                page.locator("#modal-submit").click()
                page.locator(".node.agent").wait_for(timeout=10000)
                page.locator('[data-tool="note"]').click()
                page.locator('[name="title"]').fill("Contexto")
                page.locator('[name="body"]').fill("Plano em andamento")
                page.locator("#modal-submit").click()
                page.locator(".node.note").wait_for(timeout=10000)
                assert page.locator(".node").count()==3
                page.locator(".node.terminal .node-header").click()
                ports=page.locator(".node.terminal .node-port.output")
                ports.click(timeout=3000)
                page.locator(".node.agent .node-port.input").click()
                page.locator(".edge-line").wait_for(timeout=10000)
                assert page.locator(".edge-line").count()==1
                page.locator("#fit-nodes").click()
                assert page.locator("#zoom-label").inner_text().endswith("%")
                # Drag a note by its titlebar and verify it writes persisted layout.
                node=page.locator(".node.note")
                header=node.locator(".node-header")
                bounds=header.bounding_box()
                assert bounds is not None
                x,y=bounds["x"]+75,bounds["y"]+14
                before=canvas.graph_detail(canvas.workspaces()[0]["id"])["nodes"]
                previous=next(n for n in before if n["kind"]=="note")
                page.mouse.move(x,y);page.mouse.down()
                page.mouse.move(x+110,y+50,steps=6);page.mouse.up()
                page.wait_for_timeout(600)
                after=canvas.graph_detail(canvas.workspaces()[0]["id"])["nodes"]
                current=next(n for n in after if n["kind"]=="note")
                assert current["x"] != previous["x"]
                evidence=Path(__file__).resolve().parents[2]/".sentra"/"canvas"/"evidence"
                evidence.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(evidence/"native-canvas-e2e.png"),full_page=True)
                assert not errors,errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)
        canvas.shutdown()
