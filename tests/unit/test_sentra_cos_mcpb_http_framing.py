"""Real HTTP framing with central admission and no ambiguous effect replay.

MCP permits arbitrary endpoint paths. These fixtures use /fixture-rpc; the
existing /mcp fixtures separately cover that endpoint on this machine.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sentra_mcp.services.mcpb_http import MCPHttpRegistry
from test_sentra_cos_mcpb_http import args, control, grant


@pytest.fixture
def framed_peer():
    servers = []

    def start(framing):
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                assert self.path == "/fixture-rpc"
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                method = request["method"]
                observed.append(method)
                if method == "notifications/initialized":
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                result = ({"protocolVersion": "2025-06-18"} if method == "initialize"
                          else {"tools": [{"name": "echo"}]} if method == "tools/list"
                          else {"content": [{"type": "text", "text": "HTTP_OK"}]})
                body = json.dumps({"jsonrpc": "2.0", "id": request["id"],
                                   "result": result}).encode()
                tool = method == "tools/call"
                sse = tool and framing == "chunked-sse"
                if sse:
                    body = b"event: message\ndata: " + body + b"\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if sse
                                 else "application/json")
                if tool and framing.startswith("chunked"):
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    # Split SSE lines and JSON tokens across physical chunks.
                    for offset in range(0, len(body), 7):
                        chunk = body[offset:offset + 7]
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")
                elif tool and framing == "malformed-chunk":
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self.wfile.write(body)  # Deliberately missing HTTP chunks.
                else:
                    self.send_header("Content-Length", str(len(body) + (
                        9 if tool and framing == "truncated-length" else 0)))
                    self.end_headers()
                    self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_address[1]}/fixture-rpc", observed

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize("framing", ["chunked-json", "chunked-sse"])
def test_chunked_http_body_decoded_before_json_or_sse(control, framed_peer, framing):
    cp, ws = control
    endpoint, observed = framed_peer(framing)
    registry = MCPHttpRegistry(cp)
    registry.register("owner", ws, "local-echo", endpoint, approved=True,
                      streamable=True)
    for capability in ("mcp:http-connect", "mcp:list", "mcp:echo"):
        grant(cp, capability)
    details = args(ws, framing)
    result = asyncio.run(registry.execute(**details))
    assert result.operation.state == "SUCCEEDED", result
    assert result.payload["content"] == [{"type": "text", "text": "HTTP_OK"}]
    assert observed.count("tools/call") == 1
    assert asyncio.run(registry.execute(**details)).duplicate
    assert observed.count("tools/call") == 1


@pytest.mark.parametrize("framing", ["truncated-length", "malformed-chunk"])
def test_incomplete_http_tool_reply_stays_uncertain_without_replay(
        control, framed_peer, framing):
    cp, ws = control
    endpoint, observed = framed_peer(framing)
    registry = MCPHttpRegistry(cp)
    registry.register("owner", ws, "local-echo", endpoint, approved=True)
    for capability in ("mcp:http-connect", "mcp:list", "mcp:echo"):
        grant(cp, capability)
    details = args(ws, framing)
    result = asyncio.run(registry.execute(**details))
    assert result.operation.state == "UNCERTAIN", result
    assert cp.durable.operation_status(details["operation_id"], "owner")["state"] == "UNCERTAIN"
    assert observed.count("tools/call") == 1
    replay = asyncio.run(registry.execute(**details))
    assert replay.duplicate and replay.operation.state == "UNCERTAIN"
    assert observed.count("tools/call") == 1
