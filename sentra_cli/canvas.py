"""Workspace-bound access to the native SENTRA Canvas, without Maestri."""
from __future__ import annotations

import json
import os
import hashlib
import re
import urllib.error
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


class CanvasBridge:
    def __init__(self, config):
        self.workspace = str(config.workspace)
        self.model = getattr(config, "model", None)
        self._token = os.environ.get("SENTRA_CANVAS_AGENT_TOKEN", "")
        port = os.environ.get("SENTRA_CANVAS_AGENT_PORT", "")
        self.port = int(port) if port.isdigit() and 1 <= int(port) <= 65535 else None
        self.is_available = bool(self.port and len(self._token) >= 32)
        self.is_shell_scope = os.environ.get('SENTRA_CANVAS_AGENT_SCOPE', '') == 'shell'
        self._binding_path = os.environ.get('SENTRA_CANVAS_AGENT_BINDING_FILE', '') if not self.is_shell_scope else ''

    def execute(self, raw_args, request_key):
        if not self.is_available:
            raise RuntimeError("SENTRA Canvas connection is unavailable")
        action, _, value = raw_args.partition("|")
        action=action.strip().lower()
        if self.is_shell_scope and action=='isolate_work':
            if value.strip():raise ValueError('isolate_work takes no arguments')
            return json.dumps(self._request({'action':action,'workspace':self.workspace,
                'value':'','request_key':request_key}),ensure_ascii=False)
        if self.is_shell_scope and action=='review_worktrees':
            spec=json.loads(value)
            if not isinstance(spec,dict) or set(spec)!={'conversation_ids'} or len(value)>4000:
                raise ValueError('bounded conversation selection required')
            return json.dumps(self._request({'action':action,'workspace':self.workspace,
                'value':value,'request_key':request_key}),ensure_ascii=False)
        if self.is_shell_scope and action=='verify_result':
            spec=json.loads(value)
            if not isinstance(spec,dict) or set(spec)!={'operation_ids'} or len(value)>4000:
                raise ValueError('verification requires file-read operation_ids')
            return json.dumps(self._request({'action':action,'workspace':self.workspace,
                'value':value,'request_key':request_key}),ensure_ascii=False)
        if action in {'vm_create', 'vm_status', 'vm_frame', 'vm_input'}:
            body = {'action': action, 'workspace': self.workspace}
            if action == 'vm_input':
                spec = json.loads(value)
                if (not isinstance(spec, dict) or spec.get('action') not in {'input.key', 'input.mouse'}
                        or set(spec) - ({'action','scancodes'} if spec.get('action') == 'input.key'
                            else {'action','x','y','buttons','wheel'})
                        or not isinstance(request_key, str) or not 1 <= len(request_key) <= 128 or len(value) > 4000):
                    raise ValueError('bounded VM input and persistent request identity required')
                body.update(value=json.dumps(spec, ensure_ascii=False, sort_keys=True), request_key=request_key)
            if action == 'vm_frame' and value.strip():
                raise ValueError('VM frame read takes no arguments')
            if action == 'vm_create':
                spec = json.loads(value)
                if (not isinstance(spec, dict) or set(spec) - {'os_family', 'cpus', 'memory_mb', 'disk_gb', 'iso_path', 'username'}
                        or not isinstance(request_key, str) or not 1 <= len(request_key) <= 128 or len(value) > 4000):
                    raise ValueError('bounded persistent VM configuration required')
                body.update(value=value, request_key=request_key)
            return json.dumps(self._request(body), ensure_ascii=False)
        # The shell host translates these aliases into the same typed central
        # coordinator intents, with live binding, directed scope and Grants.
        # Terminal bootstrap/network configuration still have no shell alias.
        if self.is_shell_scope and action in {'create_terminal', 'network_whitelist'}:
            raise PermissionError('shell coordination requires the central coordinator_intent protocol')
        if action in {'children', 'child_reply'}:
            if not self.is_shell_scope:
                raise PermissionError('child conversations are available only to a live shell Dot turn')
            if action == 'children':
                if value.strip():
                    raise ValueError('children read takes no selector or conversation id')
                return json.dumps(self._request({'action': action, 'workspace': self.workspace}), ensure_ascii=False)
            if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128 or '\0' in request_key:
                raise ValueError('persistent child reply identity required')
            if not value or len(value) > 100000:
                raise ValueError('bounded child reply JSON required')
            reply = json.loads(value)
            if (not isinstance(reply, dict) or set(reply) != {'conversation_id', 'content'}
                    or not isinstance(reply['conversation_id'], str) or not reply['conversation_id']
                    or not isinstance(reply['content'], str) or not 1 <= len(reply['content']) <= 100000):
                raise ValueError('child reply requires only conversation_id and bounded content')
            canonical = json.dumps(reply, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))
            return json.dumps(self._request({'action': action, 'workspace': self.workspace,
                'value': canonical, 'request_key': request_key}), ensure_ascii=False)
        if action == 'coordinator_intent':
            if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128 or '\0' in request_key:
                raise ValueError('persistent coordination identity required')
            if not value or len(value) > 4000:
                raise ValueError('bounded structured coordinator intent required')
            intent = json.loads(value)
            if not isinstance(intent, dict) or intent.get('kind') not in {
                'create_dot', 'create_team', 'connect', 'delegate', 'handoff',
                'pause', 'resume', 'cancel', 'reassign', 'pause_dot', 'resume_dot',
                'dot_tool_dispatch', 'consolidate_tool_dispatches'}:
                raise ValueError('unsupported coordinator intent kind')
            canonical = json.dumps(intent, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))
            if len(canonical) > 4000:
                raise ValueError('coordinator intent exceeds host value limit')
            return json.dumps(self._request({'action': action, 'workspace': self.workspace,
                'value': canonical, 'request_key': request_key}), ensure_ascii=False)
        if action in {"machine_list", "machine_execute", "machine_observe", "machine_experiences"}:
            body = {"action": action, "workspace": self.workspace}
            if action == "machine_execute":
                if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
                    raise ValueError("persistent machine operation identity required")
                values = json.loads(value)
                if (not isinstance(values, dict)
                        or set(values) - {"work_item_id", "machine_id", "capability_id", "arguments", "observation_id"}
                        or not {"work_item_id", "machine_id", "capability_id", "arguments"} <= set(values)
                        or not isinstance(values["arguments"], dict)):
                    raise ValueError("machine command requires scoped task/capability/arguments")
                observation = values.pop("observation_id", None)
                if observation is not None:
                    if (values["arguments"].get("action") not in {"read", "stat"}
                            or not isinstance(observation, str) or not 1 <= len(observation) <= 64
                            or not re.fullmatch("[a-zA-Z0-9_-]+", observation)):
                        raise ValueError("observation_id is allowed only for repeated read/stat calls")
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

    def authority_checkpoint(self):
        """Revalidate the live turn without rebuilding its machine catalog."""
        if not self.is_available:
            return None
        return self._request({"action": "checkpoint", "workspace": self.workspace})

    def receipt(self, ident: str, status: str) -> None:
        if not self.is_available or not ident:
            return
        if status not in {"answered","tool_completed","failed","uncertain"}:
            raise ValueError("invalid Canvas receipt")
        self._request({"action":"receipt","workspace":self.workspace,
                       "handoff_id":ident,"receipt_status":status})

    def _request(self, body):
        if self._binding_path:
            from .canvas_binding import read_binding
            binding=read_binding(self._binding_path,self._token,self.workspace)
            self.port=binding['port']
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/agent/control",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization":"Bearer "+self._token,
                     "Content-Type":"application/json"})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
        timeout = 130 if body.get("action") in {"machine_execute", "vm_create", "vm_frame", "vm_input", "verify_result", "isolate_work", "review_worktrees"} else 8
        if body.get('action') in {'context','machine_list','checkpoint'}:
            # These reads enumerate several independently authorized resources.
            # Parallel Windows worktrees can exceed the old eight-second bound.
            # Admission checkpoints are also single read-only revalidations;
            # a busy host must not strand an otherwise live model turn after
            # metadata effects. The authority/fence is still checked on reply.
            # This widens one read deadline; no request is retried.
            timeout=30
        if self.is_shell_scope and body.get('action') in {
                'dispatch','coordinator_intent','create_agent','create_team','connect','child_reply'}:
            # Admission may prepare several scoped child resources. The original
            # identity remains journaled; a timeout still must never resend it.
            timeout=130
        intent = body.get('intent')
        if body.get('action') == 'coordinator_intent' and intent is None:
            intent = json.loads(body.get('value') or '{}')
        if body.get('action') == 'coordinator_intent' and isinstance(intent, dict) and intent.get('kind') == 'dot_tool_dispatch':
            requested = intent.get('timeout_s', 300)
            if type(requested) not in {int, float} or not 1 <= requested <= 600:
                raise ValueError('bounded tool timeout required')
            timeout = requested + 15
        try:
            with opener.open(request,timeout=timeout) as response:
                # The executor caps a PNG frame at 1 MiB; its JSON Base64
                # envelope exceeds the ordinary 64 KiB control response limit.
                limit=2_100_000 if body.get("action","").startswith("machine_") or body.get("action") == "vm_frame" else 65536
                payload=response.read(limit+1)
                if len(payload)>limit:
                    raise RuntimeError("Canvas response exceeded limit")
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            # Show only recognized validation messages. Never echo arbitrary
            # server text, bearer tokens, workspace paths or raw HTML.
            reason = ""
            if exc.code == 400:
                try:
                    details = json.loads(exc.read(1025))
                    candidate = details.get("error", "") if isinstance(details, dict) else ""
                    known = (
                        "name must be 1-48 ASCII letters/numbers/_/-",
                        "invalid Canvas model or role",
                        "Canvas resource name already exists",
                        "terminal concurrency quota reached",
                        "creation requires name|model|optional role",
                        "Canvas coordination value must contain at most 4000 characters",
                        "persistent coordination identity required",
                        "Canvas coordination idempotency collision",
                    )
                    if isinstance(candidate, str) and any(candidate.startswith(k) for k in known):
                        reason = ": " + candidate[:160]
                except (ValueError, TypeError, UnicodeError, OSError):
                    pass
            raise RuntimeError(f"Canvas rejected the operation (HTTP {exc.code}){reason}") from None
