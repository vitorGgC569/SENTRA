"""Offline concurrency acceptance. The real model/provider is intentionally not contacted."""
from __future__ import annotations

import concurrent.futures
import http.client
import json
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sentra_model_gateway.gateway import GatewayServer, GatewayConfig

NUMBER = 10


class StreamingStub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        size = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(size))
        assert payload["model"] == "chatgpt-web/gpt-6"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for number in range(3):
            frame = (f'event: response.output_text.delta\\ndata: {{"delta":"{payload["input"]}:{number}"}}\\n\\n')
            self.wfile.write(frame.replace("\\n", "\n").encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.02)
        self.wfile.write(b"event: response.completed\ndata: {}\n\n")
        self.wfile.flush()
        self.close_connection = True


def test_ten_simultaneous_gateway_responses_no_replay_or_lost_frames(tmp_path):
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), StreamingStub)
    gateway = GatewayServer(GatewayConfig(
        upstream=f"http://127.0.0.1:{upstream.server_port}",
        port=0, state_root=tmp_path / "isolated",
        browser_descriptor=tmp_path / "browser.json",
    ))
    upstream.request_queue_size = 64
    assert gateway.request_queue_size >= 10
    threads = [threading.Thread(target=server.serve_forever, daemon=True)
               for server in (upstream, gateway)]
    for thread in threads:
        thread.start()
    barrier = threading.Barrier(NUMBER)

    def run_one(index):
        client = http.client.HTTPConnection("127.0.0.1", gateway.server_port, timeout=10)
        body = json.dumps({"model": "chatgpt-web/gpt-6", "input": f"turn-{index}"}).encode()
        barrier.wait(timeout=5)
        before = time.perf_counter()
        try:
            client.request("POST", "/v1/responses", body, {
                "Content-Type": "application/json", "Connection": "close"})
            reply = client.getresponse()
            result = reply.read().decode()
            return index, reply.status, round((time.perf_counter() - before) * 1000), result
        finally:
            client.close()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=NUMBER) as pool:
            items = list(pool.map(run_one, range(NUMBER)))
    finally:
        for server in (gateway, upstream):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=4)

    latency = sorted(item[2] for item in items)
    for index, status, elapsed, content in items:
        assert status == 200, (index, status, content[:200])
        assert content.count("response.output_text.delta") == 3, (index, content)
        assert content.count(f"turn-{index}:0") == 1
        assert content.count(f"turn-{index}:1") == 1
        assert content.count(f"turn-{index}:2") == 1
        assert content.count("event: response.completed") == 1
    print(f"synthetic_local_10_streams=10/10 p50_ms={statistics.median(latency)} p95_ms={latency[-1]} min_ms={latency[0]}")
