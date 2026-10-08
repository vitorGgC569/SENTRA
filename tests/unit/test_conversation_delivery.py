"""Real loopback HTTP delivery must be journaled before submission, never replayed."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from sentra_cli.agent import SentraAgent
from sentra_cli.config import CLIConfig
from sentra_core.conversations import ConversationStore, UncertainCall


@pytest.mark.skipif(os.name != "nt", reason="real Windows protected provider journal")
@pytest.mark.parametrize("complete", [True, False])
def test_real_http_submission_has_durable_identity_before_request_and_no_truncated_replay(tmp_path, complete):
    requests = []
    journal = {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            # The request cannot arrive before the submitted marker is committed.
            with journal["store"]._connect() as db:
                calls = db.execute("SELECT * FROM calls WHERE kind='provider'").fetchall()
            assert len(calls) == 1 and calls[0]["state"] == "started"
            metadata = json.loads(self.headers["x-codex-turn-metadata"])
            assert calls[0]["provider_id"] == metadata["turn_id"]
            assert metadata["thread_id"].endswith(journal["session"])
            delta = "A complete answer." if complete else "[[W|must_not_execute.txt|untrusted partial output]]"
            data = "data: " + json.dumps({"type": "response.output_text.delta", "delta": delta}) + "\n\n"
            if complete:
                data += "data: " + json.dumps({"type": "response.completed", "response": {
                    "usage":{"input_tokens":11,"output_tokens":3,"output_tokens_details":{"reasoning_tokens":1}}
                }}) + "\n\n"
            payload = data.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        kwargs = dict(workspace=tmp_path, state_root=tmp_path / "state",
            model="sentra/gemini-web/flash", auto_start_gateway=False,
            gateway_url=f"http://127.0.0.1:{server.server_port}/v1", openai_api_key="none")
        agent = SentraAgent(CLIConfig(**kwargs))
        journal.update(store=agent.store, session=agent.session_id)
        agent.client.probe_health = Mock(return_value={"gateway": True, "gateway_reachable": True, "local": True})
        output = "".join(agent.step_stream("one request only"))
        assert len(requests) == 1
        restored = SentraAgent(CLIConfig(**kwargs, session_id=agent.session_id, resume_session=True))
        if complete:
            assert "A complete answer" in output
            assert restored.store.status(restored.session_id)["uncertain_calls"] == []
            assert restored.messages == agent.messages
            usage=restored._ledger().governance.cost_summary("cli:"+restored.store.principal)
            assert usage["input_tokens"]==11 and usage["output_tokens"]==3
            assert usage["reasoning_tokens"]==1 and usage["total_tokens"]==14
        else:
            assert not (tmp_path / "must_not_execute.txt").exists()
            assert agent.client.last_delivery_state == "uncertain"
            restored.client.chat_stream = Mock()
            with pytest.raises(UncertainCall):
                list(restored.step_stream("continue"))
            restored.client.chat_stream.assert_not_called()
            assert len(requests) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
