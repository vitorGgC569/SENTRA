"""Real Edge/ConPTY coverage for native canvas interactions and delivery retries."""
from __future__ import annotations

import os
import threading

import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows ConPTY and Edge required")


@pytest.fixture
def native_ui(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    canvas = Canvas(tmp_path)
    server = CanvasServer(canvas)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pw.sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 760})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                url = f"http://127.0.0.1:{server.server_port}/native.html#token={server.secret}"
                yield canvas, page, url, tmp_path
                assert errors == [], errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        canvas.shutdown()


def test_background_pan_expand_restore_keeps_real_terminal(native_ui):
    canvas, page, url, evidence = native_ui
    ws = canvas.create_workspace("navigation")["id"]
    terminal = canvas.create_terminal(ws, "interactive", "cmd")
    page.goto(url)
    entry = page.locator(".xterm-helper-textarea")
    entry.wait_for()
    page.wait_for_timeout(250)
    entry.focus()
    page.keyboard.type("echo CANVAS_REAL_PROCESS")
    page.keyboard.press("Enter")
    page.locator(".term-output").get_by_text("CANVAS_REAL_PROCESS", exact=True).first.wait_for()
    page.evaluate("window.qaTerminal = [...terminalViews.values()][0].term")

    before = page.evaluate("[state.x,state.y]")
    viewport = page.locator("#viewport").bounding_box()
    assert viewport
    x, y = viewport["x"] + 80, viewport["y"] + viewport["height"] - 110
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 105, y - 45, steps=8)
    page.mouse.up()
    after = page.evaluate("[state.x,state.y]")
    assert after == [before[0] + 105, before[1] - 45]
    assert page.evaluate("state.move === null")
    assert "panning" not in page.locator("#viewport").get_attribute("class")

    layout = canvas.graph_detail(ws)["nodes"]
    camera = page.evaluate("[state.x,state.y,state.scale]")
    page.locator(".node.terminal .node-title").dblclick()
    page.locator("#terminal-stage .node.expanded").wait_for()
    bounds = page.locator("#terminal-stage .node").bounding_box()
    assert bounds and bounds["width"] > 1000 and bounds["height"] > 650
    assert page.evaluate("window.qaTerminal === [...terminalViews.values()][0].term")
    page.wait_for_function("() => window.qaTerminal.cols > 100")
    assert page.locator('#terminal-stage [data-node-action="expand"]').get_attribute("aria-expanded") == "true"
    page.screenshot(path=str(evidence / "terminal-expanded.png"))

    # Input in the expanded surface still reaches the original ConPTY process.
    page.locator("#terminal-stage [data-terminal-input]").fill("echo EXPANDED_PROCESS_INPUT")
    page.locator("#terminal-stage [data-terminal-input]").press("Enter")
    page.locator(".term-output").get_by_text("EXPANDED_PROCESS_INPUT", exact=True).first.wait_for()
    page.locator("#terminal-stage .node-title").dblclick()
    assert page.locator("#terminal-stage").is_hidden()
    assert canvas.graph_detail(ws)["nodes"] == layout
    assert page.evaluate("[state.x,state.y,state.scale]") == camera
    assert canvas.workspace_detail(ws)["terminals"][0]["pid"] == terminal["pid"]
    assert page.evaluate("window.qaTerminal === [...terminalViews.values()][0].term")

    page.locator('[data-node-action="expand"]').click()
    page.keyboard.press("Escape")
    assert page.locator("#terminal-stage").is_hidden()
    page.reload()
    page.locator(".term-output").get_by_text("EXPANDED_PROCESS_INPUT", exact=True).first.wait_for()
    assert canvas.workspace_detail(ws)["terminals"][0]["pid"] == terminal["pid"]


