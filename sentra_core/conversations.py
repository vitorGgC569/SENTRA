"""Protected logical conversations and durable call journals shared by SENTRA.

The journal records intent before external effects. An interrupted submission
is uncertain, never evidence that it is safe to repeat it.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from sentra_remote.secrets import protect_secret, unprotect_secret
from .telemetry import EventJournal
from . import telemetry_outbox


SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,95}$")
READ_OPERATIONS = {"R", "READ", "LIST", "SEARCH", "DIFF", "STATUS", "JOB", "JOBS", "MEMORY"}


def _schema(db,source):
    """Execute these static DDL blocks without committing the migration lock."""
    for statement in source.split(";"):
        if statement.strip():db.execute(statement)


class ConversationBusy(RuntimeError):
    pass


class UncertainCall(RuntimeError):
    pass


def valid_session_id(value):
    if not isinstance(value, str) or not SESSION_ID.fullmatch(value):
        raise ValueError("session ID must be 8-96 letters, numbers, dots, underscores or hyphens")
    return value


def _encode(value):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > 2_000_000:
        raise ValueError("conversation item exceeds 2 MB")
    protected = protect_secret(text)
    if not protected.startswith(("dpapi:", "keyring:")):
        raise RuntimeError("conversation persistence requires OS protected storage")
    return protected


def _decode(value):
    if not value.startswith(("dpapi:", "keyring:")):
        raise RuntimeError("unprotected conversation data rejected")
    return json.loads(unprotect_secret(value))


@contextmanager
def _lease(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ConversationBusy("conversation is already executing in another process") from exc
        yield
    finally:
        # Closing releases the OS lock, including after an exception.
        handle.close()


class ConversationStore:
    def __init__(self, state_root, *, principal=None):
        self.root = Path(state_root).resolve() / "conversations"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "conversations.sqlite3"
        self.principal = principal or getpass.getuser()
        self.telemetry = None
        self.telemetry_root = Path(state_root)
        self.telemetry_error = None
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError("conversation database requires a newer SENTRA")
            if version == 0:
                _schema(db,"""
                    CREATE TABLE IF NOT EXISTS conversations(
                        id TEXT PRIMARY KEY,owner TEXT NOT NULL,workspace TEXT NOT NULL,
                        created REAL NOT NULL,updated REAL NOT NULL,state TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS messages(
                        conversation_id TEXT NOT NULL REFERENCES conversations(id),
                        seq INTEGER NOT NULL,role TEXT NOT NULL,protected_content TEXT NOT NULL,
                        created REAL NOT NULL,PRIMARY KEY(conversation_id,seq));
                    CREATE TABLE IF NOT EXISTS turns(
                        id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),
                        state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS calls(
                        id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),
                        turn_id TEXT NOT NULL REFERENCES turns(id),kind TEXT NOT NULL,
                        operation TEXT NOT NULL,fingerprint TEXT NOT NULL,state TEXT NOT NULL,
                        provider_id TEXT,protected_input TEXT NOT NULL,protected_result TEXT,
                        created REAL NOT NULL,updated REAL NOT NULL,
                        UNIQUE(turn_id,kind,fingerprint));
                    CREATE INDEX IF NOT EXISTS conversation_owner ON conversations(owner,workspace,updated);
                    CREATE INDEX IF NOT EXISTS call_recovery ON calls(conversation_id,state,fingerprint);
                    PRAGMA user_version=1;
                """)
            if version < 2:
                db.execute("ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'message'")
                db.execute("PRAGMA user_version=2")
            db.execute("CREATE INDEX IF NOT EXISTS message_memory_scan ON messages(created DESC,conversation_id DESC,seq DESC)")
            telemetry_outbox.initialize(db)
            # Additive tables keep existing schema-v2 messages/calls readable by
            # prior clients during rollback. No private response text is copied.
            _schema(db,"""
                CREATE TABLE IF NOT EXISTS provider_usage(
                    call_id TEXT PRIMARY KEY REFERENCES calls(id),
                    model TEXT NOT NULL,usage_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS usage_outbox(
                    call_id TEXT PRIMARY KEY REFERENCES provider_usage(call_id));
                CREATE TABLE IF NOT EXISTS provider_context(
                    call_id TEXT PRIMARY KEY REFERENCES calls(id),context_json TEXT NOT NULL);
            """)
            columns={row[1] for row in db.execute("PRAGMA table_info(provider_context)")}
            upgraded=False
            for metric in ("input","output","reasoning"):
                column="known_"+metric
                if column not in columns:
                    db.execute("ALTER TABLE provider_context ADD COLUMN "+column+" INTEGER NOT NULL DEFAULT 0")
                    upgraded=True
                db.execute("CREATE INDEX IF NOT EXISTS context_missing_"+metric+" ON provider_context("
                    "json_extract(context_json,'$.owner'),json_extract(context_json,'$.workspace')) WHERE "+column+"=0")
            if upgraded:
                db.execute("INSERT OR IGNORE INTO provider_context(call_id,context_json,known_input,known_output,known_reasoning) "
                    "SELECT call_id,context_json,json_type(usage_json,'$.input_tokens') IS NOT NULL,"
                    "json_type(usage_json,'$.output_tokens') IS NOT NULL,json_type(usage_json,'$.reasoning_tokens') IS NOT NULL "
                    "FROM provider_usage WHERE call_id NOT IN (SELECT call_id FROM provider_context)")
                for metric in ("input","output","reasoning"):
                    db.execute("UPDATE provider_context SET known_"+metric+"=EXISTS(SELECT 1 FROM provider_usage u "
                        "WHERE u.call_id=provider_context.call_id AND json_type(u.usage_json,'$."+metric+"_tokens') IS NOT NULL)")
        self._flush_telemetry()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=10000")
            deadline=time.monotonic()+10
            while True:
                try:
                    if db.execute("PRAGMA journal_mode").fetchone()[0].lower()!="wal":
                        db.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if (getattr(exc,"sqlite_errorcode",0)&255 not in {sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED}
                            or time.monotonic()>=deadline):raise
                    time.sleep(.025)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def _tx(self):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db
        self._flush_telemetry()

    def _flush_telemetry(self):
        try:
            if self.telemetry is None:
                self.telemetry = EventJournal(self.telemetry_root)
            telemetry_outbox.flush(self.path,self.telemetry)
            self.telemetry_error=None
        except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
            self.telemetry_error=type(exc).__name__

    def _event(self,db,ident,action,outcome="ok",details=None,turn=None):
        telemetry_outbox.queue(db,self.telemetry,"cli",action,outcome,
            {"session_id":ident,**(details or {})},correlation_id=turn or ident)

    @contextmanager
    def lease(self, session_id):
        ident = valid_session_id(session_id)
        # A fixed hashed filename prevents path traversal and owner collisions.
        name = hashlib.sha256(ident.encode()).hexdigest()
        with _lease(self.root / "leases" / (name + ".lock")):
            yield

    def _owned(self, db, session_id, workspace=None):
        row = db.execute("SELECT * FROM conversations WHERE id=? AND owner=?",
                         (valid_session_id(session_id), self.principal)).fetchone()
        if row is None or (workspace is not None and row["workspace"] != str(Path(workspace).resolve())):
            raise PermissionError("conversation is not accessible in this workspace")
        return dict(row)

    def open(self, workspace, *, session_id=None, resume=False):
        ident = valid_session_id(session_id) if session_id else uuid.uuid4().hex
        workspace = str(Path(workspace).resolve())
        with self.lease(ident), self._tx() as db:
            existing = db.execute("SELECT id FROM conversations WHERE id=?", (ident,)).fetchone()
            if existing:
                self._owned(db, ident, workspace)
                self._recover(db, ident)
                self._event(db,ident,"conversation.resumed")
            else:
                if resume:
                    raise FileNotFoundError("conversation not found; no new session was created")
                now = time.time()
                db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?)",
                           (ident, self.principal, workspace, now, now, "ready"))
                self._event(db,ident,"conversation.created")
        return ident

    def _recover(self, db, ident):
        self._owned(db, ident)
        now = time.time()
        active = db.execute("SELECT id FROM turns WHERE conversation_id=? AND state='running'", (ident,)).fetchall()
        db.execute("UPDATE calls SET state='uncertain',updated=? WHERE conversation_id=? AND state IN ('started','received')",
                   (now, ident))
        changed = db.execute("UPDATE turns SET state='interrupted',updated=? WHERE conversation_id=? AND state='running'",
                             (now, ident)).rowcount
        if changed:
            db.execute("UPDATE conversations SET state='interrupted',updated=? WHERE id=?", (now, ident))
            self._event(db,ident,"conversation.recovered","interrupted",{"interrupted_turns":changed})
            for turn in active:
                results = db.execute("SELECT operation,protected_result FROM calls WHERE turn_id=? AND kind='tool' AND state='completed'", (turn["id"],)).fetchall()
                if results:
                    text = "[RECOVERED TOOL JOURNAL]\nThese calls completed before the interruption. Do not repeat their effects.\n"
                    text += "\n".join(r["operation"] + ": " + str(_decode(r["protected_result"]))[:20000] for r in results)
                    self._append(db, ident, "user", text[:60000])

    @contextmanager
    def executing(self, ident):
        with self.lease(ident):
            with self._tx() as db:
                self._recover(db, ident)
            yield

    def _append(self, db, ident, role, content, kind="message"):
        if role not in {"user", "assistant", "system"} or not isinstance(content, str):
            raise ValueError("invalid conversation message")
        self._owned(db, ident)
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM messages WHERE conversation_id=?", (ident,)).fetchone()[0]
        if kind not in {"message", "user_prompt", "assistant_response", "command", "tool_result", "memory_query", "memory_recall", "journal", "provider_error"}:
            raise ValueError("invalid message provenance kind")
        db.execute("INSERT INTO messages(conversation_id,seq,role,protected_content,created,kind) VALUES(?,?,?,?,?,?)",
                   (ident, seq, role, _encode(content), time.time(), kind))
        db.execute("UPDATE conversations SET updated=? WHERE id=?", (time.time(), ident))
        self._event(db,ident,"conversation.message","ok",{"role":role,"kind":kind,"seq":seq,"characters":len(content)})
        return {"role": role, "content": content, "id": uuid.uuid5(uuid.NAMESPACE_URL, f"{ident}:{seq}").hex}

    def append(self, ident, role, content, *, kind="message"):
        with self._tx() as db:
            return self._append(db, ident, role, content, kind)

    def messages(self, ident, *, limit=1000):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("message limit must be between 1 and 10000")
        with self._connect() as db:
            self._owned(db, ident)
            rows = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY seq DESC LIMIT ?",
                              (ident, limit)).fetchall()
        return [{"role": r["role"], "content": _decode(r["protected_content"]),
                 "id": uuid.uuid5(uuid.NAMESPACE_URL, f"{ident}:{r['seq']}").hex} for r in reversed(rows)]

    def history_window(self, ident, *, max_messages=512, max_chars=320000):
        """Bound provider context while retaining every original message on disk."""
        if not 1 <= max_messages <= 1000 or not 1000 <= max_chars <= 2_000_000:
            raise ValueError("invalid history window budget")
        items, size = [], 0
        with self._connect() as db:
            self._owned(db, ident)
            total = db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?", (ident,)).fetchone()[0]
            for row in db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY seq DESC LIMIT ?", (ident, max_messages)):
                text = _decode(row["protected_content"])
                if size + len(text) > max_chars:
                    if not items:
                        raise ValueError("latest message exceeds provider context budget; start a new conversation or raise the budget")
                    break
                items.append({"role": row["role"], "content": text,
                              "id": uuid.uuid5(uuid.NAMESPACE_URL, f"{ident}:{row['seq']}").hex})
                size += len(text)
        return {"messages": list(reversed(items)), "omitted": total - len(items), "total": total}

    def search(self, workspace, query, *, limit=20):
        return self.search_page(workspace, query, limit=limit)["items"]

    def search_page(self, workspace, query, *, limit=20, after=None,
                    max_scan=2000, budget_seconds=2):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
            raise ValueError("memory query must be 1-200 characters")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("memory search limit must be 1-100")
        matches = []
        needle = query.casefold()
        where, arguments = "", []
        if after is not None:
            if (not isinstance(after, (list, tuple)) or len(after) != 3
                    or type(after[0]) not in {int, float} or not math.isfinite(after[0])
                    or type(after[2]) is not int or after[2] < 1):
                raise ValueError("invalid memory search cursor")
            valid_session_id(after[1])
            where = " AND (m.created,m.conversation_id,m.seq)<(?,?,?)"
            arguments = list(after)
        scanned, cursor, has_more = 0, None, False
        deadline = time.monotonic() + max(.001, budget_seconds)
        with self._connect() as db:
            rows = db.execute("""SELECT m.*,c.workspace FROM messages m JOIN conversations c ON c.id=m.conversation_id
                WHERE c.owner=? AND c.workspace=? AND m.kind NOT IN ('memory_query','memory_recall')
                """ + where + " ORDER BY m.created DESC,m.conversation_id DESC,m.seq DESC",
                (self.principal, str(Path(workspace).resolve()), *arguments))
            for row in rows:
                text = _decode(row["protected_content"])
                scanned += 1
                cursor = [row["created"], row["conversation_id"], row["seq"]]
                at = text.casefold().find(needle)
                if at >= 0:
                    start = max(0, at - 160)
                    matches.append({"session_id": row["conversation_id"], "seq": row["seq"],
                                    "role": row["role"], "excerpt": text[start:start + 800],
                                    "kind": row["kind"], "created": row["created"]})
                if len(matches) >= limit or scanned >= max_scan or time.monotonic() >= deadline:
                    has_more = rows.fetchone() is not None
                    break
        return {"items": matches, "scanned": scanned, "has_more": has_more,
                "next_cursor": cursor if has_more else None}

    def list(self, workspace, *, limit=100):
        with self._connect() as db:
            return [dict(row) for row in db.execute("""SELECT c.*,
                (SELECT COUNT(*) FROM messages WHERE conversation_id=c.id) AS message_count,
                (SELECT COUNT(*) FROM calls WHERE conversation_id=c.id AND state='uncertain') AS uncertain_calls
                FROM conversations c WHERE owner=? AND workspace=? ORDER BY updated DESC LIMIT ?""",
                (self.principal, str(Path(workspace).resolve()), min(1000, max(1, int(limit)))))]

    def status(self, ident):
        with self._connect() as db:
            row = self._owned(db, ident)
            row["message_count"] = db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?", (ident,)).fetchone()[0]
            row["uncertain_calls"] = [dict(c) for c in db.execute("""SELECT id,turn_id,kind,operation,state,provider_id,created
                FROM calls WHERE conversation_id=? AND state='uncertain' ORDER BY created""", (ident,))]
            row["telemetry_pending"] = db.execute("SELECT COUNT(*) FROM telemetry_outbox").fetchone()[0]
            row["telemetry_error"] = self.telemetry_error
            return row

    def tool_receipt(self,ident):
        """Read the single protected call in a dedicated automation receipt."""
        with self._connect() as db:
            self._owned(db,ident)
            rows=db.execute("SELECT * FROM calls WHERE conversation_id=? AND kind='tool' ORDER BY created LIMIT 2",(ident,)).fetchall()
            if not rows:return None
            if len(rows)!=1:raise ValueError("automation receipt contains multiple calls")
            row=dict(rows[0])
            return {"id":row["id"],"turn_id":row["turn_id"],"state":row["state"],
                    "fingerprint":row["fingerprint"],
                    "result":_decode(row["protected_result"]) if row["protected_result"] else None}

    def begin_turn(self, ident, prompt, *, kind="user_prompt"):
        turn = uuid.uuid4().hex
        with self._tx() as db:
            self._owned(db, ident)
            now = time.time()
            db.execute("INSERT INTO turns VALUES(?,?,?,?,?)", (turn, ident, "running", now, now))
            db.execute("UPDATE conversations SET state='running',updated=? WHERE id=?", (now, ident))
            self._event(db,ident,"conversation.turn.started",turn=turn)
            message = self._append(db, ident, "user", prompt, kind)
        return turn, message

    def end_turn(self, ident, turn, state="completed"):
        if state not in {"completed", "interrupted", "provider_error", "uncertain", "limit_reached"}:
            raise ValueError("invalid turn state")
        with self._tx() as db:
            self._owned(db, ident)
            changed = db.execute("UPDATE turns SET state=?,updated=? WHERE id=? AND conversation_id=? AND state='running'",
                                 (state, time.time(), turn, ident)).rowcount
            if changed != 1:
                existing = db.execute("SELECT state FROM turns WHERE id=? AND conversation_id=?", (turn, ident)).fetchone()
                if existing is None:
                    raise PermissionError("turn not accessible")
                if existing["state"] == state or state == "interrupted":
                    return
                raise RuntimeError("turn completion conflicts with an already recorded outcome")
            db.execute("UPDATE conversations SET state=?,updated=? WHERE id=?", (state, time.time(), ident))
            self._event(db,ident,"conversation.turn.finished",state,turn=turn)

    def continue_turn(self, ident):
        with self._tx() as db:
            self._owned(db, ident)
            row = db.execute("SELECT * FROM turns WHERE conversation_id=? ORDER BY created DESC LIMIT 1", (ident,)).fetchone()
            if row is None or row["state"] == "completed":
                raise ValueError("there is no interrupted or unfinished turn to continue")
            if db.execute("SELECT 1 FROM calls WHERE turn_id=? AND state='uncertain' LIMIT 1", (row["id"],)).fetchone():
                raise UncertainCall("resolve uncertain calls in /session before continuing")
            db.execute("UPDATE turns SET state='running',updated=? WHERE id=?", (time.time(), row["id"]))
            db.execute("UPDATE conversations SET state='running',updated=? WHERE id=?", (time.time(), ident))
            self._event(db,ident,"conversation.turn.continued",turn=row["id"])
            message = self._append(db, ident, "user", "[EXPLICIT CONTINUATION]\nContinue the unfinished turn from its durable journal. Reuse recorded tool results; never repeat completed effects.")
            return row["id"], message

    def finish_response(self, ident, turn, text):
        with self._tx() as db:
            self._owned(db, ident)
            message = self._append(db, ident, "assistant", text, "assistant_response")
            db.execute("UPDATE calls SET state='completed',updated=? WHERE conversation_id=? AND turn_id=? AND kind='provider' AND state='received'",
                       (time.time(), ident, turn))
            self._event(db,ident,"provider.response.committed","completed",{"characters":len(text)},turn=turn)
            return message

    @staticmethod
    def fingerprint(operation, args):
        return hashlib.sha256((operation.upper() + "\0" + args).encode("utf-8")).hexdigest()

    def start_tool(self, ident, turn, operation, args):
        if not isinstance(operation, str) or not re.fullmatch(r"[A-Za-z_]{1,64}", operation) or not isinstance(args, str):
            raise ValueError("invalid tool operation or arguments")
        operation = operation.upper()
        fingerprint = self.fingerprint(operation, args)
        with self._tx() as db:
            self._owned(db, ident)
            current = db.execute("SELECT id FROM turns WHERE id=? AND conversation_id=? AND state='running'", (turn, ident)).fetchone()
            if current is None:
                raise PermissionError("turn is not running")
            previous = db.execute("SELECT * FROM calls WHERE turn_id=? AND kind='tool' AND fingerprint=?", (turn, fingerprint)).fetchone()
            if previous:
                if previous["state"] == "completed":
                    return previous["id"], _decode(previous["protected_result"])
                if previous["state"] == "not_executed":
                    db.execute("UPDATE calls SET state='started',protected_result=NULL,updated=? WHERE id=?",
                               (time.time(), previous["id"]))
                    return previous["id"], None
                raise UncertainCall("call has already started; inspect /session before any repeat")
            uncertain = db.execute("""SELECT id FROM calls WHERE conversation_id=? AND kind='tool'
                AND fingerprint=? AND state='uncertain' LIMIT 1""", (ident, fingerprint)).fetchone()
            if uncertain and operation not in READ_OPERATIONS:
                raise UncertainCall("previous tool result is uncertain; inspect /session and resolve call " + uncertain["id"])
            call = uuid.uuid4().hex
            now = time.time()
            db.execute("INSERT INTO calls VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (call, ident, turn, "tool", operation, fingerprint, "started", None,
                        _encode(args), None, now, now))
            self._event(db,ident,"tool.started",details={"call_id":call,"operation":operation},turn=turn)
            return call, None

    def finish_tool(self, ident, call, result):
        with self._tx() as db:
            self._owned(db, ident)
            changed = db.execute("UPDATE calls SET state='completed',protected_result=?,updated=? WHERE id=? AND conversation_id=? AND kind='tool' AND state='started'",
                                 (_encode(result), time.time(), call, ident)).rowcount
            if changed != 1:
                raise RuntimeError("tool call completion conflicts with its journal state")
            row=db.execute("SELECT turn_id,operation FROM calls WHERE id=?",(call,)).fetchone()
            self._event(db,ident,"tool.completed","completed",{"call_id":call,"operation":row["operation"]},turn=row["turn_id"])

    def provider_state(self, ident, turn, provider, provider_id, state, *, context=None):
        if state not in {"submitted", "completed", "rejected", "uncertain"}:
            raise ValueError("invalid delivery state")
        with self._tx() as db:
            owned=self._owned(db, ident)
            if db.execute("SELECT id FROM turns WHERE id=? AND conversation_id=?", (turn, ident)).fetchone() is None:
                raise PermissionError("turn not accessible")
            now = time.time()
            if state == "submitted":
                call_id=uuid.uuid4().hex
                db.execute("INSERT INTO calls VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (call_id, ident, turn, "provider", provider, provider_id,
                            "started", provider_id, _encode({"provider": provider}), None, now, now))
                if context is not None:
                    scope=self._validate_usage_context(owned,context)
                    db.execute("INSERT INTO provider_context(call_id,context_json) VALUES(?,?)",(call_id,scope))
            else:
                db.execute("UPDATE calls SET state=?,updated=? WHERE conversation_id=? AND turn_id=? AND kind='provider' AND provider_id=? AND state='started'",
                           ("received" if state == "completed" else state, now, ident, turn, provider_id))
            self._event(db,ident,"provider.delivery",state,{"provider":provider,"provider_id":provider_id},turn=turn)

    def _validate_usage_context(self,owned,context):
        fields={"owner","workspace","run_id","operation_id","work_item_id","agent_id","goal_id"}
        if not isinstance(context,dict) or set(context)-fields:
            raise ValueError("invalid usage context")
        if (context.get("owner") not in {"cli:"+self.principal,"canvas:"+self.principal} or
                context.get("workspace")!=owned["workspace"]):
            raise PermissionError("usage context belongs to another owner or workspace")
        if any(not isinstance(value,str) or not value or len(value)>32768 for value in context.values()):
            raise ValueError("invalid usage context value")
        return json.dumps(context,sort_keys=True,separators=(",",":"))

    def record_provider_usage(self,ident,turn,provider,provider_id,model,usage,context):
        if not isinstance(model,str) or not 1<=len(model)<=256:
            raise ValueError("invalid usage model")
        metrics={"input_tokens","output_tokens","cached_input_tokens","reasoning_tokens"}
        if not isinstance(usage,dict) or set(usage)-metrics:
            raise ValueError("unsupported provider usage")
        if any(type(value) is not int or not 0<=value<=2**53 for value in usage.values()):
            raise ValueError("invalid provider token count")
        if not usage:return
        with self._tx() as db:
            owned=self._owned(db,ident)
            scope=self._validate_usage_context(owned,context)
            row=db.execute("SELECT id FROM calls WHERE conversation_id=? AND turn_id=? AND "
                "kind='provider' AND operation=? AND provider_id=?",(ident,turn,provider,provider_id)).fetchone()
            if row is None:raise PermissionError("provider call is not accessible")
            encoded=json.dumps(usage,sort_keys=True,separators=(",",":"))
            snapshot=db.execute("SELECT context_json FROM provider_context WHERE call_id=?",(row["id"],)).fetchone()
            if snapshot and snapshot[0]!=scope:raise ValueError("provider usage scope changed after submission")
            previous=db.execute("SELECT model,usage_json,context_json FROM provider_usage WHERE call_id=?",(row["id"],)).fetchone()
            if previous:
                if tuple(previous)!=(model,encoded,scope):raise ValueError("provider usage identity collision")
                return
            db.execute("INSERT INTO provider_usage VALUES(?,?,?,?,?)",(row["id"],model,encoded,scope,time.time()))
            db.execute("INSERT INTO provider_context(call_id,context_json,known_input,known_output,known_reasoning) "
                "VALUES(?,?,?,?,?) ON CONFLICT(call_id) DO UPDATE SET known_input=excluded.known_input,"
                "known_output=excluded.known_output,known_reasoning=excluded.known_reasoning",
                (row["id"],scope,int("input_tokens" in usage),int("output_tokens" in usage),int("reasoning_tokens" in usage)))
            db.execute("INSERT INTO usage_outbox VALUES(?)",(row["id"],))
            self._event(db,ident,"provider.usage.reported","ok",
                {"call_id":row["id"],"provider":provider,"model":model,"usage":usage},turn=turn)

    def pending_usage(self,*,ident=None,limit=128):
        if type(limit) is not int or not 1<=limit<=1024:raise ValueError("invalid usage page")
        with self._connect() as db:
            if ident:self._owned(db,ident)
            return [dict(row) for row in db.execute("SELECT u.*,c.operation AS provider,c.conversation_id "
                "FROM usage_outbox o JOIN provider_usage u ON u.call_id=o.call_id JOIN calls c ON c.id=u.call_id "
                "JOIN conversations s ON s.id=c.conversation_id WHERE s.owner=? "+
                ("AND s.id=? " if ident else "")+"ORDER BY u.created,u.call_id LIMIT ?",
                (self.principal,ident,limit) if ident else (self.principal,limit))]

    def usage_summary(self,ident):
        totals={key:0 for key in ("input_tokens","output_tokens","cached_input_tokens","reasoning_tokens")}
        with self._connect() as db:
            self._owned(db,ident)
            rows=db.execute("SELECT u.usage_json FROM calls c LEFT JOIN provider_usage u ON u.call_id=c.id "
                "WHERE c.conversation_id=? AND c.kind='provider' AND c.state<>'rejected'",(ident,)).fetchall()
            pending=db.execute("SELECT COUNT(*) FROM usage_outbox o JOIN calls c ON c.id=o.call_id "
                "WHERE c.conversation_id=?",(ident,)).fetchone()[0]
        reported=0;unreported=0
        for row in rows:
            if row[0] is None:
                unreported+=1
                continue
            usage=json.loads(row[0]);reported+=1
            if not {"input_tokens","output_tokens"}<=usage.keys():unreported+=1
            for metric in totals:totals[metric]+=usage.get(metric,0)
        return {**totals,"total_tokens":totals["input_tokens"]+totals["output_tokens"],
                "reported_calls":reported,"unreported_calls":unreported,
                "fully_reported":bool(reported) and not unreported,"projection_pending":pending,
                "pricing_known":False}

    def acknowledge_usage(self,call_id):
        with self._connect() as db:
            db.execute("DELETE FROM usage_outbox WHERE call_id=? AND call_id IN "
                "(SELECT c.id FROM calls c JOIN conversations s ON s.id=c.conversation_id WHERE s.owner=?)",
                (call_id,self.principal))

    def resolve_call(self, ident, call, *, executed, evidence):
        if type(executed) is not bool or not isinstance(evidence, str) or not 1 <= len(evidence.strip()) <= 4000:
            raise ValueError("explicit executed/not-executed decision and evidence are required")
        with self.lease(ident), self._tx() as db:
            self._owned(db, ident)
            row = db.execute("SELECT * FROM calls WHERE id=? AND conversation_id=? AND state='uncertain'", (call, ident)).fetchone()
            if row is None:
                raise ValueError("uncertain call not found")
            result = "Recovery decision: " + ("executed" if executed else "not executed") + ". Evidence: " + evidence
            db.execute("UPDATE calls SET state=?,protected_result=?,updated=? WHERE id=?",
                       ("completed" if executed else "not_executed", _encode(result), time.time(), call))
            self._event(db,ident,"call.resolved","executed" if executed else "not_executed",{"call_id":call,"kind":row["kind"]},turn=row["turn_id"])
            self._append(db, ident, "user", "[RECOVERY JOURNAL]\n" + result + "\nDo not automatically repeat the previous action.")
