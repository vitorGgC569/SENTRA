"""ToolHive-inspired selective discovery over a host-provided authorized catalog.

Search never executes or grants a tool. Embeddings have no default provider.
Returned schema/version fingerprints must still be checked at invocation.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from sentra_runtime.contracts import OperationRequest, OperationResult, PolicyDecision
from .gate import DispatchOutcome, EffectRejected, InteropGate, _fingerprint


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


@dataclass(frozen=True)
class ToolDescriptor:
    tool_id: str
    capability_id: str
    name: str
    description: str
    version: str
    schema_json: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]):
        fields = ("tool_id", "capability_id", "name", "description", "version")
        if any(not isinstance(row.get(k), str) or not row[k] or len(row[k]) > (8192 if k == "description" else 256)
               for k in fields) or not isinstance(row.get("inputSchema"), Mapping):
            raise ValueError("invalid tool catalog descriptor")
        schema = _json(row["inputSchema"])
        if len(schema.encode()) > 65536:
            raise ValueError("tool schema exceeds bound")
        return cls(*(row[k] for k in fields), schema)

    @property
    def fingerprint(self):
        return hashlib.sha256(_json(self.public()).encode()).hexdigest()

    def public(self):
        return {"tool_id":self.tool_id,"capability_id":self.capability_id,"name":self.name,
                "description":self.description,"version":self.version,"inputSchema":json.loads(self.schema_json)}


class EmbeddingProvider(Protocol):
    identity: str  # Includes provider/model/revision; changing it invalidates vectors.
    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


def _words(text):
    return re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)


def _vector(raw):
    values = tuple(raw)
    if not values or len(values) > 16384 or any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
        raise ValueError("invalid explicit embedding result")
    norm = math.sqrt(sum(v*v for v in values))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("empty embedding direction")
    return tuple(v/norm for v in values)


class AuthorizedToolCatalog:
    def __init__(self, gate: InteropGate, *, authorize_tool=None, embedding: EmbeddingProvider | None = None):
        self.gate, self.authorize_tool, self.embedding = gate, authorize_tool, embedding
        self._tools: dict[str, ToolDescriptor] = {}
        self._vectors: dict[tuple[str,str], tuple[float,...]] = {}
        self._lock = asyncio.Lock()
        self._generation = 0

    def replace(self, descriptors: Sequence[ToolDescriptor]) -> None:
        if len(descriptors) > 10000 or any(not isinstance(d,ToolDescriptor) for d in descriptors):
            raise ValueError("invalid catalog snapshot")
        replacement = {d.tool_id:d for d in descriptors}
        if len(replacement) != len(descriptors):
            raise ValueError("duplicate tool identity")
        self._tools = replacement
        retained = {d.fingerprint for d in descriptors}
        self._vectors = {key:value for key,value in self._vectors.items() if key[1] in retained}
        self._generation += 1

    def require_current(self, tool_id: str, *, fingerprint: str) -> ToolDescriptor:
        tool = self._tools.get(tool_id)
        if tool is None or tool.fingerprint != fingerprint:
            raise EffectRejected("tool schema/version changed; rediscover before invoking")
        return tool  # This is freshness, never execution authorization.

    async def _authorized(self, tool, request):
        if not callable(self.authorize_tool):
            return False
        decision = self.authorize_tool(tool, request)
        if inspect.isawaitable(decision):
            decision = await decision
        # Trusted host PDP must evaluate its resource-specific constraints.
        # An unhandled constraint cannot silently broaden catalog visibility.
        return isinstance(decision,PolicyDecision) and decision.allowed is True and not decision.constraints

    async def host_handler(self, request):
        args=request.arguments
        outcome=await self.discover(request,query=args.get("query"),limit=args.get("limit",8),
            semantic=args.get("semantic",False),semantic_weight=args.get("semantic_weight",.35))
        return outcome.payload if outcome.operation.state=="SUCCEEDED" else outcome.operation

    async def discover(self, request: OperationRequest, *, query: str, limit: int = 8,
                       semantic: bool = False, semantic_weight: float = .35) -> DispatchOutcome:
        async def effect():
            if (request.capability_id != "tools:discover" or request.arguments != {
                "query":query,"limit":limit,"semantic":semantic,"semantic_weight":semantic_weight}
                or not isinstance(query,str) or not query.strip() or len(query) > 4096
                or type(limit) is not int or not 1 <= limit <= 50 or type(semantic) is not bool
                or type(semantic_weight) not in (int,float) or not 0 <= semantic_weight <= 1):
                raise EffectRejected("tool discovery intent mismatch")
            if not callable(self.authorize_tool):
                raise EffectRejected("authorized catalog PDP unavailable")
            async with self._lock:
                generation = self._generation
                snapshot = tuple(self._tools.values())
                tools = [d for d in snapshot if await self._authorized(d,request)]
                query_terms = Counter(_words(query))
                docs = {d.tool_id:Counter(_words(d.name+" "+d.description)) for d in tools}
                counts = Counter(word for terms in docs.values() for word in terms)
                lexical = {}
                for tool in tools:
                    terms = docs[tool.tool_id]
                    score = sum(math.log(1+(len(tools)+1)/(counts[word]+1)) * min(3,terms[word])
                                for word in query_terms if word in terms)
                    if query.casefold() in tool.name.casefold(): score += 3
                    lexical[tool.tool_id] = score
                semantic_scores = {}
                if semantic:
                    if self.embedding is None or not isinstance(self.embedding.identity,str) or not self.embedding.identity:
                        raise EffectRejected("explicit embedding provider unavailable")
                    provider_id = self.embedding.identity
                    missing = [d for d in tools if (provider_id,d.fingerprint) not in self._vectors]
                    # Unauthorized descriptions never reach the embedding provider.
                    if missing:
                        result = await self.embedding.embed([d.name+"\n"+d.description for d in missing])
                        if len(result) != len(missing): raise ValueError("embedding result count mismatch")
                        for d,v in zip(missing,result): self._vectors[(provider_id,d.fingerprint)] = _vector(v)
                    q = _vector((await self.embedding.embed([query]))[0])
                    for d in tools:
                        v = self._vectors[(provider_id,d.fingerprint)]
                        if len(v) != len(q): raise ValueError("embedding dimension changed")
                        semantic_scores[d.tool_id] = max(0.,sum(a*b for a,b in zip(q,v)))
                maximum = max(lexical.values(),default=0.) or 1.
                ranked = sorted(tools,key=lambda d:(-((1-semantic_weight if semantic else 1)*lexical[d.tool_id]/maximum
                    + semantic_weight*semantic_scores.get(d.tool_id,0)), d.tool_id))
                selected = [d for d in ranked if lexical[d.tool_id] > 0 or semantic_scores.get(d.tool_id,0) > 0][:limit]
                if generation != self._generation:
                    raise EffectRejected("catalog changed during discovery")
                # Re-evaluate visibility after slow embedding I/O. Search is
                # not a grant cache, and revoked tools cannot leak in results.
                visible = [d for d in tools if await self._authorized(d,request)]
                if generation != self._generation:
                    raise EffectRejected("catalog changed during authorization refresh")
                selected = [d for d in selected if d in visible]
                returned_tools=[{**d.public(),"fingerprint":d.fingerprint,
                    "lexical_score":lexical[d.tool_id],"semantic_score":semantic_scores.get(d.tool_id)} for d in selected]
                baseline = (len(_json([d.public() for d in visible]).encode())+3)//4
                returned = (len(_json(returned_tools).encode())+3)//4
                return {"tools":returned_tools,
                    "catalog_generation":generation,"authorized_count":len(visible),
                    "token_metrics":{"baseline_tokens":baseline,"returned_tokens":returned,
                        "savings_percent":max(0.,100*(baseline-returned)/baseline) if baseline else 0.,
                        "estimate_method":"utf8-bytes/4; not provider billing"},
                    "execution_authorization_required":True}
        from sentra_runtime.effect_boundary import current_effect_context
        context=current_effect_context.get()
        if context is None:
            return await self.gate.execute(request,effect,timeout=60)
        if _fingerprint(context.request)!=_fingerprint(request):
            raise EffectRejected("tool discovery nested physical intent mismatch")
        context.checkpoint()
        return DispatchOutcome(OperationResult(request.operation_id,"SUCCEEDED"),await effect())
