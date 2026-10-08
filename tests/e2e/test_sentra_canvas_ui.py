"""Real Edge headless E2E for SENTRA's independent desktop canvas."""
from __future__ import annotations
import os
import threading
import time
from pathlib import Path
import pytest
from sentra_canvas.service import Canvas
from sentra_canvas.__main__ import CanvasServer

@pytest.mark.skipif(os.name!="nt",reason="Windows Edge/ConPTY integration")
def test_canvas_browser_end_to_end(tmp_path):
    playwright=pytest.importorskip("playwright.sync_api")
    app=Canvas(tmp_path)
    server=CanvasServer(app)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            try:
                browser=p.chromium.launch(channel="msedge",headless=True)
            except Exception as exc:
                pytest.skip("Edge browser not available: "+str(exc)[:120])
            try:
                page=browser.new_page(viewport={"width":1440,"height":960})
                page.goto(f"http://127.0.0.1:{server.server_port}/#token={server.secret}")
                page.locator("#ws-name").fill("projeto_um")
                page.locator("#new-ws button").click()
                page.locator("#ws-title").get_by_text("projeto_um").wait_for(timeout=10000)
                page.locator("#terminal-name").fill("console_1")
                page.locator("#terminal-shell").select_option("cmd")
                page.locator("#new-terminal button").click()
                page.locator(".terminal").first.wait_for()
                page.locator("#terminal-name").fill("console_2")
                page.locator("#new-terminal button").click()
                page.locator(".terminal").nth(1).wait_for(timeout=10000)
                assert page.locator(".terminal").count()==2
                page.locator("#ws-name").fill("projeto_dois")
                page.locator("#new-ws button").click()
                page.locator("#ws-title").get_by_text("projeto_dois").wait_for(timeout=10000)
                page.locator("#terminal-name").fill("console_3")
                page.locator("#terminal-shell").select_option("cmd")
                page.locator("#new-terminal button").click()
                page.locator(".terminal").filter(has_text="console_3").wait_for(timeout=10000)
                assert page.locator(".terminal").count()==1
                page.locator("[data-ws]").filter(has_text="projeto_um").click()
                page.locator("#ws-title").get_by_text("projeto_um").wait_for(timeout=10000)
                page.locator(".terminal").filter(has_text="console_2").wait_for(timeout=10000)
                assert page.locator(".terminal").count()==2
                page.locator("[data-input]").first.fill("echo UI_CONPTY_LIVE")
                page.locator("[data-input]").first.press("Enter")
                page.get_by_text("UI_CONPTY_LIVE").first.wait_for(timeout=10000)
                for name,role in (("coord","coordinator"),("dev_a","worker"),
                                  ("dev_b","worker")):
                    page.locator("#agent-name").fill(name)
                    page.locator("#agent-role").select_option(role)
                    page.locator("#new-agent button").click()
                    page.locator("#agents").get_by_text(name,exact=True).wait_for()
                ids={o.inner_text():o.get_attribute("value")
                     for o in page.locator("#team-coordinator option").all()
                     if o.get_attribute("value")}
                page.locator("#team-name").fill("time_demo")
                page.locator("#team-coordinator").select_option(ids["coord"])
                page.locator("#team-workers").select_option([ids["dev_a"],ids["dev_b"]])
                page.locator("#new-team button").click()
                page.locator("#teams").get_by_text("time_demo").wait_for()
                team_id=page.locator("#task-team option").last.get_attribute("value")
                page.locator("#task-team").select_option(team_id)
                page.locator("#task-worker").select_option(ids["dev_a"])
                page.locator("#task-prompt").fill("Validação local do pipeline")
                page.locator("#new-task button").click()
                page.locator("#tasks").get_by_text("PROVEDOR DE TESTE",exact=False).wait_for(timeout=12000)
                evidence=Path(__file__).resolve().parents[2]/".sentra"/"canvas"/"evidence"
                evidence.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(evidence/"canvas-e2e.png"),full_page=True)
                assert page.locator("#events .event").count()>0
            finally:
                browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
        app.shutdown()
