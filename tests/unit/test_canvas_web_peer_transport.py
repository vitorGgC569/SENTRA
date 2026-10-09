"""Real SENTRA ConPTY peer-to-peer regression with a deterministic Web API test double.

This proves Canvas -> CLI -> Responses SSE -> persisted transcript in BOTH
directions; it does NOT claim a live ChatGPT/Gemini account made inference.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
import uuid

import pytest

from sentra_canvas.service import Canvas
from sentra_cli.config import CLIConfig
from sentra_core.conversations import ConversationStore


class WebResponsesStub(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        self.messages = []
        self.lock = threading.RLock()
        super().__init__(("127.0.0.1", 0), StubHandler)


class StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/healthz":
            return self.send_json({"status": "ok", "ready": True, "upstream": {
                "status": "ok", "accepting_turns": True
            }})
        if self.path == "/v1/models":
            return self.send_json({"data": [{"id": "sentra/gemini-web/flash"}]})
        self.send_error(404)

    def send_json(self, data):
        blob = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def do_POST(self):
        if self.path != "/v1/responses":
            return self.send_error(404)
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw)
        assert payload["model"] == "sentra/gemini-web/flash"
        turns = []
        for item in payload["input"]:
            if item.get("role") == "user":
                parts = item.get("content", [])
                turns.append(" ".join(p.get("text", "") for p in parts))
        prompt = turns[-1] if turns else ""
        with self.server.lock:
            self.server.messages.append(prompt)
        if "RECRUIT_WEB_WORKER" in prompt:
            response_text = "[[CANVAS|create_agent|web_worker|sentra/gemini-web/flash|worker]]"
        elif "DISPATCH_WEB_PEER:" in prompt:
            node_id, marker = prompt.split("DISPATCH_WEB_PEER:", 1)[1].strip().split(":", 1)
            marker = marker.split()[0]
            response_text = "[[CANVAS|dispatch|" + node_id + "|FROM_A_" + marker + " reply briefly]]"
        elif "FROM_A_" in prompt:
            suffix = prompt.split("FROM_A_", 1)[1].split()[0]
            response_text = "B_REPLIED_" + suffix
        elif "FROM_B_" in prompt:
            suffix = prompt.split("FROM_B_", 1)[1].split()[0]
            response_text = "A_REPLIED_" + suffix
        else:
            response_text = "WEB_PEER_READY"
        result = {"id": "resp_" + uuid.uuid4().hex, "status": "completed",
                  "output": [{"type": "message", "role": "assistant",
                              "content": [{"type": "output_text", "text": response_text}]}],
                  "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16}}
        if "DENY_WEB_ACCESS" in prompt:
            events = [{"type":"response.failed","response":{
                "status":"failed","error":{"code":"chatgpt_model_controls_unavailable",
                "type":"invalid_request_error","message":"Think-only composer; no model selection"}}}]
        elif "FAIL_WEB_PROVIDER" in prompt:
            events = [{"type":"response.failed","response":{
                "status":"failed","error":{"code":"upstream_error",
                "type":"server_error","message":"simulated provider outage"}}}]
        else:
            events = [
                {"type": "response.output_text.delta", "delta": response_text},
                {"type": "response.completed", "response": result},
            ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        for event in events:
            self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
            self.wfile.flush()


def await_until(fn, timeout=25):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return
        time.sleep(.075)
    raise AssertionError("Web peer transport did not reach expected state")


@pytest.mark.skipif(os.name != "nt", reason="real Windows ConPTY required")
def test_two_independent_web_cli_peers_exchange_replies_and_persist(tmp_path, monkeypatch):
    gateway = WebResponsesStub()
    gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    gateway_thread.start()
    monkeypatch.setenv("SENTRA_GATEWAY_URL", f"http://127.0.0.1:{gateway.server_port}/v1")
    monkeypatch.setenv("SENTRA_CLI_GATEWAY_API_KEY", "qa-scoped")
    monkeypatch.setenv("SENTRA_CLI_AUTO_START_GATEWAY", "0")
    from sentra_canvas.__main__ import CanvasServer
    app = Canvas(tmp_path, max_terminals=3)
    server = CanvasServer(app)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    ws = app.create_workspace("two_web_peers")["id"]
    agents = {}
    try:
        for name in ("web_a", "web_b"):
            agents[name] = app.create_agent(
                ws, name, "sentra/gemini-web/flash", start=True
            )
        graph = app.graph_detail(ws)
        node = {
            name: next(n for n in graph["nodes"]
                       if n["kind"] == "agent" and n["resource_id"] == agent["id"])
            for name, agent in agents.items()
        }
        app.graph_link(ws, node["web_a"]["id"], node["web_b"]["id"])
        app.graph_link(ws, node["web_b"]["id"], node["web_a"]["id"])
        tag = uuid.uuid4().hex[:12]
        first = app.handoff(ws, node["web_a"]["id"], node["web_b"]["id"],
                            f"FROM_A_{tag} reply briefly", True, "qa-from-a")
        assert first["status"] == "sent"
        assert first["model_acknowledged"] is False
        def b_replied():
            output = app.terminal_output(ws, agents["web_b"]["terminal_id"])
            return "B_REPLIED_" + tag in output["text"]
        await_until(b_replied)
        other = app.handoff(ws, node["web_b"]["id"], node["web_a"]["id"],
                            f"FROM_B_{tag} reply briefly", True, "qa-from-b")
        assert other["status"] == "sent"
        await_until(lambda: "A_REPLIED_" + tag in
                    app.terminal_output(ws, agents["web_a"]["terminal_id"])["text"])
        history = ConversationStore(app.state_dir.parent)
        for name, expected in (("web_b", "B_REPLIED_"), ("web_a", "A_REPLIED_")):
            conversation = history.history_window(agents[name]["conversation_id"])
            assert any(expected + tag in item["content"] and item["role"] == "assistant"
                       for item in conversation["messages"])
        with gateway.lock:
            assert any("FROM_A_" + tag in value for value in gateway.messages)
            assert any("FROM_B_" + tag in value for value in gateway.messages)
        await_until(lambda: all(h["receipt_status"] == "answered"
                                for h in app.graph.handoffs(ws)))
        assert len(app.graph.handoffs(ws)) == 2
        assert app.handoff(ws, node["web_a"]["id"], node["web_b"]["id"],
                           f"FROM_A_{tag} reply briefly", True, "qa-from-a")["id"] == first["id"]
    finally:
        server.shutdown()
        server_thread.join(timeout=5)
        server.server_close()
        app.shutdown()
        gateway.shutdown()
        gateway_thread.join(timeout=3)
        gateway.server_close()
    restored = Canvas(tmp_path)
    try:
        assert len(restored.graph.handoffs(ws)) == 2
        assert "A_REPLIED_" + tag in restored.terminal_output(
            ws, agents["web_a"]["terminal_id"])["text"]
        assert "B_REPLIED_" + tag in restored.terminal_output(
            ws, agents["web_b"]["terminal_id"])["text"]
    finally:
        restored.shutdown()

@pytest.mark.skipif(os.name != "nt", reason="real Windows ConPTY required")
def test_web_model_recruits_peer_and_dispatches_via_canvas_capability(tmp_path, monkeypatch):
    """Model-emitted CANVAS directives execute through real CLI and local bearer API."""
    from sentra_canvas.__main__ import CanvasServer

    gateway = WebResponsesStub()
    gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    gateway_thread.start()
    monkeypatch.setenv("SENTRA_GATEWAY_URL", f"http://127.0.0.1:{gateway.server_port}/v1")
    monkeypatch.setenv("SENTRA_CLI_GATEWAY_API_KEY", "qa-scoped")
    monkeypatch.setenv("SENTRA_CLI_AUTO_START_GATEWAY", "0")
    app = Canvas(tmp_path, max_terminals=3)
    server = CanvasServer(app)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        ws = app.create_workspace("web_coordination")["id"]
        coordinator = app.create_agent(ws, "web_coordinator", "sentra/gemini-web/flash", start=True)
        coordinator_terminal = coordinator["terminal_id"]
        app.terminal_input(ws, coordinator_terminal, "RECRUIT_WEB_WORKER\r")
        await_until(lambda: any(agent["name"] == "web_worker" for agent in
                                app.store.list_resources("agents", ws)), timeout=30)
        agents = app.store.list_resources("agents", ws)
        worker = next(a for a in agents if a["name"] == "web_worker")
        assert worker["terminal_id"] != coordinator_terminal
        assert len(app._agent_tokens) == 2
        graph = app.graph_detail(ws)
        source = next(n for n in graph["nodes"]
                      if n["kind"] == "agent" and n["resource_id"] == coordinator["id"])
        target = next(n for n in graph["nodes"]
                      if n["kind"] == "agent" and n["resource_id"] == worker["id"])
        # Agent row and directed link commit in separate transactions.
        await_until(lambda: any(
            link["source"] == source["id"] and link["target"] == target["id"]
            for link in app.graph_detail(ws)["links"]
        ))
        marker = uuid.uuid4().hex[:12]
        app.terminal_input(ws, coordinator_terminal,
                           "DISPATCH_WEB_PEER:" + target["id"] + ":" + marker + "\r")
        await_until(lambda: "B_REPLIED_" + marker in
                    app.terminal_output(ws, worker["terminal_id"])["text"], timeout=30)
        handoffs = app.graph.handoffs(ws)
        assert len(handoffs) == 1
        assert handoffs[0]["status"] == "sent"
        await_until(lambda: app.graph.handoffs(ws)[0]["receipt_status"] == "answered")
        assert handoffs[0]["source"] == source["id"]
        assert handoffs[0]["target"] == target["id"]
        assert "FROM_A_" + marker in handoffs[0]["content"]
        # An independent Web-model round generated the directive, and Canvas executed it.
        with gateway.lock:
            assert any("RECRUIT_WEB_WORKER" in message for message in gateway.messages)
            assert any("DISPATCH_WEB_PEER:" in message for message in gateway.messages)
            assert any("FROM_A_" + marker in message for message in gateway.messages)
        assert len(agents) == 2
        assert len(app.store.list_resources("agents", ws)) == 2
        assert ConversationStore(app.state_dir.parent).history_window(worker["conversation_id"])["messages"]
    finally:
        server.shutdown()
        server_thread.join(timeout=5)
        server.server_close()
        app.shutdown()
        gateway.shutdown()
        gateway_thread.join(timeout=5)
        gateway.server_close()

@pytest.mark.skipif(os.name != "nt", reason="real Windows ConPTY required")
@pytest.mark.parametrize(("message","expected_receipt","error_code"),[
    ("FAIL_WEB_PROVIDER","uncertain","upstream_error"),
    ("DENY_WEB_ACCESS","failed","chatgpt_model_controls_unavailable")
])
def test_web_failure_never_becomes_false_model_ack(
    tmp_path, monkeypatch, message, expected_receipt, error_code
):
    """Upstream or access errors can never masquerade as a model answer."""
    from sentra_canvas.__main__ import CanvasServer

    gateway=WebResponsesStub()
    gw_thread=threading.Thread(target=gateway.serve_forever,daemon=True)
    gw_thread.start()
    monkeypatch.setenv("SENTRA_GATEWAY_URL",f"http://127.0.0.1:{gateway.server_port}/v1")
    monkeypatch.setenv("SENTRA_CLI_GATEWAY_API_KEY","qa-scoped")
    monkeypatch.setenv("SENTRA_CLI_AUTO_START_GATEWAY","0")
    app=Canvas(tmp_path,max_terminals=3)
    server=CanvasServer(app)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        ws=app.create_workspace("web_failure")["id"]
        source=app.create_agent(ws,"source","sentra/gemini-web/flash",start=True)
        dest=app.create_agent(ws,"dest","sentra/gemini-web/flash",start=True)
        nodes=app.graph_detail(ws)["nodes"]
        a=next(n["id"] for n in nodes if n["kind"]=="agent" and n["resource_id"]==source["id"])
        b=next(n["id"] for n in nodes if n["kind"]=="agent" and n["resource_id"]==dest["id"])
        app.graph_link(ws,a,b)
        result=app.handoff(ws,a,b,message,True,"failure-qa")
        await_until(lambda: app.graph.handoffs(ws)[0]["receipt_status"]==expected_receipt)
        output=app.terminal_output(ws,dest["terminal_id"])["text"]
        assert error_code in output
        assert "SENTRA Web turn failed" in output
        handoff=app.graph.handoffs(ws)[0]
        assert handoff["status"]=="sent"
        assert handoff["receipt_status"]==expected_receipt
        assert result["model_acknowledged"] is False
        assert len(app.graph.handoffs(ws))==1
    finally:
        server.shutdown()
        thread.join(timeout=4)
        server.server_close()
        app.shutdown()
        gateway.shutdown()
        gw_thread.join(timeout=4)
        gateway.server_close()

def test_canvas_model_catalog_route_requires_local_auth_and_never_asserts_entitlement(
    tmp_path, monkeypatch
):
    from sentra_canvas.__main__ import CanvasServer
    from urllib.error import HTTPError
    from urllib.request import Request, build_opener, ProxyHandler

    app = Canvas(tmp_path)
    monkeypatch.setattr(app, "model_catalog", lambda: {
        "models": ["sentra/chatgpt-web/gpt-6-instant",
                   "sentra/chatgpt-web/gpt-6",
                   "sentra/gemini-web/flash"],
        "source": "authenticated_catalog",
        "model_access_verified": False,
    })
    server = CanvasServer(app)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    url = f"http://127.0.0.1:{server.server_port}/api/models"
    try:
        with pytest.raises(HTTPError) as rejected:
            opener.open(Request(url),timeout=3)
        assert rejected.value.code == 401
        with opener.open(Request(url, headers={"Authorization":"Bearer "+server.secret}),timeout=3) as resp:
            data=json.loads(resp.read())
        assert resp.status == 200
        assert len(data["models"]) == 3
        assert "sentra/chatgpt-web/gpt-6" in data["models"]
        assert data["model_access_verified"] is False
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        app.shutdown()


def test_canvas_model_catalog_not_a_model_access_verdict(tmp_path, monkeypatch):
    from sentra_cli.client import ModelClient, ProviderHTTPError
    app=Canvas(tmp_path)
    try:
        monkeypatch.setattr(ModelClient, "list_models", lambda self: [
            "sentra/codex/current", "sentra/chatgpt-web/gpt-6",
            "sentra/chatgpt-web/gpt-6-instant", "unsupported/surprise"
        ])
        models=app.model_catalog()
        assert models["model_access_verified"] is False
        assert "unsupported/surprise" not in models["models"]
        assert "sentra/chatgpt-web/gpt-6" in models["models"]
        def unavailable(self):
            raise ProviderHTTPError("gateway",503,"offline")
        monkeypatch.setattr(ModelClient,"list_models",unavailable)
        missing=app.model_catalog()
        assert missing == {"models":[],"source":"unavailable","model_access_verified":False}
    finally:
        app.shutdown()
