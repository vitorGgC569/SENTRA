"""Workspace-bound access to the native SENTRA Canvas, without Maestri."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


class CanvasBridge:
    def __init__(self, config):
        self.workspace = str(config.workspace)
        self._token = os.environ.get("SENTRA_CANVAS_AGENT_TOKEN", "")
        port = os.environ.get("SENTRA_CANVAS_AGENT_PORT", "")
        self.port = int(port) if port.isdigit() and 1 <= int(port) <= 65535 else None
        self.is_available = bool(self.port and len(self._token) >= 32)

    def execute(self, raw_args, request_key):
        if not self.is_available:
            raise RuntimeError("SENTRA Canvas connection is unavailable")
        action, _, value = raw_args.partition("|")
        action=action.strip().lower()
        if action in {"create_agent","create_terminal","connect","create_team","dispatch","note_write"}:
            if not isinstance(request_key,str) or not 1<=len(request_key)<=128:
                raise ValueError("persistent Canvas request identity required")
        body = {"action":action, "workspace":self.workspace,
                "value":value, "request_key":request_key}
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/agent/control",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization":"Bearer "+self._token,
                     "Content-Type":"application/json"})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
        try:
            with opener.open(request,timeout=8) as response:
                payload=response.read(65537)
                if len(payload)>65536:
                    raise RuntimeError("Canvas response exceeded limit")
                return json.dumps(json.loads(payload),ensure_ascii=False)
        except urllib.error.HTTPError as exc:
            # Do not expose authorization headers, environment or raw HTML.
            raise RuntimeError(f"Canvas rejected the operation (HTTP {exc.code})") from None
