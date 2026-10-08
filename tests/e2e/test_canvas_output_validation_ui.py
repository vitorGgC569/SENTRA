import os
from pathlib import Path
import threading

import pytest

from sentra_canvas.service import Canvas
from sentra_canvas.__main__ import CanvasServer
from tests.unit.test_canvas_task_queue import team,wait


@pytest.mark.skipif(os.name!="nt",reason="actual Edge, protected stores and CLI")
def test_ui_declares_checks_and_completes_without_duplicate_consent(tmp_path):
    pw=pytest.importorskip("playwright.sync_api")
    app=Canvas(tmp_path)
    server=CanvasServer(app)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        ws,group,workers=team(app)
        with pw.sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel="msedge",headless=True)
            try:
                page=browser.new_page(viewport={"width":1550,"height":920})
                errors=[];dialogs=[]
                page.on("pageerror",lambda error:errors.append(str(error)))
                page.on("dialog",lambda dialog:(dialogs.append(dialog.type),dialog.dismiss()))
                page.goto(f"http://127.0.0.1:{server.server_port}/native.html#token={server.secret}")
                page.locator(".node.team .node-cta").click()
                assert page.locator('[name="provider"]').input_value()=="sentra-cli"
                page.locator('[name="prompt"]').fill("[[W|ui_checked.txt|UI_REAL_CHECK]]")
                page.locator('[name="check_path"]').fill("ui_checked.txt")
                page.locator('[name="check_text"]').fill("UI_REAL_CHECK")
                page.locator("#modal-submit").click()
                task=wait(lambda:next(iter(app.store.list_resources("tasks",ws)),None))
                wait(lambda:app._runtime().work_item(task)["state"]=="COMPLETED")
                assert Path(app.store.workspace(ws)["path"],"ui_checked.txt").read_text()=="UI_REAL_CHECK"
                page.locator("#events-button").click()
                page.locator("#inspector-content").get_by_text("Critérios verificados",exact=False).wait_for()
                page.get_by_role("button",name="Reverificar arquivos",exact=True).click()
                page.locator("#inspector-content").get_by_text("Critérios verificados",exact=False).wait_for()
                assert not dialogs and not errors
            finally:browser.close()
    finally:
        server.shutdown();thread.join(5);server.server_close();app.shutdown()
