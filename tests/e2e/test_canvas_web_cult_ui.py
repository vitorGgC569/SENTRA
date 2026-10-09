"""Real Edge UI coverage for SENTRA Canvas Web navigation and physical cables."""
from __future__ import annotations
import os
import threading
from pathlib import Path
import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas

@pytest.mark.skipif(os.name!="nt", reason="Windows Edge/WebView2 target")
def test_web_command_palette_and_physics(tmp_path):
    pw=pytest.importorskip("playwright.sync_api")
    canvas=Canvas(tmp_path)
    ws=canvas.create_workspace("web_visual_qa")["id"]
    one=canvas.graph_note(ws,"Origem","Instrucoes",x=190,y=200)
    two=canvas.graph_note(ws,"Revisor","Resultados",x=760,y=260)
    link=canvas.graph_link(ws,one["id"],two["id"])
    server=CanvasServer(canvas,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with pw.sync_playwright() as p:
            browser=p.chromium.launch(channel="msedge",headless=True)
            try:
                page=browser.new_page(viewport={"width":1460,"height":850},reduced_motion="reduce")
                errors=[]
                page.on("pageerror",lambda err:errors.append(str(err)))
                page.goto(f"http://127.0.0.1:{server.server_port}/canvas#token={server.secret}")
                page.locator(".cable-line").wait_for(timeout=10000)
                page.wait_for_function("document.documentElement.classList.contains('fractal-ready') && document.querySelector('#fractal-grid').width > 200")
                background=page.evaluate("""() => {
                    const c=document.querySelector('#fractal-grid');
                    const color=[...c.getContext('2d').getImageData(2,2,1,1).data];
                    return {w:c.width,h:c.height,color,fps:window.SentraFractalGrid?.settings.fps};
                }""")
                assert background["w"]>500 and background["h"]>300
                assert max(background["color"][:3])<85,background
                assert background["fps"] <= 30
                assert page.locator(".cable-line").count()==1
                # Terminal creation exposes native Codex effort, not a cosmetic selector.
                page.locator('[data-tool="terminal"]').click()
                page.locator('#modal-form [name="shell"]').select_option("sentra-cli")
                assert page.locator('#terminal-model-wrap [name="effort"]').is_visible()
                assert page.locator('#terminal-model-wrap [name="effort"]').input_value()=="low"
                page.locator('#terminal-model-wrap [name="effort"]').select_option("high")
                assert page.locator('#terminal-model-wrap [name="effort"]').input_value()=="high"
                page.locator("#modal-cancel").click()
                assert page.locator(".native-titlebar").is_hidden()
                line=page.locator(".cable-line")
                assert line.get_attribute("data-edge")==link["id"]
                before=line.get_attribute("d")
                page.locator("#command-launch").click()
                page.locator("#command-query").fill("Revisor")
                page.locator(".command-result").first.click()
                assert page.locator("#inspector-title").inner_text()=="Revisor"
                assert page.locator("#inspector-tabs").is_visible()
                page.locator("#inspector-tab-connections").click()
                assert "Origem" in page.locator("#inspector-content").inner_text()
                page.locator("#inspector-tab-activity").click()
                assert page.locator("#inspector-content").is_visible()
                page.locator("#inspector-tab-details").click()
                canvas.graph_move(ws,two["id"],1080,490)
                page.evaluate("refreshResources()")
                page.wait_for_timeout(150)
                assert line.get_attribute("d") != before
                page.keyboard.press("Control+k")
                assert page.locator("#command-overlay").is_visible()
                page.locator("#command-query").fill("Revisor")
                assert page.locator("#command-clear").is_visible()
                page.locator("#command-clear").click()
                assert page.locator("#command-query").input_value()==""
                page.keyboard.press("Escape")  # Close the modal command overlay first.
                assert page.locator("#command-overlay").is_hidden()
                page.evaluate('toast("Operação confirmada","success")')
                assert page.locator(".halo-toast[data-tone=success]").count()==1
                page.locator(".halo-toast button").click()
                assert page.locator(".halo-toast").count()==0
                page.keyboard.press("Escape")
                assert page.locator("#command-overlay").is_hidden()
                assert not errors,errors
                page.locator("#fit-nodes").click()
                page.wait_for_timeout(180)
                evidence=Path(__file__).resolve().parents[2]/".sentra"/"canvas"/"evidence"
                evidence.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(evidence/"cult-dark-fractal-web.png"),full_page=True)
            finally:
                browser.close()
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close();canvas.shutdown()

@pytest.mark.skipif(os.name!="nt", reason="Windows ConPTY required")
def test_prompt_composer_handoff_to_connected_terminal(tmp_path):
    """Echo-only ConPTY receiver: verifies transport, never claims model inference."""
    pw=pytest.importorskip("playwright.sync_api")
    app=Canvas(tmp_path)
    ws=app.create_workspace("composer_transport")["id"]
    server=CanvasServer(app,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        source=app.graph_note(ws,"Solicitante","Instruções",x=200,y=210)
        receiver=app._start(ws,"echo_receiver","sentra-cli",["cmd.exe","/Q","/K"])
        graph=app.graph_detail(ws)
        destination=next(n for n in graph["nodes"]
                         if n["kind"]=="terminal" and n["resource_id"]==receiver["id"])
        app.graph_link(ws,source["id"],destination["id"])
        with pw.sync_playwright() as p:
            browser=p.chromium.launch(channel="msedge",headless=True)
            try:
                page=browser.new_page(viewport={"width":1440,"height":900})
                errors=[]
                page.on("pageerror",lambda err:errors.append(str(err)))
                page.goto(f"http://127.0.0.1:{server.server_port}/canvas#token={server.secret}")
                page.locator(".cable-line").wait_for(timeout=10000)
                assert page.locator(".session-nav-item").count()>=1
                assert page.locator(".cli-controls button").count()==2
                assert page.locator(".session-nav-item").filter(has_text="echo_receiver").count()==1
                page.locator("#fit-nodes").click()
                page.wait_for_timeout(200)
                evidence=Path(__file__).resolve().parents[2]/".sentra"/"canvas"/"evidence"
                evidence.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(evidence/"sentra-maestri-terminal-rail.png"),full_page=True)
                page.locator("#command-launch").click()
                page.locator("#command-query").fill("Solicitante")
                page.locator(".command-result").first.click()
                page.locator("#inspector-tab-connections").click()
                page.locator('#inspector-content [data-inspect-action="handoff"]').click()
                assert page.locator(".prompt-composer-shell").is_visible()
                entry=page.locator('[name="message"]')
                entry.fill("echo CULT_COMPOSER_OK\n")
                assert "22 / 4000" in page.locator("#composer-count").inner_text()
                entry.press("Control+Enter")
                page.locator(".modal-shade").wait_for(state="hidden",timeout=10000)
                assert "CULT_COMPOSER_OK" in app.terminal_output(ws,receiver["id"])["text"] or (
                    app.graph.handoffs(ws) and app.graph.handoffs(ws)[0]["status"]=="sent")
                assert app.graph.handoffs(ws)[0]["status"]=="sent"
                assert not errors,errors
            finally:
                browser.close()
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close();app.shutdown()
