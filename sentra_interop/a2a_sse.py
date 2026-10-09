"""Authenticated read-only A2A-style SSE on IPv4 loopback, SQLite fixture.

No commands/agent execution over HTTP. Persistent task events are admitted
through the SENTRA InteropGate; readers are scoped by Bearer, principal,
work_item, task and live PolicyDecision on every emission and heartbeat.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from sentra_runtime.contracts import OperationRequest, OperationResult
from .gate import DispatchOutcome, InteropGate
from .requests import _bounded, InteropMappingDenied

TASK_ID = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")
MAX_REPLAY = 8
MAX_EVENT = 4096
MAX_HEADERS = 20
MAX_STREAM_SECONDS = 2
HEARTBEAT_SECONDS = .07
DRAIN_TIMEOUT = .25
TERMINAL = frozenset({"completed","canceled","failed"})


class A2ASSEDenied(ValueError):
    pass


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, separators=(",",":"),sort_keys=True,
                      allow_nan=False,ensure_ascii=False)


class A2ASSELedger:
    def __init__(self, gate: InteropGate, *, workspace_root: str,
                 database: str, task_id: str, work_item_id: str,
                 principal_id: str) -> None:
        root=Path(workspace_root).resolve()
        dest=Path(database).resolve()
        if (not root.is_dir() or not dest.is_relative_to(root) or dest==root
            or not TASK_ID.fullmatch(task_id) or not principal_id or not work_item_id):
            raise A2ASSEDenied("untrusted SSE ledger scope")
        self.gate,self.db_file = gate,dest
        self.task_id,self.work_item_id,self.principal_id=task_id,work_item_id,principal_id
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS sse_streams(
                task_id TEXT PRIMARY KEY, work_item_id TEXT NOT NULL,
                principal_id TEXT NOT NULL, state TEXT NOT NULL, sequence INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS sse_events(
                task_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                operation_id TEXT UNIQUE NOT NULL, idem_key TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(task_id,sequence))""")
            existing=db.execute("SELECT work_item_id,principal_id FROM sse_streams "
                                "WHERE task_id=?", (task_id,)).fetchone()
            if existing and existing != (work_item_id,principal_id):
                raise A2ASSEDenied("task scope changed across restart")
            if not existing:
                db.execute("INSERT INTO sse_streams VALUES(?,?,?,?,?)",
                           (task_id,work_item_id,principal_id,"new",0))

    @contextmanager
    def _db(self):
        db=sqlite3.connect(str(self.db_file),timeout=10)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def state(self) -> str:
        with self._db() as db:
            return db.execute("SELECT state FROM sse_streams WHERE task_id=?",
                              (self.task_id,)).fetchone()[0]

    def latest(self) -> int:
        with self._db() as db:
            return db.execute("SELECT sequence FROM sse_streams WHERE task_id=?",
                              (self.task_id,)).fetchone()[0]

    def since(self, last: int) -> list[dict[str, Any]]:
        if type(last) is not int or last<0:
            raise A2ASSEDenied("invalid Last-Event-ID")
        with self._db() as db:
            newest=db.execute("SELECT sequence FROM sse_streams WHERE task_id=?",
                              (self.task_id,)).fetchone()[0]
            if last>newest:
                raise A2ASSEDenied("Last-Event-ID is ahead of task stream")
            if newest-last>MAX_REPLAY:
                raise A2ASSEDenied("bounded replay window exceeded")
            rows=db.execute("SELECT sequence,payload FROM sse_events "
                            "WHERE task_id=? AND sequence>? ORDER BY sequence ASC",
                            (self.task_id,last)).fetchall()
        return [{"sequence":seq, **json.loads(payload)} for seq,payload in rows]

    async def append(self, request: OperationRequest, *, state: str, text: str
                     ) -> DispatchOutcome:
        if (request.capability_id!="a2a:sse_publish"
            or request.principal_id != self.principal_id
            or request.work_item_id != self.work_item_id
            or request.machine_id != self.gate.machine.machine_id
            or state not in {"submitted","working","completed","canceled","failed"}
            or not isinstance(text,str) or len(text.encode("utf-8"))>1000
            or request.arguments != {"task_id":self.task_id,"state":state,"text":text}):
            return DispatchOutcome(OperationResult(request.operation_id,"FAILED",
                                                   error="untrusted SSE publisher"))
        # secret-like payload fields are disallowed; no raw tools or commands.
        try:
            _bounded(request.arguments)
        except InteropMappingDenied:
            return DispatchOutcome(OperationResult(request.operation_id,"FAILED",
                                                   error="unsafe SSE content"))

        async def write() -> dict[str, Any]:
            if not (await self.gate.decision(request)).allowed:
                raise A2ASSEDenied("SSE publisher grant revoked")
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                old=db.execute("SELECT state,sequence FROM sse_streams WHERE task_id=?",
                               (self.task_id,)).fetchone()
                if old[0] in TERMINAL or (
                    old[0]=="new" and state!="submitted") or (
                    old[0]!="new" and state=="submitted"):
                    raise A2ASSEDenied("invalid task state transition")
                seq=old[1]+1
                payload=_json({"state":state,"text":text})
                if len(payload.encode("utf-8"))>MAX_EVENT:
                    raise A2ASSEDenied("SSE data oversized")
                db.execute("INSERT INTO sse_events VALUES(?,?,?,?,?)",
                           (self.task_id,seq,request.operation_id,request.idempotency_key,payload))
                db.execute("UPDATE sse_streams SET state=?,sequence=? WHERE task_id=?",
                           (state,seq,self.task_id))
            return {"sequence":seq,"state":state}
        # If the write commits but a grant expires before reply, UNCERTAIN
        # cannot be repeated. Persistent primary keys prevent restart replay.
        return await self.gate.execute(request,write)


