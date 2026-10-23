"""Authenticated, owner-local PTY host. Canvas restart only detaches viewers.

Host callers retain authorization responsibility: this endpoint is never given
to renderer/mobile/agents. It accepts no network bind other than loopback.
"""
from __future__ import annotations

import base64
import codecs
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .pty_history import PtyHistory, OUTPUT_CHARS
from .pty_input_effects import REFERENCE_FIELDS, validate_reference, validate_payload

VERSION = 1
MAX_CACHE_BYTES = 16 * 1024 * 1024
MAX_FRAME = 256 * 1024
MAX_INPUT_EFFECTS = 250000


class UncertainPTY(RuntimeError):
    pass


class PtyServer(ThreadingHTTPServer):
    # server_close joins accepted handlers before serve() closes journals and
    # releases installation ownership. Socket reads already have a deadline.
    daemon_threads = False
    block_on_close = True


class OutputCache:
    """Bounded UTF-8 text cache with explicit monotonically increasing cursors."""
    def __init__(self, limit=MAX_CACHE_BYTES):
        self.limit, self.size = limit, 0
        self.entries = OrderedDict()
        self.lock = threading.RLock()

    def append(self, key, text):
        with self.lock:
            base, previous = self.entries.pop(key, (0, ""))
            start = base + len(previous)
            self.size -= len(previous.encode("utf-8"))
            value = previous + text
            encoded = value.encode("utf-8")
            if len(encoded) > self.limit:
                value = encoded[-self.limit:].decode("utf-8", "ignore")
                base += len(previous + text) - len(value)
            self.entries[key] = (base, value)
            self.size += len(value.encode("utf-8"))
            for old, (offset, content) in list(self.entries.items()):
                if self.size <= self.limit:
                    break
                # Retain cursor metadata even when all text is evicted.
                self.entries[old] = (offset + len(content), "")
                self.size -= len(content.encode("utf-8"))
            return start, start + len(text)

    def read(self, key, cursor=0):
        with self.lock:
            base, text = self.entries.get(key, (0, ""))
            end = base + len(text)
            truncated = cursor < base or cursor > end
            cursor = min(end, max(base, cursor))
            # Bound HTTP frames; never claim bytes beyond this chunk.
            part = text[cursor-base:cursor-base+OUTPUT_CHARS]
            return {"text": part, "cursor": cursor+len(part), "base": base,
                    "truncated": truncated, "head": end}


