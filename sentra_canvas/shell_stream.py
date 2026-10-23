"""Durable presentation feed. Observations never authorize a send or an effect.

One project cursor multiplexes all of its conversations. The current snapshot
and its event are committed together before any HTTP consumer can observe them.
Compaction retains current snapshots; an expired cursor explicitly resets.
"""
from __future__ import annotations

from contextlib import closing, contextmanager, nullcontext
from collections import OrderedDict
import copy
import hashlib
import json
import threading
import time
import uuid

from sentra_core.conversations import _decode, _encode
from sentra_core.model_prose import prose_prefix

MAX_EVENTS = 2048
MAX_CONTENT_CHARS = 200_000
INLINE_UTF16_UNITS = 131_072
CONTENT_CHUNK_CHARS = 65_536
CONTENT_PAGE_UTF8_BYTES = CONTENT_CHUNK_CHARS * 4
MAX_FULL_CONTENT_BYTES = 8_000_000
VISIBLE_STATES = frozenset({"generating", "confirming", "interrupted", "preview_unavailable", "committed"})


def _identifier(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c) < 32 for c in value):
        raise ValueError("stable stream scope required")
    return value


def content_window(text):
    """Bound the wire/window in JS UTF-16 units without splitting Unicode."""
    tail = text[-INLINE_UTF16_UNITS:]
    encoded = tail.encode("utf-16-le")
    if len(encoded) > INLINE_UTF16_UNITS * 2:
        tail = encoded[-INLINE_UTF16_UNITS * 2:].decode("utf-16-le", errors="ignore")
    return tail