def test_agent_node_exposes_genuine_cli_and_saved_output(native_ui):
    canvas, page, url, evidence = native_ui
    ws = canvas.create_workspace("agent_session")["id"]
    agent = canvas.create_agent(ws, "real_worker", "sentra/codex/current", start=True)
    terminal_id = agent["terminal_id"]
    page.goto(url)
    node = page.locator(".node.agent")
    node.locator(".xterm-helper-textarea").wait_for()
    # These are genuine CLI diagnostics, not fabricated conversation/model replies.
    node.locator(".term-output").get_by_text("SENTRA CLI v1.1", exact=False).first.wait_for(timeout=30000)
    assert page.locator(".terminal-emulator").count() == 1
    assert page.locator(".node.terminal .session-reference").count() == 1
    node.locator("[data-terminal-input]").fill("/session")
    node.locator("[data-terminal-input]").press("Enter")
    page.wait_for_function(
        "id => {const b=[...terminalViews.values()][0].term.buffer.active;"
        "const text=Array.from({length:b.length},(_,i)=>b.getLine(i).translateToString()).join('\\n');"
        "return text.includes(id)&&text.includes('uncertain_calls')}",
        arg=agent["conversation_id"],
    )
    transcript = canvas.terminal_output(ws, terminal_id)["text"]
    assert agent["conversation_id"] in transcript
    pid = canvas.workspace_detail(ws)["terminals"][0]["pid"]
    page.screenshot(path=str(evidence / "agent-real-cli.png"))
    page.reload()
    node.locator(".xterm-helper-textarea").wait_for()
    node.locator(".term-output").get_by_text("SENTRA CLI v1.1", exact=False).first.wait_for(timeout=10000)
    assert canvas.workspace_detail(ws)["terminals"][0]["pid"] == pid
    assert canvas.workspace_detail(ws)["agents"][0]["conversation_id"] == agent["conversation_id"]
    page.locator('.node.terminal [data-node-action="open-session"]').click()
    assert page.locator("#terminal-stage .node.agent.expanded").count() == 1


def test_task_lost_response_retries_same_delivery_and_locks_submit(native_ui):
    canvas, page, url, _ = native_ui
    ws = canvas.create_workspace("retry_delivery")["id"]
    coordinator = canvas.create_agent(ws, "coordinator", "sentra/codex/current", role="coordinator")
    worker = canvas.create_agent(ws, "worker", "sentra/codex/current")
    canvas.create_team(ws, "test_team", coordinator["id"], [worker["id"]])
    page.goto(url)
    page.locator('.node.team [data-node-action="delegate"]').click()
    page.locator('[name="provider"]').select_option("test")
    page.locator('[name="agent"]').select_option(worker["id"])
    page.locator('[name="prompt"]').fill("delivery retry regression, explicitly no model inference")
    assert page.evaluate("document.querySelector('#modal-form').checkValidity()"), page.evaluate("Array.from(document.querySelector('#modal-form').elements).filter(e=>!e.validity.valid).map(e=>[e.name,e.value,e.validationMessage])")
    deliveries = []

    def lose_first_response(route):
        deliveries.append(route.request.post_data_json)
        assert page.locator("#modal-submit").is_disabled()
        assert page.locator("#modal-cancel").is_disabled()
        # The real server receives it; only its first response is deliberately lost.
        response = route.fetch()
        if len(deliveries) == 1:
            route.abort("failed")
        else:
            route.fulfill(response=response)

    page.route("**/api/tasks", lose_first_response)
    page.evaluate("document.querySelector('#modal-form').requestSubmit();document.querySelector('#modal-form').requestSubmit()")
    try:
        page.wait_for_function("() => document.querySelector('#modal-submit').textContent==='Tentar novamente'", timeout=5000)
    except Exception:
        pytest.fail(str({"deliveries": len(deliveries), "ui": page.evaluate("({kind:modalKind,sending:modalSending,button:document.querySelector('#modal-submit').textContent,toast:document.querySelector('#toast').textContent,hidden:document.querySelector('#modal-shade').hidden})")}))
    assert len(deliveries) == 1
    assert page.locator('[name="prompt"]').is_disabled()
    page.locator("#modal-submit").click()
    page.locator("#modal-shade").wait_for(state="hidden")
    assert len(deliveries) == 2
    assert deliveries[0] == deliveries[1]
    assert len(canvas.workspace_detail(ws)["tasks"]) == 1
    page.locator('.node.team [data-node-action="delegate"]').click()
    page.locator('[name="provider"]').select_option("test")
    page.locator('[name="agent"]').select_option(worker["id"])
    page.locator('[name="prompt"]').fill("a separate delivery")
    page.locator("#modal-submit").click()
    page.locator("#modal-shade").wait_for(state="hidden")
    assert deliveries[2]["request_key"] != deliveries[0]["request_key"]
    assert len(canvas.workspace_detail(ws)["tasks"]) == 2
