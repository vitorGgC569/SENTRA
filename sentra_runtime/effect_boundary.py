"""Physical I/O admission for one central SENTRA machine.

An OS byte/flock lock excludes other dispatcher processes sharing this central
state directory. The current durable fence is checked only AFTER acquiring the
lock, and immediately before I/O. Blocking workers keep the lock and lease even
if their awaiting coroutine times out. Remote services still require their own
idempotency/status contracts; this module does not assert control of other hosts.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import hashlib
import inspect
import os
from pathlib import Path
import threading
import time
import uuid
import json
from typing import Any, Callable

from .central_authority import CentralDurableIntentAuthority
from .contracts import OperationRequest, PolicyDecision
from .durable_admission import IntentReceipt, DurableAdmissionUnavailable
from .executor import AuthorizationRequired, _request_snapshot


current_effect_context: ContextVar["CentralEffectContext | None"] = ContextVar(
    "sentra_physical_effect_context", default=None)


class ResourceEffectBusy(DurableAdmissionUnavailable):
    pass


class _ResourceLock:
    def __init__(self, root: Path, machine_id: str):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / (hashlib.sha256(machine_id.encode()).hexdigest() + ".lock")
        self.stream = None

    def acquire(self, timeout: float) -> None:
        if self.stream is not None:
            raise RuntimeError("physical lock already acquired")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        stream = os.fdopen(fd, "r+b", buffering=0)
        if os.fstat(fd).st_size == 0:
            stream.write(b"\0")
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.stream = stream
                return
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    stream.close()
                    raise ResourceEffectBusy("machine physical I/O is still owned")
                time.sleep(min(0.025, max(0.001, deadline - time.monotonic())))

    def release(self) -> None:
        stream, self.stream = self.stream, None
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


class CentralEffectContext:
    """Trusted host context; never constructed from untrusted operation arguments."""

    def __init__(self, authority: CentralDurableIntentAuthority, receipt: IntentReceipt,
                 request: OperationRequest, authorize: Callable, *, lock_timeout: float = 5.0):
        if not isinstance(authority, CentralDurableIntentAuthority):
            raise TypeError("real central physical effect authority required")
        if not callable(authorize) or not 0 <= lock_timeout <= 60:
            raise ValueError("bounded effect configuration required")
        intent, digest = _request_snapshot(request)
        if digest != receipt.intent_sha256 or intent.operation_id != receipt.operation_id:
            raise ValueError("physical context intent mismatch")
        self.authority, self.receipt, self.request = authority, receipt, intent
        self.authorize, self.lock_timeout = authorize, lock_timeout
        self._serial = threading.Lock()
        self._lost = threading.Event()
        self._owned_async=set()
        self._borrowed_guard=threading.Lock()
        self._borrowed_count=0
        self._deferred_end=None
        self._owned_blocking=set()
        self._had_blocking=False

    def checkpoint(self) -> None:
        """Revalidate before each additional physical action in a compound provider."""
        if self._lost.is_set():
            raise DurableAdmissionUnavailable("effect lease ownership lost")
        candidate, digest = _request_snapshot(self.request)
        if digest != self.receipt.intent_sha256:
            raise AuthorizationRequired("physical operation intent changed after reservation")
        decision = self.authorize(candidate)
        if inspect.isawaitable(decision):
            if inspect.iscoroutine(decision):
                decision.close()
            raise TypeError("physical worker requires synchronous central policy")
        if (not isinstance(decision, PolicyDecision) or decision.allowed is not True
                or decision.constraints or _request_snapshot(candidate)[1] != digest):
            raise AuthorizationRequired("physical effect grant revoked or invalid")
        if not self.authority.fence_active(self.receipt):
            raise DurableAdmissionUnavailable("physical effect fence is not current")

    def _keepalive(self, stop: threading.Event) -> None:
        interval = max(0.1, min(10.0, self.authority.ttl_s / 3))
        while not stop.wait(interval):
            try:
                if not self.authority.renew(self.receipt):
                    self._lost.set()
                    return
            except Exception:
                self._lost.set()
                return

    def capture_output(self, path, *, expected_sha256: str, max_bytes: int = 128 * 1024 * 1024) -> dict:
        """Snapshot an explicitly requested output in the existing Artifact store.

        Providers call this while holding their publication lock. No arbitrary
        provider-supplied path is imported: it must equal this request's output.
        The workspace copy remains user-editable; the stored bytes are verified
        independently when recovered through the authorized Artifact API.
        """
        self.checkpoint()
        source = Path(path).resolve(strict=True)
        requested = self.request.arguments.get("output")
        if (not isinstance(requested, str) or Path(requested).resolve() != source
                or not source.is_file() or type(max_bytes) is not int
                or not 1 <= max_bytes <= 512 * 1024 * 1024
                or source.stat().st_size > max_bytes):
            raise ValueError("artifact is not a bounded explicitly requested output")
        identity = hashlib.sha256(json.dumps(
            [self.receipt.owner, self.receipt.run_id, self.receipt.operation_id, expected_sha256],
            separators=(",", ":")).encode()).hexdigest()
        directory = self.authority.durable.artifact_root / "machine-outputs"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = directory / (identity + source.suffix.lower())
        temporary = directory / (identity + "." + uuid.uuid4().hex + ".tmp")
        digest = hashlib.sha256()
        total = 0
        try:
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as outgoing, source.open("rb") as incoming:
                for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("output grew beyond bounded capture")
                    digest.update(chunk)
                    outgoing.write(chunk)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if digest.hexdigest() != expected_sha256:
                raise ValueError("output changed before durable artifact capture")
            self.checkpoint()
            os.replace(temporary, destination)
            return self.authority.durable.register_artifact(
                self.receipt.run_id, self.receipt.owner, destination,
                operation_id=self.receipt.operation_id,
                artifact_id="machine-output-" + identity[:48],
                expected_sha256=expected_sha256,
                metadata={"kind": "machine-output", "source_path": str(source),
                          "machine_id": self.request.machine_id,
                          "work_item_id": self.request.work_item_id,
                          "intent_sha256": self.receipt.intent_sha256},
            )
        finally:
            temporary.unlink(missing_ok=True)

    def _begin(self):
        lock = _ResourceLock(self.authority.durable.root / "effect-locks",
                             self.request.machine_id)
        lock.acquire(self.lock_timeout)
        try:
            self.checkpoint()
            self.authority.begin_effect(self.receipt)
        except BaseException:
            lock.release()
            raise
        stop = threading.Event()
        worker = threading.Thread(target=self._keepalive, args=(stop,),
                                  name="sentra-effect-lease", daemon=True)
        worker.start()
        return lock, stop, worker

    @staticmethod
    def _end(lock, stop, worker):
        stop.set()
        worker.join(timeout=1)
        lock.release()

    def run_sync(self, effect: Callable[..., Any], *args, **kwargs) -> Any:
        """Run blocking provider I/O; timeout of its waiter cannot unlock the worker."""
        with self._serial:
            lock, stop, worker = self._begin()
            token = current_effect_context.set(self)
            try:
                value=effect(*args, **kwargs)
                self._late_return(value=value)
                return value
            except BaseException as exc:
                self._late_return(error_type=type(exc).__name__)
                raise
            finally:
                current_effect_context.reset(token)
                self._end(lock, stop, worker)

    def _late_return(self,*,value=None,error_type=None):
        try:self.authority.record_late_return(self.receipt,value=value,error_type=error_type)
        except Exception:pass  # Missing diagnostic persistence never changes an effect result.

    def _end_owned(self,lock,stop,worker):
        with self._borrowed_guard:
            if self._borrowed_count:
                self._deferred_end=(lock,stop,worker)
                return
        self._end(lock,stop,worker)

    async def run_blocking(self,effect: Callable[..., Any],*args,**kwargs):
        """One blocking provider helper inside this already owned async scope.

        The physical invocation owns the exclusion already. It must not acquire
        the same OS lock again, and cancellation of an activity timeout must not
        release that exclusion while its actual blocking I/O is still running.
        """
        if current_effect_context.get() is not self:
            raise AuthorizationRequired("blocking helper outside its central physical scope")
        self.checkpoint()
        with self._borrowed_guard:
            self._borrowed_count+=1;self._had_blocking=True
        def invocation():
            token=current_effect_context.set(self)
            try:
                self.checkpoint()
                value=effect(*args,**kwargs);self._late_return(value=value);return value
            except BaseException as exc:
                self._late_return(error_type=type(exc).__name__);raise
            finally:
                current_effect_context.reset(token)
                deferred=None
                with self._borrowed_guard:
                    self._borrowed_count-=1
                    if not self._borrowed_count:
                        deferred=self._deferred_end;self._deferred_end=None
                if deferred:self._end(*deferred)
        try:
            task=asyncio.create_task(asyncio.to_thread(invocation))
        except BaseException:
            with self._borrowed_guard:self._borrowed_count-=1
            raise
        self._owned_blocking.add(task)
        def consume(done):
            self._owned_blocking.discard(done)
            if not done.cancelled():done.exception()
        task.add_done_callback(consume)
        return await asyncio.shield(task)

    async def run_async(self, effect: Callable[..., Any], *args, **kwargs) -> Any:
        """Run an owned async transport while retaining OS exclusion and lease."""
        # Acquire outside the event loop; only _begin waits and performs
        # synchronous central checks. No network effect happens in that thread.
        pending = asyncio.create_task(asyncio.to_thread(self._begin))
        try:
            lock, stop, worker = await asyncio.shield(pending)
        except asyncio.CancelledError:
            # Cancellation cannot abandon a lock acquired later by its worker.
            def release_abandoned(done):
                if not done.cancelled():
                    try:
                        self._end(*done.result())
                    except Exception:
                        pass
            pending.add_done_callback(release_abandoned)
            raise
        async def owned_invocation():
            token=current_effect_context.set(self)
            try:
                result=effect(*args, **kwargs)
                value=await result if inspect.isawaitable(result) else result
                with self._borrowed_guard:borrowed=self._had_blocking
                if not borrowed:self._late_return(value=value)
                return value
            except BaseException as exc:
                with self._borrowed_guard:borrowed=self._had_blocking
                if not borrowed:self._late_return(error_type=type(exc).__name__)
                raise
            finally:
                current_effect_context.reset(token)
                self._end_owned(lock,stop,worker)
        # The caller's cancellation does not cancel an already admitted RPC or
        # abandon a nested blocking worker. The owned task retains lock/lease;
        # checkpoints still reject further actions after grant/fence revocation.
        invocation=asyncio.create_task(owned_invocation())
        self._owned_async.add(invocation)
        def consume_completion(done):
            self._owned_async.discard(done)
            if not done.cancelled():done.exception()
        invocation.add_done_callback(consume_completion)
        return await asyncio.shield(invocation)