class A2ASSEServer:
    def __init__(self, ledger: A2ASSELedger, *, token: str) -> None:
        if not isinstance(token,str) or len(token)<32:
            raise A2ASSEDenied("trusted fixture token required")
        self.ledger,self._token=ledger,token
        self.port: int | None = None
        self._server: asyncio.AbstractServer | None = None
        self._clients: set[asyncio.StreamWriter] = set()

    async def start(self) -> "A2ASSEServer":
        if self._server:
            raise A2ASSEDenied("server already started")
        self._server=await asyncio.start_server(self._handle,host="127.0.0.1",port=0)
        self.port=self._server.sockets[0].getsockname()[1]
        return self

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server=None
        for w in tuple(self._clients):
            w.close()
        if self._clients:
            await asyncio.gather(*(w.wait_closed() for w in tuple(self._clients)),
                                 return_exceptions=True)

    def _read_request(self) -> OperationRequest:
        return OperationRequest("sse-read-"+self.ledger.task_id,
                                self.ledger.principal_id,self.ledger.gate.machine.machine_id,
                                "a2a:sse_read",self.ledger.work_item_id,
                                "sse-read-key-"+self.ledger.task_id,
                                {"task_id":self.ledger.task_id})

    async def _drain(self, writer: asyncio.StreamWriter, payload: bytes) -> None:
        if writer.transport.get_write_buffer_size()>MAX_EVENT*MAX_REPLAY:
            raise A2ASSEDenied("SSE slow consumer overflow")
        writer.write(payload)
        await asyncio.wait_for(writer.drain(),DRAIN_TIMEOUT)

    async def _handle(self,reader: asyncio.StreamReader,writer: asyncio.StreamWriter)->None:
        self._clients.add(writer)
        try:
            code=400
            req=None
            last=0
            try:
                peer=writer.get_extra_info("peername")
                if not peer or peer[0]!="127.0.0.1":
                    raise PermissionError()
                first=await asyncio.wait_for(reader.readline(),2)
                bits=first.decode("ascii").rstrip("\r\n").split(" ")
                if len(bits)!=3 or bits[0]!="GET" or bits[2]!="HTTP/1.1":
                    raise ValueError("SSE GET only")
                if bits[1]!=f"/v1/tasks/{self.ledger.task_id}/events":
                    raise ValueError("invalid task endpoint")
                headers={}
                for _ in range(MAX_HEADERS):
                    line=await asyncio.wait_for(reader.readline(),2)
                    if line==b"\r\n":
                        break
                    if not line or len(line)>2048:
                        raise ValueError("oversized header")
                    k,sep,v=line.decode("ascii").partition(":")
                    if not sep or k.lower() in headers:
                        raise ValueError("duplicate header")
                    headers[k.lower()]=v.strip()
                else:
                    raise ValueError("too many headers")
                if not hmac.compare_digest(headers.get("authorization","").encode(),
                                           ("Bearer "+self._token).encode()):
                    raise PermissionError()
                if (headers.get("x-principal")!=self.ledger.principal_id
                    or headers.get("x-work-item")!=self.ledger.work_item_id):
                    code=403
                    raise A2ASSEDenied("SSE principal/workspace denied")
                value=headers.get("last-event-id","0")
                if not value.isascii() or not value.isdecimal() or len(value)>12:
                    raise ValueError("invalid Last-Event-ID")
                last=int(value)
                self.ledger.since(last) # check bounded replay BEFORE sending 200
                req=self._read_request()
                if not (await self.ledger.gate.decision(req)).allowed:
                    code=403
                    raise A2ASSEDenied("SSE read grant denied")
                code=200
            except PermissionError:
                code=401
            except A2ASSEDenied:
                if code !=403:
                    code=409
            except (ValueError,UnicodeError,asyncio.TimeoutError):
                code=400
            if code!=200 or req is None:
                response={401:b"Unauthorized",403:b"Forbidden",
                          400:b"Bad Request",409:b"Conflict"}[code]
                await self._drain(writer,b"HTTP/1.1 "+str(code).encode()+b" "+response+
                                  b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            await self._drain(writer,b"HTTP/1.1 200 OK\r\n"
                              b"Content-Type: text/event-stream\r\nCache-Control: no-store\r\n"
                              b"Connection: close\r\nX-Accel-Buffering: no\r\n\r\n")
            loop=asyncio.get_running_loop()
            deadline=loop.time()+MAX_STREAM_SECONDS
            while loop.time()<deadline and not writer.is_closing():
                if not (await self.ledger.gate.decision(req)).allowed:
                    break # no event or heartbeat after grant revocation
                try:
                    updates=self.ledger.since(last)
                except A2ASSEDenied:
                    break # fell outside replay/backpressure bounded window
                if updates:
                    for event in updates:
                        if not (await self.ledger.gate.decision(req)).allowed:
                            return
                        sequence=event.pop("sequence")
                        packet=("id: "+str(sequence)+"\nevent: task-status\ndata: "+
                                _json(event)+"\n\n").encode("utf-8")
                        if len(packet)>MAX_EVENT:
                            raise A2ASSEDenied("SSE event oversized")
                        await self._drain(writer,packet)
                        last=sequence
                        if event["state"] in TERMINAL:
                            return # terminal task closes SSE stream
                else:
                    await self._drain(writer,b": heartbeat\n\n")
                await asyncio.sleep(HEARTBEAT_SECONDS)
        except (ConnectionError,OSError,asyncio.TimeoutError,A2ASSEDenied):
            pass
        finally:
            self._clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError,OSError):
                pass


