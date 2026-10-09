"""Borrow the enclosing central physical scope instead of reserving it twice.

Only the exact immutable Operation may borrow. The enclosing host remains the
single result committer and lock/lease owner; nested provider helpers cannot
release that ownership, acquire another identity, or acknowledge another effect.
"""
import asyncio
import inspect
import weakref

from sentra_runtime.contracts import OperationResult
from sentra_runtime.effect_boundary import current_effect_context
from .gate import DispatchOutcome,EffectRejected,_fingerprint


class _BorrowedContext:
    def __init__(self, context):self.context=context
    def checkpoint(self):self.context.checkpoint()
    async def run_async(self, callback, *args, **kwargs):
        self.checkpoint();value=callback(*args,**kwargs)
        value=await value if inspect.isawaitable(value) else value
        self.checkpoint();return value


class _HostJournal:
    def __init__(self, gate):self.gate=gate
    async def reserve(self, request):
        context=self.gate._context(request)
        if context is None:return await self.gate.central.journal.reserve(request)
        if context in self.gate._calls:raise EffectRejected("nested provider effect already admitted")
        context.checkpoint();self.gate._calls[context]=None;return None
    async def finish(self,request,result):
        context=self.gate._context(request)
        if context is None:return await self.gate.central.journal.finish(request,result)
        if context not in self.gate._calls or result.operation_id!=request.operation_id:
            raise EffectRejected("nested result outside its central admission")
        self.gate._calls[context]=result  # The outer host commits the result once.
    async def get(self,operation_id):return await self.gate.central.journal.get(operation_id)


class HostScopedInteropGate:
    def __init__(self, central):
        if not callable(getattr(central,"physical_context",None)):raise ValueError("central physical gate required")
        self.central=central;self.machine=central.machine;self.policy=central.policy
        self._calls=weakref.WeakKeyDictionary();self.journal=_HostJournal(self)
    def _context(self,request):
        context=current_effect_context.get()
        if context is not None and _fingerprint(context.request)!=_fingerprint(request):
            raise EffectRejected("nested provider attempted another operation intent")
        return context
    async def decision(self,request):return await self.central.decision(request)
    def physical_context(self,request):
        context=self._context(request)
        return _BorrowedContext(context) if context is not None else self.central.physical_context(request)
    async def execute(self,request,effect,*,timeout=None):
        context=self._context(request)
        if context is None:return await self.central.execute(request,effect,timeout=timeout)
        decision=await self.decision(request)
        if not decision.allowed:raise EffectRejected("nested provider grant rejected")
        await self.journal.reserve(request)
        context.checkpoint()
        value=effect()
        if inspect.isawaitable(value):value=await asyncio.wait_for(value,timeout) if timeout is not None else await value
        context.checkpoint()
        operation=value if isinstance(value,OperationResult) else OperationResult(request.operation_id,"SUCCEEDED")
        await self.journal.finish(request,operation)
        return DispatchOutcome(operation,value if not isinstance(value,OperationResult) else dict(value.evidence))
