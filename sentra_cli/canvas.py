"""Workspace-bound access to the native SENTRA Canvas, without Maestri."""
from __future__ import annotations

import json
import os
import hashlib
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
        if action in {"machine_list", "machine_execute", "machine_observe", "machine_experiences"}:
            body = {"action": action, "workspace": self.workspace}
            if action == "machine_execute":
                if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
                    raise ValueError("persistent machine operation identity required")
                values = json.loads(value)
                if (not isinstance(values, dict)
                        or set(values) != {"work_item_id", "machine_id", "capability_id", "arguments"}
                        or not isinstance(values["arguments"], dict)):
                    raise ValueError("machine command requires scoped task/capability/arguments")
                body.update(values)
                body["operation_id"] = "op-canvas-" + hashlib.sha256(request_key.encode()).hexdigest()[:40]
                body["request_key"] = request_key
            elif action == "machine_observe":
                body["operation_id"] = value.strip()
            elif action == "machine_experiences":
                values=json.loads(value)
                if (not isinstance(values,dict) or set(values)-{"work_item_id","machine_id","query","limit"}
                        or not {"work_item_id","machine_id","query"}<=set(values)):
                    raise ValueError("experience command requires scoped task/machine/query")
                body.update(values)
            return json.dumps(self._request(body), ensure_ascii=False)
        if action in {"create_agent","create_terminal","connect","create_team","dispatch","note_write"}:
            if not isinstance(request_key,str) or not 1<=len(request_key)<=128:
                raise ValueError("persistent Canvas request identity required")
        body = {"action":action, "workspace":self.workspace,
                "value":value, "request_key":request_key}
        return json.dumps(self._request(body), ensure_ascii=False)

    def claim(self, content: str) -> str | None:
        """Identify an actual queued Canvas delivery without changing user input."""
        if not self.is_available or not isinstance(content,str):
            return None
        result = self._request({"action":"claim","workspace":self.workspace,"value":content})
        ident = result.get("id")
        return ident if isinstance(ident,str) and len(ident)==32 else None

    def working_context(self):
        if not self.is_available:return None
        return self._request({"action":"context","workspace":self.workspace})

    def receipt(self, ident: str, status: str) -> None:
        if not self.is_available or not ident:
            return
        if status not in {"answered","tool_completed","failed","uncertain"}:
            raise ValueError("invalid Canvas receipt")
        self._request({"action":"receipt","workspace":self.workspace,
                       "handoff_id":ident,"receipt_status":status})

    def _request(self, body):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/agent/control",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization":"Bearer "+self._token,
                     "Content-Type":"application/json"})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
        try:
            with opener.open(request,timeout=130 if body.get("action") == "machine_execute" else 8) as response:
                limit=2_100_000 if body.get("action","").startswith("machine_") else 65536
                payload=response.read(limit+1)
                if len(payload)>limit:
                    raise RuntimeError("Canvas response exceeded limit")
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            # Do not expose authorization headers, environment or raw HTML.
            raise RuntimeError(f"Canvas rejected the operation (HTTP {exc.code})") from None
