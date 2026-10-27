"""Exercise an installed core executable against an isolated local API fixture."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    parser.add_argument('--local', action='store_true')
    args = parser.parse_args()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            if self.path != '/v1/models':
                self.send_error(404); return
            self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        def do_POST(self):
            if self.path != '/v1/chat/completions':
                self.send_error(404); return
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(request.get('model'))
            data = (b'data: {"choices":[{"delta":{"content":"SENTRA_CORE_OK"}}]}\n\n'
                    b'data: [DONE]\n\n')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='sentra-core-smoke-') as tmp:
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('SENTRA_', 'MAESTRI_', 'OPENAI_'))}
            endpoint = f'http://127.0.0.1:{server.server_port}/v1'
            if args.local:
                env.update(OPENAI_API_KEY='none', SENTRA_LOCAL_BASE_URL=endpoint,
                           SENTRA_LOCAL_MODEL='fixture-model')
            else:
                env.update(OPENAI_API_KEY='fixture-key', OPENAI_BASE_URL=endpoint)
            result = subprocess.run([str(args.executable.resolve()), '-p', 'Reply briefly',
                                     '--model', 'fixture-model', '--timeout', '30'],
                                    cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
            assert 'SENTRA_CORE_OK' in result.stdout, result.stdout
            assert calls == ['fixture-model'], calls
            print('PASS: installed CLI made one direct request to the local API fixture')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__':
    main()
