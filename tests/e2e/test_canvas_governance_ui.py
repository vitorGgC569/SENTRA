"""Real Edge DOM, native broker and CLI admission controls."""
import os
from pathlib import Path
import threading

import pytest

from sentra_canvas.service import Canvas
from sentra_canvas.__main__ import CanvasServer
from tests.unit.test_canvas_task_queue import team, wait, terminal


@pytest.mark.skipif(os.name!="nt",reason="Windows/Edge/DPAPI")
def test_real_canvas_governance_controls(tmp_path):
    pw=pytest.importorskip("playwright.sync_api")
    app=Canvas(tmp_path)
    http=CanvasServer(app)
    server=threading.Thread(target=http.serve_forever,daemon=True)
    server.start()
    try:
        ws,group,workers=team(app)
        policy=app.budget_set(ws,"workspace",{"quota_usage":0})
        task=app.delegate(ws,group,workers[0],"[[W|ui_effect.txt|REAL_GOVERNANCE_UI]]",
                          "ui-effect","sentra-cli",True)
        app.task_control(ws,task["id"],"block")
        with pw.sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel="msedge",headless=True)
            try:
                page=browser.new_page(viewport={"width":1550,"height":920})
                errors=[]
                page.on("pageerror",lambda error:errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{http.server_port}/native.html#token={http.secret}")
                page.locator("#current-project").get_by_text("task_queue").wait_for(timeout=10000)
                page.locator("#events-button").click()
                page.locator("#inspector-content").get_by_text("Fluxo: Bloqueada",exact=False).wait_for()
                page.get_by_role("button",name="Liberar tarefa",exact=True).click()
                page.locator("#inspector-content").get_by_text("limite de orçamento",exact=False).wait_for()
                assert app.store.resource("tasks",task["id"],ws)["status"]=="queued"
                root=Path(app.store.workspace(ws)["path"])
                assert not (root/"ui_effect.txt").exists()
                app.budget_set(ws,"workspace",None,policy_id=policy["budget_policy_id"],enabled=False)
                assert wait(lambda:terminal(app,ws,task))["status"]=="succeeded"
                assert (root/"ui_effect.txt").read_text()=="REAL_GOVERNANCE_UI"
                # Refresh from the genuine broker before opening the inspector.
                page.reload()
                page.locator("#current-project").get_by_text("task_queue").wait_for(timeout=10000)
                page.locator("#events-button").click()
                page.locator("#inspector-content").get_by_text("Fluxo: Resultado aguarda validação",exact=False).wait_for()
                assert not errors,errors
            finally:
                browser.close()
    finally:
        http.shutdown();server.join(5);http.server_close();app.shutdown()