class PtyHost:
    def __init__(self, state_dir, factory=None):
        from .terminal import WindowsPTY
        self.state = Path(state_dir).resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.factory = factory or WindowsPTY
        self.runtime_id = uuid.uuid4().hex
        self.sessions = {}
        self.draining = False
        self.last_probe = None
        self.lock = threading.RLock()
        self.cache = OutputCache()
        self.db = sqlite3.connect(self.state/"pty-effects.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL, result TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS input_effect_refs (key TEXT PRIMARY KEY,reference TEXT NOT NULL)")
        self.db.execute("UPDATE effects SET state='uncertain' WHERE state='in_flight'")
        self.db.commit()
        try:
            self.history = PtyHistory(self.state)
        except BaseException:
            self.db.close()
            raise
        self._closed = False

    def _session(self, fields):
        item = self.sessions.get(fields.get("terminal_id"))
        if not item or item["workspace_id"] != fields.get("workspace_id"):
            raise PermissionError("PTY not in this workspace")
        return item

    def dispatch(self, method, fields, key=None):
        if method == "health":
            return {"protocol_version": VERSION, "runtime_id": self.runtime_id,
                    "pid": os.getpid(), "state": "draining" if self.draining else "live", "coverage": "handshake",
                    "owns_fresh_sessions": not self.draining, "sessions": len(self.sessions),
                    "last_probe": self.last_probe,
                    "cache_bytes": self.cache.size, "state_dir": str(self.state),
                    "history_protocol_version": 1, "history": self.history.status(),
                    "capabilities": {"persistent_history": self.history.error is None, "consumer_cursor": True,
                                     "ansi_tui_snapshots": bool(self.history.snapshots and self.history.snapshots.available),
                                     "producer_queue_bounded": True, "agent_binding_proof": True,
                                     "correlated_input_receipts": 1}}
        if method == "input_effect":
            reference = validate_reference(fields)
            with self.lock:
                saved = self.db.execute("SELECT r.reference,e.state,e.result FROM input_effect_refs r "
                    "JOIN effects e ON e.key=r.key WHERE r.key=?", (reference['effect_key'],)).fetchone()
            if saved is None:
                return {'input_receipt_protocol_version':1,'found':False,'resolved':False,'automatic_retry':False,'may_resend':False,'task_completion_verified':False}
            if json.loads(saved[0]) != reference:
                raise PermissionError('terminal input receipt belongs to another exact scope')
            receipt = json.loads(saved[2]) if saved[2] else None
            resolved = saved[1] == 'done' and receipt is not None
            if resolved and (any(receipt.get(k) != v for k,v in reference.items())
                    or receipt.get('stage') != 'delivered_to_process'
                    or receipt.get('input_receipt_protocol_version') != 1
                    or receipt.get('automatic_retry') is not False
                    or receipt.get('task_completion_verified') is not False):
                raise RuntimeError('terminal input receipt binding is invalid')
            return {'input_receipt_protocol_version':1,'found':True,'resolved':resolved,'state':saved[1], 'receipt':receipt,
                    'automatic_retry':False,'may_resend':False,'task_completion_verified':False}
        if method in {"drain", "cancel_drain", "stop_when_idle"}:
            with self.lock:
                live = sum(s['pty'].poll() is None for s in self.sessions.values())
                if method == "stop_when_idle" and (not self.draining or live):
                    raise ValueError("explicit drain and zero live PTYs required; active processes are preserved")
                if method == "stop_when_idle":
                    for session in self.sessions.values():
                        session['pty'].close(graceful_seconds=0)
                        if not getattr(session['pty'],'wait_output',lambda _timeout:True)(2):
                            raise RuntimeError('PTY output reader has not drained; daemon remains available')
                    for ident,session in self.sessions.items():
                        self.history.ended(ident,session['pty'].poll(),drained=True)
                if method == "stop_when_idle" and not self.history.flush():
                    raise RuntimeError("PTY history checkpoint not ready; daemon remains available")
                self.draining = method != "cancel_drain"
                return {"draining": self.draining, "live_sessions": live,
                        "safe_to_stop": self.draining and live == 0}
        if method == "self_test":
            # Fixed diagnostic command, never arbitrary caller input. A handshake
            # and an inventory cannot certify actual Windows PTY execution.
            with self.lock:
                if self.draining:
                    raise ValueError("PTY host draining")
                if self.last_probe and time.time() - self.last_probe['observed_at'] < 30:
                    return self.last_probe
                marker = 'SENTRA_PTY_' + uuid.uuid4().hex
                output = bytearray()
                process = self.factory([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/q', '/c', 'echo ' + marker],
                    self.state, lambda chunk: output.extend(chunk))
                try:
                    deadline = time.monotonic() + 4
                    while time.monotonic() < deadline:
                        if marker.encode() in output and process.poll() == 0:
                            self.last_probe = {"coverage": "process_execution", "functional": True,
                                "observed_at": time.time(), "runtime_id": self.runtime_id,
                                "backend": "ConPTY", "input_tested": False}
                            return self.last_probe
                        time.sleep(.02)
                    raise RuntimeError("PTY process execution probe failed")
                finally:
                    process.close(exit_input=b'exit\r')
        if method == "inventory":
            with self.lock:
                result = []
                for ident, session in self.sessions.items():
                    code = session['pty'].poll()
                    result.append({"terminal_id": ident, "workspace_id": session["workspace_id"],
                         "pid": session["pty"].pid, "exit_code": code, "process_live": code is None,
                         "process_state": "live" if code is None else "ended",
                         "agent_token_sha256": session.get("agent_token_sha256"), "runtime_id": self.runtime_id})
                    result[-1]['input_generation'] = session['input_generation']
                if fields.get('include_history'):
                    result.extend({**row, "runtime_id": self.runtime_id, "process_live": False,
                                   "process_state": "history_restored", "restoration_creates_process": False}
                                  for row in self.history.inventory() if row['terminal_id'] not in self.sessions)
                return result
        if method == 'checkpoint':
            return self.history.checkpoint(fields.get('workspace_id'),fields.get('terminal_id'))
        if method == "output":
            cursor = fields.get("cursor", 0)
            if type(cursor) is not int or cursor < 0:
                raise ValueError("invalid output cursor")
            if fields.get('terminal_id') not in self.sessions:
                return {**self.history.read(fields.get('workspace_id'), fields.get('terminal_id'), cursor),
                        **self.history.geometry(fields.get('terminal_id')),
                        'checkpoint_supported':self.history.checkpoint_supported(fields.get('terminal_id')),
                        "runtime_id": self.runtime_id}
            s = self._session(fields)
            data = self.cache.read(fields["terminal_id"], cursor)
            code = s["pty"].poll()
            if code is not None and not s.get('exit_recorded'):
                self.history.ended(fields['terminal_id'], code)
                s['exit_recorded'] = True
            if code is not None and not s.get('output_drained') and getattr(s['pty'],'wait_output',lambda _timeout:False)(0):
                self.history.ended(fields['terminal_id'],code,drained=True)
                s['output_drained']=True
            if not data['text'] and data['truncated']:
                # An idle session can lose its whole memory window to another
                # producer while its protected history still exists on disk.
                restored = self.history.read(fields['workspace_id'], fields['terminal_id'], cursor)
                if restored['text']:
                    return {**restored, "runtime_id": self.runtime_id, "exit_code": code,
                            **self.history.geometry(fields['terminal_id']),
                            'checkpoint_supported':self.history.checkpoint_supported(fields['terminal_id']),
                            "process_live": code is None, "process_state": "live" if code is None else "ended"}
            status = self.history.status(fields['terminal_id'], data['cursor'] - len(data['text']), data['cursor'])
            return {**data, **status, "exit_code": code, "runtime_id": self.runtime_id,
                    **self.history.geometry(fields['terminal_id']),
                    'checkpoint_supported':self.history.checkpoint_supported(fields['terminal_id']),
                    "process_live": code is None, "process_state": "live" if code is None else "ended"}
        if method == "resize":
            s = self._session(fields)
            cols, rows = fields.get("cols"), fields.get("rows")
            if type(cols) is not int or type(rows) is not int or not 20<=cols<=500 or not 5<=rows<=200:
                raise ValueError("invalid geometry")
            with s['output_lock']:
                self.history.resize(fields['terminal_id'],cols,rows)
            try:s["pty"].resize(cols, rows)
            except BaseException:
                self.history.invalidate_checkpoint(fields['terminal_id']);raise
            return {"resized": True}
        if method not in {"create", "write", "write_correlated", "close"}:
            raise ValueError("unsupported PTY method")
        if not isinstance(key, str) or not 8<=len(key)<=160:
            raise ValueError("durable effect identity required")
        fingerprint = hashlib.sha256(json.dumps([method, fields], sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        with self.lock:
            reference = None
            if method == 'write_correlated':
                if set(fields) != REFERENCE_FIELDS | {'data'}:
                    raise ValueError('exact correlated input fields required')
                reference = validate_payload({k:fields[k] for k in REFERENCE_FIELDS},
                    base64.b64decode(fields['data'],validate=True))
                if key != reference['effect_key']:
                    raise ValueError('terminal input effect key differs from selector')
            row = self.db.execute("SELECT fingerprint,state,result FROM effects WHERE key=?", (key,)).fetchone()
            if row:
                if not hmac.compare_digest(row[0], fingerprint):
                    raise ValueError("idempotency key payload changed")
                if row[1] == "done":
                    result = json.loads(row[2])
                    if method == "create" and result.get("runtime_id") != self.runtime_id:
                        raise UncertainPTY("historical session is not a live process; no respawn")
                    return result
                raise UncertainPTY("PTY effect requires observation; never replay")
            if reference:
                session = self._session(fields)
                if reference['runtime_id'] != self.runtime_id or reference['generation'] != session['input_generation']:
                    raise PermissionError('physical terminal input generation changed')
                if self.db.execute('SELECT COUNT(*) FROM input_effect_refs').fetchone()[0] >= MAX_INPUT_EFFECTS:
                    raise ValueError('terminal input receipt capacity reached; no input admitted')
            with self.db:
                if reference:
                    self.db.execute('INSERT INTO input_effect_refs VALUES(?,?)', (key,json.dumps(reference,sort_keys=True)))
                self.db.execute("INSERT INTO effects VALUES(?,?,'in_flight',NULL)", (key, fingerprint))
            try:
                if method == "create":
                    if self.draining:
                        raise ValueError("PTY host draining; no new sessions accepted")
                    ident, workspace = fields["terminal_id"], fields["workspace_id"]
                    if not isinstance(ident,str) or not isinstance(workspace,str) or not ident or len(ident)>128:
                        raise ValueError("invalid terminal identity")
                    if ident in self.sessions or len(self.sessions)>=512 or len([s for s in self.sessions.values() if s["pty"].poll() is None]) >= 32:
                        raise ValueError("PTY identity occupied or quota exhausted")
                    decoder = codecs.getincrementaldecoder("utf-8")("replace")
                    output_lock=threading.RLock()
                    self.history.register(workspace, ident, self.runtime_id)
                    def output(chunk):
                        with output_lock:
                            text = decoder.decode(chunk)
                            start, _end = self.cache.append(ident, text)
                            self.history.append(ident, start, text)
                    pty = self.factory(fields["argv"], Path(fields["cwd"]), output,
                        env=fields.get("env"))
                    token = (fields.get('env') or {}).get('SENTRA_CANVAS_AGENT_TOKEN')
                    self.sessions[ident] = {"pty": pty, "workspace_id": workspace,
                        'output_lock':output_lock, 'input_generation':uuid.uuid4().hex,
                        "agent_token_sha256": hashlib.sha256(token.encode()).hexdigest() if token else None}
                    self.history.bind(ident, pty.pid)
                    result = {"terminal_id": ident, "pid": pty.pid, "runtime_id": self.runtime_id,
                              'input_generation':self.sessions[ident]['input_generation']}
                elif method in {"write", "write_correlated"}:
                    s = self._session(fields)
                    data = base64.b64decode(fields["data"], validate=True)
                    if not data or len(data)>16384:
                        raise ValueError("invalid input frame")
                    s["pty"].write(data)
                    result = ({**reference,'input_receipt_protocol_version':1,'stage':'delivered_to_process','task_completion_verified':False,
                               'automatic_retry':False} if reference else {"stage": "delivered", "model_completed": False})
                else:
                    s = self._session(fields)
                    exit_input = base64.b64decode(fields.get("exit_input", "ZXhpdA0="), validate=True)
                    if len(exit_input)>128:
                        raise ValueError("invalid close input")
                    s["pty"].close(exit_input=exit_input)
                    if not getattr(s['pty'],'wait_output',lambda _timeout:True)(2):
                        raise UncertainPTY('PTY closed but final output is not confirmed')
                    self.history.ended(fields['terminal_id'], s['pty'].poll(),drained=True)
                    s['exit_recorded'] = True
                    result = {"closed": True}
            except BaseException:
                self.db.execute("UPDATE effects SET state='uncertain' WHERE key=?", (key,))
                self.db.commit()
                raise
            self.db.execute("UPDATE effects SET state='done',result=? WHERE key=?", (json.dumps(result),key))
            self.db.commit()
            return result

    def close(self):
        if not self._closed:
            self.history.close()
            self.db.close()
            self._closed = True


def serve(state_dir):
    from .instance_lock import InstanceLock
    from sentra_remote.secrets import protect_secret
    state = Path(state_dir).resolve()
    lease = InstanceLock(state/"pty-owner.lock")
    host = PtyHost(state)
    token = secrets.token_urlsafe(36)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            if self.path != "/v1/pty" or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer "+token):
                self.send_error(403);return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0<size<=MAX_FRAME:
                    raise ValueError("invalid frame size")
                body = json.loads(self.rfile.read(size))
                result = host.dispatch(body["method"], body.get("fields", {}), body.get("key"))
                data = json.dumps({"ok":True,"value":result}).encode()
                status = 200
            except Exception as exc:
                status = 409 if isinstance(exc,UncertainPTY) else 400
                data = json.dumps({"ok":False,"error":type(exc).__name__}).encode()
            self.send_response(status);self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
            if status == 200 and body['method'] == 'stop_when_idle':
                threading.Thread(target=server.shutdown, daemon=True).start()
    server = PtyServer(("127.0.0.1",0),Handler)
    original=server.get_request
    def request():
        sock,addr=original();sock.settimeout(5);return sock,addr
    server.get_request=request
    descriptor = {**host.dispatch("health",{}), "port":server.server_port,
                  "protected_token":protect_secret(token)}
    temporary = state/("pty-endpoint-"+uuid.uuid4().hex+".tmp")
    temporary.write_text(json.dumps(descriptor));temporary.replace(state/"pty-endpoint.json")
    try:
        server.serve_forever()
    finally:
        server.server_close();host.close()
        descriptor_path = state/'pty-endpoint.json'
        try:
            if json.loads(descriptor_path.read_text()).get('runtime_id') == host.runtime_id:
                descriptor_path.unlink()
        except (OSError, ValueError):
            pass
        lease.close()


if __name__ == "__main__":
    serve(sys.argv[1])
