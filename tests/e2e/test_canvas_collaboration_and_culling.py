"""Production Canvas/ControlPlane/Hocuspocus with actual browser clients."""
import json
import threading
from pathlib import Path

import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas


def test_two_native_clients_notes_undo_and_revocation(tmp_path):
    pw=pytest.importorskip("playwright.sync_api")
    app=Canvas(tmp_path,principal="local-owner")
    ws=app.create_workspace("Shared")["id"]
    first=app.graph_note(ws,"One","alpha",x=100,y=100)
    second=app.graph_note(ws,"Two","beta",x=550,y=100)
    server=CanvasServer(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with pw.sync_playwright() as runtime:
            browser=runtime.chromium.launch(headless=True)
            contexts=[browser.new_context(viewport={"width":1440,"height":900}) for _ in range(2)]
            pages=[context.new_page() for context in contexts]
            errors=[]
            for page in pages:
                page.on("pageerror",lambda error:errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/canvas#token={server.secret}")
                page.locator('[data-note="'+first["id"]+'"]').wait_for()
                page.locator("#show-collaboration").click()
                page.wait_for_function("collaboration.status().synced && collaboration.status().writable")
            one='[data-note="'+first["id"]+'"]';two='[data-note="'+second["id"]+'"]'
            pages[0].locator(one).fill("alpha from A")
            pages[1].wait_for_function("([selector,value])=>document.querySelector(selector)?.value===value",arg=[one,"alpha from A"])
            pages[1].locator(two).fill("beta from B")
            pages[0].wait_for_function("([selector,value])=>document.querySelector(selector)?.value===value",arg=[two,"beta from B"])
            pages[0].locator("#collab-undo").click()
            pages[1].wait_for_function("selector=>document.querySelector(selector)?.value==='alpha'",arg=one)
            assert pages[0].locator(two).input_value()=="beta from B"
            pages[0].locator("#show-collaboration").click()
            pages[0].wait_for_function("!collaboration.active()")
            pages[0].evaluate("refreshResources()")
            assert app.graph_detail(ws)["collaboration_revision"]>0
            assert not errors,errors
            for context in contexts:context.close()
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);app.shutdown()


@pytest.mark.parametrize("count",[100,500])
def test_actual_native_renderer_culls_and_keyboard_selects_nodes(tmp_path,count):
    pw=pytest.importorskip("playwright.sync_api")
    app=Canvas(tmp_path,principal="local-owner")
    ws=app.create_workspace("Large graph")["id"]
    for index in range(count):
        app.graph_note(ws,"Node "+str(index),"text",x=(index%25)*400,y=(index//25)*320)
    server=CanvasServer(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with pw.sync_playwright() as runtime:
            browser=runtime.chromium.launch(headless=True)
            page=browser.new_page(viewport={"width":1440,"height":900})
            page.goto(f"http://127.0.0.1:{server.server_port}/canvas#token={server.secret}")
            page.wait_for_function("count=>state.nodes.length===count",arg=count)
            metrics=page.evaluate("""async () => {
                const start=performance.now();state.scale=1;state.x=50;state.y=50;setView();
                await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
                const mounted=document.querySelectorAll('#node-layer .node').length;
                for(let i=0;i<30;i++){state.x=-i*100;state.y=-i*20;setView();await new Promise(requestAnimationFrame);}
                return {count:state.nodes.length,mounted,pan_ms:performance.now()-start};
            }""")
            assert 0<metrics["mounted"]<count
            page.locator("#viewport").focus();page.keyboard.press("End")
            page.wait_for_function("state.selected===state.nodes.at(-1).id")
            assert page.locator(".graph-announcement").inner_text().endswith("de "+str(count))
            (tmp_path/f"graph-{count}-metrics.json").write_text(json.dumps(metrics),encoding="utf-8")
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);app.shutdown()
