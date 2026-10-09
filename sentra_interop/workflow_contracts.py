"""Subworkflow contracts derived from pinned LangGraph/Temporal semantics.

NOT a second Run/WorkItem/Operation scheduler. Only host-injected central
admission can invoke an activity; uncertain effects are never retryable.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def ident(value):
    if not isinstance(value,str) or not NAME.fullmatch(value): raise ValueError("invalid workflow identifier")
    return value


def canonical(value):
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":"))
    if len(raw.encode())>2_000_000: raise ValueError("workflow value exceeds bound")
    return raw


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    initial_seconds: float = 1
    maximum_seconds: float = 60
    coefficient: float = 2
    expiration_seconds: float = 3600
    retryable_types: tuple[str,...] = ("DEPENDENCY_UNAVAILABLE","RESOURCE_BUSY_BEFORE_START","RATE_LIMITED_BEFORE_START")

    def __post_init__(self):
        if (type(self.max_attempts) is not int or not 1<=self.max_attempts<=100 or
            any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in
                (self.initial_seconds,self.maximum_seconds,self.coefficient,self.expiration_seconds)) or
            self.coefficient<1 or self.initial_seconds>self.maximum_seconds):
            raise ValueError("invalid bounded workflow retry policy")

    def next_at(self,receipt,*,attempt,started,now):
        if (receipt.status!="FAILED" or receipt.effect_state!="NOT_STARTED" or not receipt.retryable
            or receipt.failure_type not in self.retryable_types or attempt>=self.max_attempts): return None
        delay=self.initial_seconds
        for _ in range(attempt-1): delay=min(self.maximum_seconds,delay*self.coefficient)
        scheduled=now+delay
        return scheduled if scheduled<=started+self.expiration_seconds else None


@dataclass(frozen=True)
class ActivityReceipt:
    status: str
    effect_state: str
    output: Any = None
    failure_type: str | None = None
    retryable: bool = False
    provider_reference: str | None = None
    artifacts: tuple[Mapping[str,Any],...] = ()

    def __post_init__(self):
        if self.status not in {"SUCCEEDED","FAILED","WAITING","UNCERTAIN","CANCELLED"} or self.effect_state not in {
            "NOT_STARTED","COMPLETED","UNKNOWN"}: raise ValueError("invalid activity receipt")
        if self.status=="SUCCEEDED" and self.effect_state!="COMPLETED": raise ValueError("success needs completion evidence")
        if type(self.retryable) is not bool: raise ValueError("retry classification must be boolean")
        if self.failure_type is not None and (not isinstance(self.failure_type,str) or not 1<=len(self.failure_type)<=256):
            raise ValueError("invalid activity failure type")
        if self.provider_reference is not None and (not isinstance(self.provider_reference,str) or not 1<=len(self.provider_reference)<=512):
            raise ValueError("invalid provider reference")
        if self.retryable and (self.status!="FAILED" or self.effect_state!="NOT_STARTED"):
            raise ValueError("only a confirmed never-started failure may retry")
        canonical(asdict(self))


@dataclass(frozen=True)
class ActivitySpec:
    step_id: str
    kind: str = "activity"
    handler_id: str | None = None
    handler_version: str | None = None
    dependencies: tuple[str,...] = ()
    inputs_json: str = "{}"
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    idle_timeout: float = 60
    total_timeout: float = 120
    signal_name: str | None = None
    wait_seconds: float | None = None
    subflow_id: str | None = None
    subflow_version: str | None = None

    def __post_init__(self):
        ident(self.step_id)
        for dependency in self.dependencies: ident(dependency)
        if self.kind not in {"activity","wait","subflow"}: raise ValueError("unknown workflow node type")
        if not isinstance(json.loads(self.inputs_json),dict): raise ValueError("workflow inputs must be a JSON mapping")
        canonical(json.loads(self.inputs_json))
        if self.kind=="activity":
            ident(self.handler_id); ident(self.handler_version)
        if self.kind=="wait" and self.signal_name is not None: ident(self.signal_name)
        if self.kind=="subflow": ident(self.subflow_id); ident(self.subflow_version)
        if any(type(t) not in (int,float) or not math.isfinite(t) or not 0<t<=86400 for t in (self.idle_timeout,self.total_timeout)):
            raise ValueError("invalid workflow timeout")
        if self.kind=="wait" and self.signal_name is None and self.wait_seconds is None:
            raise ValueError("wait requires a signal or a durable deadline")
        if self.wait_seconds is not None and (type(self.wait_seconds) not in (int,float) or not math.isfinite(self.wait_seconds) or not 0<=self.wait_seconds<=31536000):
            raise ValueError("invalid workflow wait deadline")


@dataclass(frozen=True)
class WorkflowDefinition:
    definition_id: str
    version: str
    worker_version: str
    steps: tuple[ActivitySpec,...]

    def __post_init__(self):
        ident(self.definition_id); ident(self.version); ident(self.worker_version)
        if not 1<=len(self.steps)<=1000 or len({s.step_id for s in self.steps})!=len(self.steps):
            raise ValueError("invalid workflow step catalog")
        graph={s.step_id:s.dependencies for s in self.steps}
        seen=set()
        active=set()
        def visit(key):
            if key in active: raise ValueError("workflow dependency cycle")
            if key in seen: return
            if key not in graph: raise ValueError("unknown workflow dependency")
            active.add(key)
            for parent in graph[key]: visit(parent)
            active.remove(key); seen.add(key)
        for key in graph: visit(key)

    @property
    def fingerprint(self): return digest(asdict(self))
