"""Reusable real UI QA for source or installed Canvas; no mocked responses.

Run with Python + Playwright + Edge. Environment:
  SENTRA_QA_CANVAS_EXE: installed sentra-canvas.exe (omit for source)
  SENTRA_QA_ROOT: source repository or installed product directory
  SENTRA_QA_OUTPUT: evidence parent directory (defaults to system temp)
  SENTRA_QA_MODEL: agent model identifier (default sentra/codex/current)
  SENTRA_QA_BROWSER: Playwright browser channel (default msedge)

Creates and closes ONLY its own broker/Edge session in a unique state directory.
Never attaches to, shuts down, or reopens the user's main GUI/broker.
"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE))
from sentra_canvas.broker import read_endpoint  # noqa: E402


def run():
    from playwright.sync_api import sync_playwright

    executable = os.environ.get("SENTRA_QA_CANVAS_EXE")
    product = Path(os.environ.get("SENTRA_QA_ROOT") or (str(Path(executable).parent) if executable else str(SOURCE))).resolve()
    evidence = Path(os.environ.get("SENTRA_QA_OUTPUT") or tempfile.gettempdir()).resolve() / ("sentra-ui-qa-" + uuid.uuid4().hex[:12])
    state_dir = evidence / "isolated-state"
    evidence.mkdir(parents=True)
    command = [str(Path(executable).resolve())] if executable else [sys.executable, "-B", "-m", "sentra_canvas"]
    command += ["--root", str(product), "--state-dir", str(state_dir), "--broker", "--no-open"]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(SOURCE) + os.pathsep + environment.get("PYTHONPATH", "")
    report = {"mode": "installed" if executable else "source", "product_root": str(product), "evidence": str(evidence), "checks": {}}
    endpoint = None
    with (evidence / "broker.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=str(product), env=environment, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                endpoint = read_endpoint(state_dir)
                if endpoint:
                    break
                if process.poll() is not None:
                    raise RuntimeError("QA broker exited; inspect broker.log")
                time.sleep(.1)
            if endpoint is None or endpoint.pid != process.pid:
                raise RuntimeError("Could not verify the isolated QA broker identity")
            report["broker_pid"] = endpoint.pid
            report["runtime_id"] = endpoint.runtime_id
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def api(path, payload=None):
                request = urllib.request.Request(f"http://127.0.0.1:{endpoint.server_port}{path}",
                    data=None if payload is None else json.dumps(payload).encode("utf-8"),
                    headers={"Authorization": "Bearer " + endpoint.secret, "Content-Type": "application/json"})
                with opener.open(request, timeout=35) as response:
                    return json.load(response)

            report["static_sha256"] = {}
            for asset in ("native.js", "native.css", "native.html"):
                with opener.open(f"http://127.0.0.1:{endpoint.server_port}/{asset}", timeout=10) as response:
                    report["static_sha256"][asset] = hashlib.sha256(response.read()).hexdigest()

            workspace = api("/api/workspaces", {"name": "ui_real_qa"})
            ws = workspace["id"]
            terminal = api("/api/terminals", {"ws": ws, "name": "real_cmd", "shell": "cmd"})
            agent = api("/api/agents", {"ws": ws, "name": "real_agent", "role": "worker",
                "model": os.environ.get("SENTRA_QA_MODEL", "sentra/codex/current"), "start": True})
            report["workspace_id"] = ws
            report["conversation_id"] = agent["conversation_id"]
            original = api("/api/graph?ws=" + ws)
            agent_terminal = next(t for t in original["terminals"] if t["id"] == agent["terminal_id"])
            report["terminal_pids"] = [terminal["pid"], agent_terminal["pid"]]
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel=os.environ.get("SENTRA_QA_BROWSER", "msedge"), headless=True)
                try:
                    page = browser.new_page(viewport={"width": 1280, "height": 760})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{endpoint.server_port}/native.html#token={endpoint.secret}")
                    cmd = page.locator(f'[data-terminal-input="{terminal["id"]}"]')
                    cmd.wait_for()
                    cmd.fill("echo QA_REAL_PTY_MARKER>qa-pty-effect.txt & type qa-pty-effect.txt")
                    cmd.press("Enter")
                    page.locator(f'#term-{terminal["id"]}').get_by_text("QA_REAL_PTY_MARKER", exact=True).first.wait_for(timeout=15000)
                    effect = Path(workspace["path"]) / "qa-pty-effect.txt"
                    assert effect.read_text().strip() == "QA_REAL_PTY_MARKER"
                    report["checks"]["real_conpty_effect"] = True
                    agent_node = page.locator(".node.agent")
                    agent_node.locator(".xterm-helper-textarea").wait_for()
                    agent_node.locator(".term-output").get_by_text("SENTRA CLI v1.1", exact=False).first.wait_for(timeout=35000)
                    agent_node.locator("[data-terminal-input]").fill("/session")
                    agent_node.locator("[data-terminal-input]").press("Enter")
                    page.wait_for_function("id=>{const v=terminalViews.get(id);if(!v)return false;const b=v.term.buffer.active;"
                        "return Array.from({length:b.length},(_,i)=>b.getLine(i).translateToString()).join('\\n').includes('uncertain_calls')}",
                        arg=agent["terminal_id"], timeout=15000)
                    assert agent["conversation_id"] in api("/api/terminal/output?ws=" + ws + "&id=" + agent["terminal_id"])["text"]
                    report["checks"]["real_cli_inside_agent"] = True
                    assert page.locator(".terminal-emulator").count() == 2
                    page.screenshot(path=str(evidence / "01-real-xterm.png"))

                    # Find an actual uncovered background coordinate, then drag with the mouse.
                    point = page.evaluate("""()=>{const v=document.getElementById('viewport'),r=v.getBoundingClientRect();
                        for(let y=r.bottom-110;y>r.top+100;y-=40)for(let x=r.left+40;x<r.right-160;x+=40){
                          const hit=document.elementFromPoint(x,y);
                          if(v.contains(hit)&&!hit.closest('.node,.onboarding,.glass,#connection-hint'))return [x,y];
                        }throw Error('No canvas background found')}""")
                    before = page.evaluate("[state.x,state.y]")
                    page.mouse.move(*point)
                    page.mouse.down()
                    page.mouse.move(point[0] + 80, point[1] - 35, steps=8)
                    page.mouse.up()
                    assert page.evaluate("[state.x,state.y]") == [before[0] + 80, before[1] - 35]
                    report["checks"]["background_pan"] = True
                    page.screenshot(path=str(evidence / "02-background-pan.png"))
                    page.locator("#fit-nodes").click()
                    camera = page.evaluate("[state.x,state.y,state.scale]")
                    layout = api("/api/graph?ws=" + ws)["nodes"]
                    page.evaluate("window.qaAgentTerm=terminalViews.get(" + json.dumps(agent["terminal_id"]) + ").term")
                    agent_node.locator(".node-title").dblclick()
                    page.locator("#terminal-stage .node.agent.expanded").wait_for(timeout=5000)
                    page.wait_for_function("()=>window.qaAgentTerm.cols > 100")
                    assert page.evaluate("window.qaAgentTerm===terminalViews.get(" + json.dumps(agent["terminal_id"]) + ").term")
                    page.screenshot(path=str(evidence / "03-agent-expanded.png"))
                    page.locator("#terminal-stage .node-title").dblclick()
                    assert page.locator("#terminal-stage").is_hidden()
                    assert page.evaluate("[state.x,state.y,state.scale]") == camera
                    assert api("/api/graph?ws=" + ws)["nodes"] == layout
                    agent_node.locator('[data-node-action="expand"]').click()
                    page.keyboard.press("Escape")
                    assert page.locator("#terminal-stage").is_hidden()
                    report["checks"]["expand_restore_same_xterm_and_layout"] = True
                    page.screenshot(path=str(evidence / "04-restored.png"))
                    page.reload()
                    agent_node.locator(".term-output").get_by_text("SENTRA CLI v1.1", exact=False).first.wait_for(timeout=15000)
                    page.locator(f'#term-{terminal["id"]}').get_by_text("QA_REAL_PTY_MARKER", exact=True).first.wait_for(timeout=15000)
                    current = api("/api/graph?ws=" + ws)
                    assert [next(t for t in current["terminals"] if t["id"] == ident)["pid"]
                            for ident in [terminal["id"], agent["terminal_id"]]] == report["terminal_pids"]
                    assert current["agents"][0]["conversation_id"] == agent["conversation_id"]
                    report["checks"]["reload_keeps_processes_and_saved_output"] = True
                    page.screenshot(path=str(evidence / "05-reloaded-history.png"))
                    assert errors == [], errors
                    report["checks"]["no_javascript_errors"] = True
                    report["model_inference_tested"] = False
                    report["result"] = "PASSED"
                finally:
                    browser.close()
        except BaseException as error:
            report["result"] = "FAILED"
            report["error"] = type(error).__name__ + ": " + str(error)
            raise
        finally:
            # Guard cleanup by both newly created PID and unique state-directory ownership.
            if endpoint is not None and endpoint.pid == process.pid and process.poll() is None:
                try:
                    endpoint.request("/api/runtime/shutdown", {"confirm": True})
                except Exception:
                    pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()  # Only this script's Popen child, never discovered user processes.
                process.wait(timeout=10)
            (evidence / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"result": report.get("result"), "evidence": str(evidence)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
