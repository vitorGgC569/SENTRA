"""LangGraph checkpoints/pending writes in the existing configured store."""
import base64
from contextlib import contextmanager
from sentra_core.conversations import _encode, _decode


def configured_checkpointer(control, owner):
    # Optional dependency stays lazy; absence is explicit during configuration.
    from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP

    class ConfiguredSaver(BaseCheckpointSaver):
        def __init__(self):
            super().__init__()
            with self.db() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS wf_sdk_checkpoints(
                    owner TEXT NOT NULL,thread_id TEXT NOT NULL,ns TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,parent_id TEXT,content TEXT NOT NULL,
                    metadata TEXT NOT NULL,PRIMARY KEY(owner,thread_id,ns,checkpoint_id))""")
                db.execute("""CREATE TABLE IF NOT EXISTS wf_sdk_writes(
                    owner TEXT NOT NULL,thread_id TEXT NOT NULL,ns TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,task_id TEXT NOT NULL,idx INTEGER NOT NULL,
                    task_path TEXT NOT NULL,channel TEXT NOT NULL,content TEXT NOT NULL,
                    PRIMARY KEY(owner,thread_id,ns,checkpoint_id,task_id,idx))""")

        @contextmanager
        def db(self):
            connection = control.store.connect("execution_workspace")
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

        def pack(self, value):
            kind, data = self.serde.dumps_typed(value)
            return _encode({"type": kind, "bytes": base64.b64encode(data).decode("ascii")})

        def unpack(self, value):
            encoded = _decode(value)
            return self.serde.loads_typed((encoded["type"], base64.b64decode(encoded["bytes"], validate=True)))

        def scope(self, config):
            from sentra_runtime.effect_boundary import current_effect_context
            from .workflow_runtime import RuntimeScope, _scope_key
            from .workflow_contracts import digest
            context = current_effect_context.get()
            if context is None or context.receipt.owner != owner or not context.request.capability_id.startswith("runtime:langgraph:"):
                raise PermissionError("checkpoint outside admitted LangGraph operation")
            context.checkpoint()
            request, receipt = context.request, context.receipt
            runtime_scope = RuntimeScope(owner, receipt.run_id, request.work_item_id, request.principal_id)
            permitted = {"sentra-" + digest([_scope_key(runtime_scope), request.arguments["workflow_id"], occurrence])
                for occurrence in (request.arguments.get("occurrence"), request.arguments.get("new_occurrence"))
                if occurrence is not None}
            values = config["configurable"]
            thread = values["thread_id"]
            if thread not in permitted:
                raise PermissionError("scoped runtime thread required")
            return owner, thread, values.get("checkpoint_ns", "")

        def cfg(self, thread, ns, checkpoint):
            return {"configurable": {"thread_id": thread, "checkpoint_ns": ns,
                                     "checkpoint_id": checkpoint}}

        def get_tuple(self, config):
            scope = self.scope(config)
            checkpoint = config["configurable"].get("checkpoint_id")
            with self.db() as db:
                row = db.execute("SELECT * FROM wf_sdk_checkpoints WHERE owner=? AND thread_id=? "
                    "AND ns=?" + (" AND checkpoint_id=?" if checkpoint else "") +
                    " ORDER BY checkpoint_id DESC LIMIT 1", (*scope, checkpoint) if checkpoint else scope).fetchone()
                if row is None:
                    return None
                writes = db.execute("SELECT * FROM wf_sdk_writes WHERE owner=? AND thread_id=? AND ns=? "
                    "AND checkpoint_id=? ORDER BY task_path,task_id,idx", (*scope, row["checkpoint_id"])).fetchall()
            return CheckpointTuple(self.cfg(scope[1], scope[2], row["checkpoint_id"]),
                self.unpack(row["content"]), self.unpack(row["metadata"]),
                self.cfg(scope[1], scope[2], row["parent_id"]) if row["parent_id"] else None,
                [(entry["task_id"], entry["channel"], self.unpack(entry["content"])) for entry in writes])

        def put(self, config, checkpoint, metadata, new_versions):
            scope = self.scope(config)
            content, meta = self.pack(checkpoint), self.pack(metadata)
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT content,metadata FROM wf_sdk_checkpoints WHERE owner=? AND "
                    "thread_id=? AND ns=? AND checkpoint_id=?", (*scope, checkpoint["id"])).fetchone()
                if old and (self.unpack(old["content"]) != checkpoint or self.unpack(old["metadata"]) != metadata):
                    raise ValueError("immutable checkpoint conflict")
                db.execute("INSERT OR IGNORE INTO wf_sdk_checkpoints VALUES(?,?,?,?,?,?,?)",
                    (*scope, checkpoint["id"], config["configurable"].get("checkpoint_id"), content, meta))
            return self.cfg(scope[1], scope[2], checkpoint["id"])

        def put_writes(self, config, writes, task_id, task_path=""):
            scope = self.scope(config)
            checkpoint = config["configurable"]["checkpoint_id"]
            with self.db() as db:
                for index, (channel, value) in enumerate(writes):
                    idx = WRITES_IDX_MAP.get(channel, index)
                    sql = "INSERT INTO wf_sdk_writes VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT "
                    sql += "(owner,thread_id,ns,checkpoint_id,task_id,idx) DO "
                    sql += "UPDATE SET content=excluded.content,channel=excluded.channel" if channel in WRITES_IDX_MAP else "NOTHING"
                    db.execute(sql, (*scope, checkpoint, task_id, idx, task_path, channel, self.pack(value)))

        def list(self, config, *, filter=None, before=None, limit=None):
            if config is None:
                raise PermissionError("unscoped checkpoint scans unavailable")
            scope = self.scope(config)
            with self.db() as db:
                rows = db.execute("SELECT checkpoint_id,metadata FROM wf_sdk_checkpoints WHERE owner=? AND "
                    "thread_id=? AND ns=? ORDER BY checkpoint_id DESC", scope).fetchall()
            emitted = 0
            for row in rows:
                if before and row["checkpoint_id"] >= before["configurable"]["checkpoint_id"]:
                    continue
                meta = self.unpack(row["metadata"])
                if filter and any(meta.get(key) != value for key, value in filter.items()):
                    continue
                if limit is not None and emitted >= limit:
                    break
                yield self.get_tuple(self.cfg(scope[1], scope[2], row["checkpoint_id"]))
                emitted += 1

        async def aget_tuple(self, config):
            return self.get_tuple(config)

        async def aput(self, config, checkpoint, metadata, new_versions):
            return self.put(config, checkpoint, metadata, new_versions)

        async def aput_writes(self, config, writes, task_id, task_path=""):
            self.put_writes(config, writes, task_id, task_path)

        async def alist(self, config, *, filter=None, before=None, limit=None):
            for entry in self.list(config, filter=filter, before=before, limit=limit):
                yield entry

        async def afork_checkpoint(self, source_config, target_config):
            # Copy the complete parent chain and writes, preserving delta channels.
            source = await self.aget_tuple(source_config)
            if source is None:
                raise FileNotFoundError("source checkpoint missing")
            chain = []
            cursor = source
            while cursor is not None:
                chain.append(cursor)
                cursor = await self.aget_tuple(cursor.parent_config) if cursor.parent_config else None
            target = dict(target_config)
            target["configurable"] = dict(target_config["configurable"])
            for entry in reversed(chain):
                target = await self.aput(target, entry.checkpoint, entry.metadata,
                                         entry.checkpoint.get("channel_versions", {}))
                source_scope = self.scope(entry.config)
                target_scope = self.scope(target)
                with self.db() as db:
                    writes = db.execute("SELECT * FROM wf_sdk_writes WHERE owner=? AND thread_id=? AND ns=? AND checkpoint_id=? ORDER BY task_path,task_id,idx",
                        (*source_scope, entry.checkpoint["id"])).fetchall()
                    for write in writes:
                        db.execute("INSERT OR IGNORE INTO wf_sdk_writes VALUES(?,?,?,?,?,?,?,?,?)",
                            (*target_scope, entry.checkpoint["id"], write["task_id"], write["idx"], write["task_path"], write["channel"], write["content"]))
            return target

    return ConfiguredSaver()
