#!/usr/bin/env python3
"""OMA observability dashboard: read-only, stdlib only, loopback only.

  python -B dashboard/server.py [--port 8899] [--relay http://127.0.0.1:8765] [--roots R1,R2]

Reads (never writes, never sends): relay SQLite + /health, run directories.
No tokens, no secrets, no model calls. Kill with Ctrl+C.
"""
import argparse
import json
import sys
from urllib.request import urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import store

STATIC = Path(__file__).resolve().parent / "static"


def _roots(value: str | None):
    if value:
        return [Path(p).expanduser() for p in value.split(",")]
    here = Path(__file__).resolve().parent.parent
    # Somente raízes do próprio projeto; workspaces externos entram via --roots.
    return [here / "runs", here / ".oma"]


class Handler(BaseHTTPRequestHandler):
    relay_base = "http://127.0.0.1:8765"
    roots: list = []

    def log_message(self, *args):
        pass

    def _send(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (OSError, BrokenPipeError):
            pass

    def _static(self, name: str, ctype: str):
        path = STATIC / name
        if ".." in name or not path.is_file():
            return self._send({"error": "not found"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (OSError, BrokenPipeError):
            pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index.html"):
            return self._static("index.html", "text/html; charset=utf-8")
        if self.path == "/app.js":
            return self._static("app.js", "application/javascript; charset=utf-8")
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        arg = lambda k, default="": (qs.get(k) or [default])[0]
        if parsed.path == "/api/overview":
            return self._send({
                "relay": store.relay_health(self.relay_base),
                "workspaces": [
                    {"root": str(r), "runs": store.list_runs(r)} for r in self.roots],
            })
        if parsed.path == "/api/web-models":
            result = {"gateway": "http://127.0.0.1:17842/v1", "online": False, "models": []}
            try:
                with urlopen("http://127.0.0.1:17842/healthz", timeout=2) as response:
                    result["health"] = json.load(response)
                with urlopen("http://127.0.0.1:17842/v1/models", timeout=3) as response:
                    catalog = json.load(response)
                result["models"] = [
                    {"slug": item.get("slug") or item.get("id"), "name": item.get("display_name") or item.get("name")}
                    for item in (catalog.get("models") or catalog.get("data") or [])
                    if isinstance(item, dict) and str(item.get("slug") or item.get("id") or "").startswith("sentra/chatgpt-web/")
                ]
                result["online"] = True
            except (OSError, ValueError) as exc:
                result["error"] = type(exc).__name__
            return self._send(result)
        if parsed.path == "/api/runs":
            root = self._pick_root(arg("workspace"))
            if root is None:
                return self._send({"error": "unknown workspace"}, 404)
            return self._send({"runs": store.list_runs(root)})
        if parsed.path == "/api/chats":
            run_dir = self._find_run(arg("run_id"))
            if run_dir is None:
                return self._send({"error": "unknown run"}, 404)
            return self._send({"run_id": arg("run_id"), "chats": store.run_chats(run_dir)})
        if parsed.path == "/api/responses":
            jobs = store.relay_jobs(self._db(), limit=int(arg("limit", "20") or 20),
                                    task_id=arg("task_id") or None,
                                    conversation_url=arg("url") or None)
            return self._send({"responses": jobs})
        if parsed.path == "/api/relay/jobs":
            jobs = store.relay_jobs(self._db(), limit=int(arg("limit", "50") or 50))
            return self._send({"jobs": jobs,
                               "health": store.relay_health(self.relay_base)})
        if parsed.path == "/api/conversations":
            chats = store.all_chats(self.roots)
            wanted = arg("state")
            if wanted:
                chats = [c for c in chats if (c.get("state") or "") == wanted]
            return self._send({"conversations": chats})
        if parsed.path == "/api/failures":
            return self._send(store.failures(self.roots, self._db()))
        if parsed.path == "/api/program":
            return self._send(store.program_stats(self.roots))
        if parsed.path == "/api/summary":
            if arg("project"):
                return self._send({"project": arg("project"),
                                   "markdown": store.project_summary(self.roots, arg("project"))})
            run_dir = self._find_run(arg("run_id"))
            if run_dir is None:
                return self._send({"error": "unknown run"}, 404)
            project = ""
            for root in self.roots:
                try:
                    run_dir.relative_to(root)
                    project = store._project_of(root, run_dir)
                    break
                except ValueError:
                    continue
            return self._send({"run_id": arg("run_id"),
                               "markdown": store.run_summary(run_dir, arg("run_id"), project)})
        return self._send({"error": "not found"}, 404)

    @classmethod
    def _pick_root(cls, name: str):
        for root in cls.roots:
            if root.name == name or str(root) == name:
                return root
        return None

    @classmethod
    def _find_run(cls, run_id: str):
        if not run_id or not store.RUN_ID.fullmatch(run_id):
            return None
        for root in cls.roots:
            if (root / run_id).is_dir():
                return root / run_id
            # Pilot repos aninhados (.oma/self-improvement/<p>/repository/runs).
            stack = [(root, 0)]
            while stack:
                current, depth = stack.pop()
                if depth > 4 or not current.is_dir():
                    continue
                if current.name == run_id and (current / "tasks.json").exists():
                    return current
                try:
                    children = [p for p in current.iterdir() if p.is_dir()
                                and p.name not in {".git", "__pycache__", "node_modules"}]
                except OSError:
                    children = []
                stack.extend((c, depth + 1) for c in children)
        return None

    @classmethod
    def _db(cls):
        here = Path(__file__).resolve().parent.parent
        return here / ".oma" / "relay.sqlite3"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--relay", default="http://127.0.0.1:8765")
    ap.add_argument("--roots", default="")
    args = ap.parse_args()
    Handler.relay_base = args.relay
    Handler.roots = _roots(args.roots or None)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[dashboard] http://127.0.0.1:{args.port}/ (somente leitura, sem envios)",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