class ShellStreamJournal:
    def __init__(self, store, owner, *, bind_queue=False):
        self.store, self.owner = store, _identifier(owner)
        self.bind_queue = bind_queue
        self.changed = threading.Condition(threading.RLock())
        self._transaction_local = threading.local()
        self._read_cache = OrderedDict()
        self._read_cache_bytes = 0
        self._read_cache_epoch = 0
        self._read_cache_lock = threading.RLock()
        self.closed = threading.Event()
        with closing(store.connect("shell")) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS shell_stream_epochs(
                    owner TEXT PRIMARY KEY, epoch TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS shell_stream_heads(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    space_id TEXT NOT NULL, sequence INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                    protected_snapshot TEXT NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(owner,project_id,conversation_id));
                CREATE TABLE IF NOT EXISTS shell_stream_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
                    project_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    protected_event TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS shell_stream_scope ON shell_stream_events(owner,project_id,seq);
                CREATE TABLE IF NOT EXISTS shell_stream_seen_operations(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    PRIMARY KEY(owner,project_id,conversation_id,operation_id));
                CREATE TABLE IF NOT EXISTS shell_stream_contents(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    reference_id TEXT NOT NULL, space_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                    total_chars INTEGER NOT NULL, total_utf8_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
                    protected_manifest TEXT NOT NULL,
                    PRIMARY KEY(owner,project_id,conversation_id,reference_id));
                CREATE TABLE IF NOT EXISTS shell_stream_content_chunks(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, chunk_sha256 TEXT NOT NULL,
                    protected_content TEXT NOT NULL,
                    PRIMARY KEY(owner,project_id,chunk_sha256));
                CREATE TABLE IF NOT EXISTS shell_stream_content_pages(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    reference_id TEXT NOT NULL, chunk_offset INTEGER NOT NULL, chunk_sha256 TEXT NOT NULL,
                    PRIMARY KEY(owner,project_id,conversation_id,reference_id,chunk_offset));
                CREATE TABLE IF NOT EXISTS shell_stream_content_references(
                    owner TEXT NOT NULL, project_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL, reference_id TEXT NOT NULL,
                    PRIMARY KEY(owner,project_id,conversation_id,sequence));
                CREATE INDEX IF NOT EXISTS shell_stream_content_reference_roots
                    ON shell_stream_content_references(owner,project_id,conversation_id,reference_id);
                CREATE INDEX IF NOT EXISTS shell_stream_content_chunk_roots
                    ON shell_stream_content_pages(owner,project_id,chunk_sha256);
            """)
            db.execute("INSERT OR IGNORE INTO shell_stream_epochs VALUES(?,?)", (self.owner, uuid.uuid4().hex))
            self.epoch = db.execute("SELECT epoch FROM shell_stream_epochs WHERE owner=?", (self.owner,)).fetchone()["epoch"]

    @contextmanager
    def _transaction(self):
        existing = getattr(self._transaction_local, "db", None)
        if existing is not None:
            yield existing
            return
        with closing(self.store.connect("shell")) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db
        # Invalidate after the commit, including the outer ingestion batch.
        self._read_cache_epoch += 1

    def publish_many(self, observations):
        """Commit a small ingestion batch once, before waking any consumers."""
        observations = list(observations)
        if len(observations) > 64:
            raise ValueError("stream batch budget exceeded")
        if not observations:
            return []
        with self.changed, self._transaction() as db:
            previous = getattr(self._transaction_local, "db", None)
            self._transaction_local.db = db
            try:
                return [self.publish(*item) for item in observations]
            finally:
                self._transaction_local.db = previous

    def publish(self, project_id, space_id, conversation_id, preview, *, _retain_reference=False):
        project_id, space_id, conversation_id = map(_identifier, (project_id, space_id, conversation_id))
        if not isinstance(preview, dict) or preview.get("status") not in VISIBLE_STATES:
            raise ValueError("invalid stream observation")
        if type(_retain_reference) is not bool or (preview.get("content_ref") is not None and not _retain_reference):
            raise ValueError("upstream observations cannot select a protected stream reference")
        operation_id = _identifier(preview.get("operation_id"))
        text = preview.get("content", "")
        if not isinstance(text, str):
            raise ValueError("stream content must be text")
        # Never persist tool directives in the renderer's projection.
        text = prose_prefix(text, complete=preview["status"] == "committed")
        full_text = text
        total_bytes = len(text.encode("utf-8"))
        text = content_window(text)
        snapshot = {key: preview[key] for key in (
            "status", "activity", "content_revision", "truncated", "message_id", "receipt_id", "timings_ms",
        ) if key in preview}
        snapshot.update(content=text, operation_id=operation_id, partial=True,
                        authoritative=False, closes_trio=False, automatic_retry=False)
        content_ref = None
        if total_bytes > MAX_FULL_CONTENT_BYTES:
            snapshot.update(status="preview_unavailable", truncated=True,
                activity="A prévia excedeu seu orçamento de conteúdo recuperável.",
                content_error={"code": "stream_content_budget_exceeded", "limit_utf8_bytes": MAX_FULL_CONTENT_BYTES,
                               "observed_utf8_bytes": total_bytes})
        elif text != full_text:
            digest = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
            identity = json.dumps([operation_id, preview.get("content_revision"), digest], separators=(",", ":"))
            content_ref = {"reference_id": "stream-" + hashlib.sha256(identity.encode()).hexdigest(),
                "total_chars": len(full_text), "total_utf8_bytes": total_bytes, "sha256": digest,
                "action": "stream_content", "page_max_chars": CONTENT_CHUNK_CHARS,
                "page_max_utf8_bytes": CONTENT_PAGE_UTF8_BYTES}
            snapshot.update(content_ref=content_ref, truncated=True, content_offset=len(full_text)-len(text))
        reference_link = content_ref
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        with self.changed:
            with self._transaction() as db:
                if self.bind_queue:
                    binding = db.execute("SELECT operation_id FROM canvas_shell_queue WHERE owner=? AND project_id=? AND conversation_id=? "
                        "ORDER BY created_at DESC LIMIT 1", (self.owner, project_id, conversation_id)).fetchone()
                    if binding is None or binding["operation_id"] != operation_id:
                        return None
                old = db.execute("SELECT * FROM shell_stream_heads WHERE owner=? AND project_id=? AND conversation_id=?",
                    (self.owner, project_id, conversation_id)).fetchone()
                if not _retain_reference and old is not None and old["fingerprint"] == fingerprint:
                    return old["sequence"]
                previous = _decode(old["protected_snapshot"]) if old else {}
                if _retain_reference:
                    # This private transition is used ONLY to interrupt an
                    # already protected head. A renderer/upstream-selected
                    # reference, another round or a changed window is refused.
                    retained=previous.get("content_ref")
                    fields=("operation_id","content_revision","content_offset","content_ref","content","truncated")
                    if (old is None or old["space_id"] != space_id or not isinstance(retained,dict)
                            or snapshot["status"] not in {"interrupted","preview_unavailable"} or content_ref is not None
                            or snapshot["content"] != previous.get("content")
                            or any(preview.get(key)!=previous.get(key) for key in fields)):
                        raise ValueError("retained stream reference differs from the current protected head")
                    bound=db.execute("SELECT r.reference_id FROM shell_stream_content_references r JOIN shell_stream_contents m "
                        "ON m.owner=r.owner AND m.project_id=r.project_id AND m.conversation_id=r.conversation_id AND m.reference_id=r.reference_id "
                        "WHERE r.owner=? AND r.project_id=? AND r.conversation_id=? AND r.sequence=? AND r.reference_id=? "
                        "AND m.space_id=? AND m.operation_id=?",
                        (self.owner,project_id,conversation_id,old["sequence"],retained["reference_id"],space_id,operation_id)).fetchone()
                    if bound is None:
                        raise ValueError("retained stream reference has no protected head root")
                    manifest=self.content(project_id,space_id,conversation_id,retained["reference_id"],limit=1,_db=db)
                    if any(manifest[key]!=retained.get(key) for key in ("sha256","total_chars","total_utf8_bytes")):
                        raise RuntimeError("retained stream reference conflicts with its protected manifest")
                    reference_link=retained
                    snapshot.update(content_ref=retained,content_offset=previous["content_offset"],truncated=True)
                    encoded=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(",", ":"))
                    fingerprint=hashlib.sha256(encoded.encode()).hexdigest()
                    if old["fingerprint"]==fingerprint:
                        return old["sequence"]
                if previous.get("operation_id") and previous["operation_id"] != operation_id:
                    seen = db.execute("SELECT operation_id FROM shell_stream_seen_operations WHERE owner=? AND project_id=? AND conversation_id=? AND operation_id=?",
                        (self.owner, project_id, conversation_id, operation_id)).fetchone()
                    if seen:
                        return old["sequence"]
                    # Include heads made by a previous build during additive migration.
                    db.execute("INSERT OR IGNORE INTO shell_stream_seen_operations VALUES(?,?,?,?)",
                        (self.owner, project_id, conversation_id, previous["operation_id"]))
                # Once confirmed, a late preview from the same producer cannot regress it.
                if previous.get("operation_id") == operation_id and previous.get("status") == "committed" and snapshot["status"] != "committed":
                    return old["sequence"]
                if content_ref is not None:
                    self._persist_content(db, project_id, space_id, conversation_id, operation_id, content_ref, full_text)
                append = (old is not None and previous.get("operation_id") == operation_id
                          and previous.get("content_revision") == snapshot.get("content_revision")
                          and text.startswith(previous.get("content", "")))
                event = {"conversation_id": conversation_id, "space_id": space_id,
                         "operation_id": operation_id, "kind": "delta" if append else "snapshot",
                         "base_sequence": old["sequence"] if append else 0,
                         "preview": {k: v for k, v in snapshot.items() if k != "content"},
                         "text": text[len(previous.get("content", "")):] if append else text}
                now = time.time()
                inserted = db.execute("INSERT INTO shell_stream_events(owner,project_id,conversation_id,protected_event,created_at) VALUES(?,?,?,?,?)",
                    (self.owner, project_id, conversation_id, _encode(event), now))
                sequence = inserted.lastrowid
                if sequence is None:
                    sequence = db.execute("SELECT MAX(seq) AS seq FROM shell_stream_events WHERE owner=? AND project_id=?",
                        (self.owner, project_id)).fetchone()["seq"]
                db.execute("INSERT INTO shell_stream_heads VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(owner,project_id,conversation_id) DO UPDATE SET "
                    "space_id=excluded.space_id,sequence=excluded.sequence,fingerprint=excluded.fingerprint,"
                    "protected_snapshot=excluded.protected_snapshot,updated_at=excluded.updated_at",
                    (self.owner, project_id, conversation_id, space_id, sequence, fingerprint, _encode(snapshot), now))
                db.execute("INSERT OR IGNORE INTO shell_stream_seen_operations VALUES(?,?,?,?)",
                    (self.owner, project_id, conversation_id, operation_id))
                if reference_link is not None:
                    db.execute("INSERT INTO shell_stream_content_references VALUES(?,?,?,?,?)",
                        (self.owner, project_id, conversation_id, sequence, reference_link["reference_id"]))
                # Bound event history without discarding current content or pending work.
                cutoff = db.execute("SELECT seq FROM shell_stream_events WHERE owner=? AND project_id=? ORDER BY seq DESC LIMIT 1 OFFSET ?",
                    (self.owner, project_id, MAX_EVENTS - 1)).fetchone()
                if cutoff:
                    db.execute("DELETE FROM shell_stream_events WHERE owner=? AND project_id=? AND seq<?",
                        (self.owner, project_id, cutoff["seq"]))
                    self._compact_content(db, project_id, cutoff["seq"])
            self.changed.notify_all()
            return sequence

    def _persist_content(self, db, project_id, space_id, conversation_id, operation_id, reference, text):
        scope = (self.owner, project_id, conversation_id, reference["reference_id"])
        existing = db.execute("SELECT sha256,total_chars,total_utf8_bytes,space_id,operation_id,protected_manifest FROM shell_stream_contents "
            "WHERE owner=? AND project_id=? AND conversation_id=? AND reference_id=?", scope).fetchone()
        if existing:
            if (existing["sha256"],existing["total_chars"],existing["total_utf8_bytes"],existing["space_id"],existing["operation_id"]) != (
                    reference["sha256"],len(text),reference["total_utf8_bytes"],space_id,operation_id):
                raise RuntimeError("immutable stream reference conflicts with stored content")
            return
        chunk_map=[{"chunk_offset":offset,"sha256":hashlib.sha256(text[offset:offset+CONTENT_CHUNK_CHARS].encode("utf-8")).hexdigest()}
                   for offset in range(0,len(text),CONTENT_CHUNK_CHARS)]
        manifest={**reference,"owner":self.owner,"project_id":project_id,"space_id":space_id,
                  "conversation_id":conversation_id,"operation_id":operation_id,"chunks":chunk_map}
        db.execute("INSERT INTO shell_stream_contents VALUES(?,?,?,?,?,?,?,?,?,?)",
            (*scope, space_id, operation_id, len(text), reference["total_utf8_bytes"], reference["sha256"],_encode(manifest)))
        for entry in chunk_map:
            offset,digest = entry["chunk_offset"],entry["sha256"]
            chunk = text[offset:offset+CONTENT_CHUNK_CHARS]
            if db.execute("SELECT 1 FROM shell_stream_content_chunks WHERE owner=? AND project_id=? AND chunk_sha256=?",
                    (self.owner, project_id, digest)).fetchone() is None:
                db.execute("INSERT INTO shell_stream_content_chunks VALUES(?,?,?,?)",
                    (self.owner, project_id, digest, _encode(chunk)))
            db.execute("INSERT INTO shell_stream_content_pages VALUES(?,?,?,?,?,?)", (*scope, offset, digest))

    def _compact_content(self, db, project_id, cutoff):
        # Inactive conversations can have heads older than the event window.
        # Retain those roots, plus every event reference still replayable.
        db.execute("DELETE FROM shell_stream_content_references WHERE owner=? AND project_id=? AND sequence<? "
            "AND sequence NOT IN (SELECT sequence FROM shell_stream_heads WHERE owner=? AND project_id=?)",
            (self.owner, project_id, cutoff, self.owner, project_id))
        db.execute("DELETE FROM shell_stream_content_pages WHERE owner=? AND project_id=? AND NOT EXISTS "
            "(SELECT 1 FROM shell_stream_content_references r WHERE r.owner=shell_stream_content_pages.owner "
            "AND r.project_id=shell_stream_content_pages.project_id AND r.conversation_id=shell_stream_content_pages.conversation_id "
            "AND r.reference_id=shell_stream_content_pages.reference_id)", (self.owner, project_id))
        db.execute("DELETE FROM shell_stream_contents WHERE owner=? AND project_id=? AND NOT EXISTS "
            "(SELECT 1 FROM shell_stream_content_references r WHERE r.owner=shell_stream_contents.owner "
            "AND r.project_id=shell_stream_contents.project_id AND r.conversation_id=shell_stream_contents.conversation_id "
            "AND r.reference_id=shell_stream_contents.reference_id)", (self.owner, project_id))
        db.execute("DELETE FROM shell_stream_content_chunks WHERE owner=? AND project_id=? AND NOT EXISTS "
            "(SELECT 1 FROM shell_stream_content_pages p WHERE p.owner=shell_stream_content_chunks.owner "
            "AND p.project_id=shell_stream_content_chunks.project_id AND p.chunk_sha256=shell_stream_content_chunks.chunk_sha256)",
            (self.owner, project_id))

    def content(self, project_id, space_id, conversation_id, reference_id, *, offset=0, limit=CONTENT_CHUNK_CHARS, _db=None):
        project_id,space_id,conversation_id,reference_id = map(_identifier,(project_id,space_id,conversation_id,reference_id))
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= CONTENT_CHUNK_CHARS:
            raise ValueError("invalid stream content page; offsets and limits count Unicode characters")
        scope = (self.owner, project_id, conversation_id, reference_id)
        with (closing(self.store.connect("shell")) if _db is None else nullcontext(_db)) as db:
            if _db is None:
                db.execute("BEGIN")
            row = db.execute("SELECT * FROM shell_stream_contents WHERE owner=? AND project_id=? AND conversation_id=? "
                "AND reference_id=? AND space_id=?", (*scope, space_id)).fetchone()
            if row is None:
                raise FileNotFoundError("stream content reference expired or outside this scope")
            manifest=_decode(row["protected_manifest"])
            expected={"owner":self.owner,"project_id":project_id,"space_id":space_id,"conversation_id":conversation_id,
                "reference_id":reference_id,"operation_id":row["operation_id"],"sha256":row["sha256"],
                "total_chars":row["total_chars"],"total_utf8_bytes":row["total_utf8_bytes"]}
            if not isinstance(manifest,dict) or any(manifest.get(key)!=value for key,value in expected.items()):
                raise RuntimeError("protected stream manifest failed integrity")
            chunk_map=manifest.get("chunks")
            if (not isinstance(chunk_map,list) or len(chunk_map)!=(row["total_chars"]+CONTENT_CHUNK_CHARS-1)//CONTENT_CHUNK_CHARS
                    or any(not isinstance(entry,dict) or entry.get("chunk_offset")!=index*CONTENT_CHUNK_CHARS
                           for index,entry in enumerate(chunk_map))):
                raise RuntimeError("protected stream manifest has an invalid chunk map")
            if offset > row["total_chars"]:
                raise ValueError("stream content offset exceeds immutable reference")
            start = (offset // CONTENT_CHUNK_CHARS) * CONTENT_CHUNK_CHARS
            chunks = db.execute("SELECT p.chunk_offset,p.chunk_sha256,c.protected_content FROM shell_stream_content_pages p "
                "JOIN shell_stream_content_chunks c ON c.owner=p.owner AND c.project_id=p.project_id AND c.chunk_sha256=p.chunk_sha256 "
                "WHERE p.owner=? AND p.project_id=? AND p.conversation_id=? AND p.reference_id=? "
                "AND p.chunk_offset>=? AND p.chunk_offset<? ORDER BY p.chunk_offset", (*scope,start,offset+limit)).fetchall()
            decoded=[]
            for index,chunk in enumerate(chunks):
                text=_decode(chunk["protected_content"])
                if (chunk["chunk_offset"] != start+index*CONTENT_CHUNK_CHARS or not isinstance(text,str)
                        or chunk["chunk_sha256"] != chunk_map[start//CONTENT_CHUNK_CHARS+index].get("sha256")
                        or hashlib.sha256(text.encode("utf-8")).hexdigest() != chunk["chunk_sha256"]):
                    raise RuntimeError("protected stream content page failed integrity")
                decoded.append(text)
            text="".join(decoded)[offset-start:offset-start+limit]
            if len(text) != min(limit,row["total_chars"]-offset):
                raise RuntimeError("protected stream overflow is incomplete")
        return {"project_id":project_id,"space_id":space_id,"conversation_id":conversation_id,"reference_id":reference_id,
            "offset":offset,"content":text,"total_chars":row["total_chars"],"total_utf8_bytes":row["total_utf8_bytes"],
            "sha256":row["sha256"],"page_sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "page_max_chars":CONTENT_CHUNK_CHARS,"page_max_utf8_bytes":CONTENT_PAGE_UTF8_BYTES,
            "next_offset":offset+len(text) if offset+len(text)<row["total_chars"] else None,
            "persisted":True,"partial":True,"authoritative":False,"automatic_retry":False,"closes_trio":False}

    def head(self, project_id, conversation_id):
        with closing(self.store.connect("shell")) as db:
            row = db.execute("SELECT * FROM shell_stream_heads WHERE owner=? AND project_id=? AND conversation_id=?",
                (self.owner, _identifier(project_id), _identifier(conversation_id))).fetchone()
        if row is None:
            return None
        return {**_decode(row["protected_snapshot"]), "sequence": row["sequence"], "persisted": True, "epoch": self.epoch}

    def read(self, project_id, after=None, *, limit=128):
        project_id = _identifier(project_id)
        if after is not None and (type(after) is not int or not 0 <= after <= 2**63 - 1):
            raise ValueError("invalid stream cursor")
        limit = max(1, min(int(limit), 256))
        # The twenty readers of one window fan-out usually ask for the same
        # committed cursor. Coalesce those reads for at most 50 ms. No mutable
        # execution authority is cached; authority cutover is checked on every
        # hit, and each local commit invalidates the cache immediately. Another
        # process's observations are refreshed after this bounded cache period.
        if getattr(self.store, "backend", None) == "sqlite":
            self.store.assert_active()
            key = (project_id, after, limit)
            with self._read_cache_lock:
                now, epoch = time.monotonic(), self._read_cache_epoch
                cached = self._read_cache.get(key)
                if cached and cached[0] == epoch and now - cached[1] < .05:
                    return copy.deepcopy(cached[2])
                result = self._read_snapshot(project_id, after, limit)
                if epoch == self._read_cache_epoch:
                    size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
                    if size <= 256_000:
                        old = self._read_cache.pop(key, None)
                        if old:
                            self._read_cache_bytes -= old[3]
                        self._read_cache[key] = (epoch, time.monotonic(), copy.deepcopy(result), size)
                        self._read_cache_bytes += size
                        while self._read_cache_bytes > 2_000_000 or len(self._read_cache) > 64:
                            self._read_cache_bytes -= self._read_cache.popitem(last=False)[1][3]
                return result
        return self._read_snapshot(project_id, after, limit)

    def _read_snapshot(self, project_id, after, limit):
        # Readers use a database snapshot, never the publisher's condition lock.
        # Holding that lock through twenty reader connections serializes every
        # notification ahead of the next producer write and stalls ingestion.
        with closing(self.store.connect("shell")) as db:
            db.execute("BEGIN")
            bounds = db.execute("SELECT MIN(seq) AS first,MAX(seq) AS last FROM shell_stream_events WHERE owner=? AND project_id=?",
                (self.owner, project_id)).fetchone()
            last = bounds["last"] or 0
            if after is None or after > last or (bounds["first"] and after < bounds["first"] - 1):
                # Reset sends small descriptors. Content is fetched for the visible conversation,
                # keeping this one multiplexed frame bounded even with many large histories.
                heads = db.execute("SELECT conversation_id,space_id,sequence FROM shell_stream_heads WHERE owner=? AND project_id=? ORDER BY sequence DESC LIMIT 257",
                    (self.owner, project_id)).fetchall()
                return {"reset": True, "cursor": last, "epoch": self.epoch, "items": [dict(row) for row in heads[:256]],
                        "has_more": len(heads) > 256}
            rows = db.execute("SELECT seq,protected_event FROM shell_stream_events WHERE owner=? AND project_id=? AND seq>? ORDER BY seq LIMIT ?",
                (self.owner, project_id, after, limit)).fetchall()
        return {"reset": False, "cursor": rows[-1]["seq"] if rows else after, "epoch": self.epoch,
                "items": [{**_decode(row["protected_event"]), "sequence": row["seq"]} for row in rows]}

    def wait(self, seconds=1):
        with self.changed:
            if not self.closed.is_set():
                self.changed.wait(timeout=seconds)

    def close(self):
        self.closed.set()
        with self._read_cache_lock:
            self._read_cache.clear()
            self._read_cache_bytes = 0
        with self.changed:
            self.changed.notify_all()