class A2ASSEClient:
    """Real local HTTP SSE client with bounded strict frame parsing."""

    def __init__(self,*,port:int,token:str,principal_id:str,work_item_id:str,
                 task_id:str):
        if (type(port) is not int or not 0<port<65536 or
            not token or not principal_id or not work_item_id or not TASK_ID.fullmatch(task_id)):
            raise ValueError("invalid local SSE identity")
        self.port,self.token,self.principal,self.work,self.task=(port,token,principal_id,
                                                                  work_item_id,task_id)

    async def connect(self,*,last_event_id:int=0):
        if type(last_event_id) is not int or last_event_id<0:
            raise ValueError("invalid cursor")
        reader,writer=await asyncio.open_connection("127.0.0.1",self.port)
        request=(f"GET /v1/tasks/{self.task}/events HTTP/1.1\r\n"
                 f"Host: 127.0.0.1\r\nAuthorization: Bearer {self.token}\r\n"
                 f"X-Principal: {self.principal}\r\nX-Work-Item: {self.work}\r\n"
                 f"Last-Event-ID: {last_event_id}\r\nConnection: close\r\n\r\n").encode()
        writer.write(request)
        await writer.drain()
        headline=await asyncio.wait_for(reader.readline(),2)
        bits=headline.decode("ascii").split(" ")
        code=int(bits[1])
        for _ in range(MAX_HEADERS):
            line=await asyncio.wait_for(reader.readline(),2)
            if line==b"\r\n":break
            if not line or len(line)>2048:
                raise ValueError("malformed SSE headers")
        return code,reader,writer

    @staticmethod
    async def next_event(reader:asyncio.StreamReader,*,timeout:float=2
                         )->Mapping[str,Any]|None:
        values={}
        while True:
            line=await asyncio.wait_for(reader.readline(),timeout)
            if not line:
                return None
            if len(line)>MAX_EVENT:
                raise ValueError("SSE frame too large")
            if line==b"\n" or line==b"\r\n":
                if values.get("heartbeat"):
                    return {"heartbeat":True}
                if {"id","event","data"}<=set(values):
                    if values["event"]!="task-status":
                        raise ValueError("unexpected SSE event type")
                    msg=json.loads(values["data"])
                    return {"id":int(values["id"]),**msg}
                values={}
                continue
            decoded=line.decode("utf-8").rstrip("\r\n")
            if decoded.startswith(":"):
                values["heartbeat"]=True
            elif ": " in decoded:
                key,value=decoded.split(": ",1)
                if key in values:
                    raise ValueError("duplicate SSE line")
                values[key]=value
