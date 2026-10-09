"""Focused web Canvas regression checks, without model/API invocation."""
from __future__ import annotations
import os
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas

ROOT = Path(__file__).resolve().parents[2]


def test_canvas_web_cable_assets_and_browser_route(tmp_path):
    app = Canvas(tmp_path)
    server = CanvasServer(app, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/canvas", timeout=5) as response:
            html = response.read().decode("utf-8")
            assert "text/html" in response.headers["Content-Type"]
            assert 'src="/rope-physics.js"' in html
            assert 'src="/fractal-grid.js"' in html
            assert 'id="fractal-grid"' in html
            assert 'id="inspector-tabs"' in html
            assert 'id="command-clear"' in html
            assert 'src="/native.js"' in html
        with urllib.request.urlopen(base + "/rope-physics.js", timeout=5) as response:
            js = response.read().decode("utf-8")
            assert "javascript" in response.headers["Content-Type"]
            assert "SentraCablePhysics" in js
        with urllib.request.urlopen(base + "/fractal-grid.js", timeout=5) as response:
            source = response.read().decode("utf-8")
            assert "SentraFractalGrid" in source
            assert "prefers-reduced-motion" in source
        with urllib.request.urlopen(base + "/index.html", timeout=5) as response:
            assert "app.js" in response.read().decode("utf-8")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        app.shutdown()


def test_browser_cli_uses_authoritative_launch_path(tmp_path, monkeypatch):
    app = Canvas(tmp_path)
    try:
        ws = app.create_workspace("browser_cli")["id"]
        commands = []
        monkeypatch.setattr(app, "_cli_command", lambda args: commands.append(args) or ["fake-cli.exe", *args])
        monkeypatch.setattr(app, "_start", lambda ws,name,shell,cmd: {"name":name,"shell":shell,"argv":cmd})
        actual=app.create_terminal(ws, "developer", "sentra-cli")
        assert actual["shell"] == "sentra-cli"
        assert actual["argv"][0] == "fake-cli.exe"
        assert "--workspace" in commands[0]
        assert "--session-id" in commands[0]
        assert "--state-dir" in commands[0]
        assert "--no-auto-start" not in commands[0]
        assert len(commands[0][commands[0].index("--session-id")+1]) > 5
        selected=app.create_terminal(ws, "codex_model", "sentra-cli", model="sentra/codex/current")
        assert "--model" in selected["argv"]
        assert selected["argv"][-1] == "sentra/codex/current"
        chosen=app.create_terminal(ws,"high_reasoning","sentra-cli",
                                   model="sentra/codex/current",effort="high")
        assert chosen["argv"][-2:] == ["--effort","high"]
        with pytest.raises(ValueError, match="invalid SENTRA CLI reasoning effort"):
            app.create_terminal(ws,"unsafe","sentra-cli",effort="high;injected")
        with pytest.raises(ValueError, match="invalid SENTRA CLI model"):
            app.create_terminal(ws, "invalid", "sentra-cli", model="bad; injection")
        with pytest.raises(ValueError, match="model selection requires SENTRA CLI"):
            app.create_terminal(ws, "shell", "cmd", model="sentra/codex/current")
    finally:
        app.shutdown()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for SVG physics execution")
def test_canvas_physics_in_javascript():
    target=ROOT / "tests" / "js" / "canvas_cable_physics.cjs"
    result=subprocess.run([shutil.which("node"),str(target)],capture_output=True,
                          text=True,timeout=20,check=False)
    assert result.returncode == 0, result.stdout+"\n"+result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for syntax check")
def test_native_browser_javascript_syntax():
    for name in ("native.js","rope-physics.js","fractal-grid.js"):
        target=ROOT / "sentra_canvas" / "static" / name
        result=subprocess.run([shutil.which("node"),"--check",str(target)],
                              capture_output=True,text=True,timeout=10,check=False)
        assert result.returncode == 0, name+": "+result.stderr
