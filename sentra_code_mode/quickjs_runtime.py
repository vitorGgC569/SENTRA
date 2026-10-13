"""Pinned WASI-free guest ABI v1 with mandatory Wasmtime resource controls.

A worker/effect without confirmed termination is UNCERTAIN, never retried.
"""
from __future__ import annotations
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from . import (CodeModeBudgetExceeded, CodeModeCancelled, CodeModeUnavailable,
               CodeModeUncertain, ResourceLimits)
from .cpu_clock import WorkerCPUClock

_FUNCTIONS = {
    "configure": (["i64"] + ["i32"] * 6, ["i32"]),
    "eval_source": (["i32", "i32"], ["i32"]),
    "classify_exception": ([], ["i32"]), "alloc": (["i32"], ["i32"]),
    "reset_heap": ([], []), "shutdown": ([], []), "fuel_used": ([], ["i64"]),
    **{name: ([], ["i32"]) for name in ("result_ptr", "result_len", "error_ptr", "error_len", "tool_count")},
}


class QuickJSWasmRunner:
    def __init__(self, artifact, limits=None, *, cancel_event=None):
        self.artifact, self.limits = artifact, limits or ResourceLimits()
        self._cancel = cancel_event if cancel_event is not None else threading.Event()
        self._poisoned = False

    def cancel(self):
        self._cancel.set()

    def verified_bytes(self):
        from . import QuickJSWasmAdmission
        return QuickJSWasmAdmission(limits=self.limits).inspect_artifact(
            self.artifact.wasm_path, self.artifact.sbom_path,
            expected_wasm_sha256=self.artifact.wasm_sha256,
            expected_sbom_sha256=self.artifact.sbom_sha256)

    @staticmethod
    def _function_type(wasmtime, kind, params, results):
        if (not isinstance(kind, wasmtime.FuncType) or [str(v) for v in kind.params] != params
                or [str(v) for v in kind.results] != results):
            raise CodeModeUnavailable("guest ABI function signature mismatch")

    @staticmethod
    def _engine(wasmtime):
        try:
            config = wasmtime.Config()
            config.consume_fuel = True
            config.epoch_interruption = True
            config.wasm_threads = False
            config.max_wasm_stack = 512 * 1024
            return wasmtime.Engine(config)
        except (AttributeError, TypeError) as exc:
            raise CodeModeUnavailable("wasmtime lacks mandatory fuel/epoch/stack controls") from exc

    def _module(self, wasmtime, engine):
        proof = self.verified_bytes()
        with Path(self.artifact.wasm_path).open("rb") as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != self.artifact.wasm_sha256:
            raise CodeModeUnavailable("QuickJS artifact changed after provenance inspection")
        from .guest.inspect_wasm import inspect_abi
        inspect_abi(raw, memory_bytes=self.limits.memory_bytes)
        # Compile this exact hashed buffer, never deserialize native code.
        module = wasmtime.Module(engine, raw)
        imports = module.imports
        if len(imports) != 1 or (imports[0].module, imports[0].name) != ("env", "sentra_host_call"):
            raise CodeModeUnavailable("guest requires forbidden imports; no WASI is linked")
        self._function_type(wasmtime, imports[0].type, ["i32"] * 4, ["i32"])
        exports = {item.name: item.type for item in module.exports}
        if set(exports) != {"memory", *_FUNCTIONS}:
            raise CodeModeUnavailable("guest export set differs from ABI v1")
        memory = exports["memory"]
        if not isinstance(memory, wasmtime.MemoryType) or memory.is_64 or memory.is_shared:
            raise CodeModeUnavailable("ABI requires unshared wasm32 memory")
        if memory.limits.min * 65536 > self.limits.memory_bytes:
            raise CodeModeUnavailable("guest initial memory exceeds configured memory_bytes")
        for name, (params, results) in _FUNCTIONS.items():
            self._function_type(wasmtime, exports[name], params, results)
        return module, proof

    def readiness(self):
        try:
            import wasmtime
            engine = self._engine(wasmtime)
            _, proof = self._module(wasmtime, engine)
            if not all(callable(getattr(wasmtime.Store, name, None)) for name in
                       ("set_limits", "set_fuel", "get_fuel", "set_epoch_deadline")):
                raise CodeModeUnavailable("wasmtime lacks mandatory Store bounds")
            return {"enabled": True, "reason": "READY_ABI_V1", "abi": "guest/ABI.md v1",
                    "verified_bytes": proof["verified_bytes"], "wasi_imports": False,
                    "host_imports": ["env.sentra_host_call"], "execution_verified": False}
        except ImportError:
            return {"enabled": False, "reason": "QUICKJS_RUNTIME_UNAVAILABLE", "execution_verified": False}
        except Exception:
            return {"enabled": False, "reason": "QUICKJS_ARTIFACT_OR_ABI_UNAVAILABLE", "execution_verified": False}

    def _slice(self, memory, store, ptr, length):
        if (type(ptr) is not int or type(length) is not int or ptr < 0 or length < 0
                or length > self.limits.memory_bytes or ptr + length > memory.data_len(store)):
            raise CodeModeBudgetExceeded("guest memory slice outside bounds")

    def _mem_read(self, memory, store, ptr, length):
        self._slice(memory, store, ptr, length)
        data = bytes(memory.read(store, ptr, ptr + length))
        if len(data) != length:
            raise CodeModeUnavailable("guest memory read truncated")
        return data

    def _mem_write(self, memory, store, ptr, data):
        self._slice(memory, store, ptr, len(data))
        if memory.write(store, data, ptr) != len(data):
            raise CodeModeUnavailable("guest memory write truncated")

    def run(self, source, *, bridge=None, wall_deadline_s=None):
        raw = source.encode("utf-8")
        if not 1 <= len(raw) <= self.limits.max_source_bytes:
            raise CodeModeBudgetExceeded("source outside bounds")
        if self._poisoned:
            raise CodeModeUnavailable("guest runner abandoned; reconcile without retry")
        if bridge is None:
            raise PermissionError("central tool bridge required")
        if self._cancel.is_set():
            raise CodeModeCancelled("cancelled before instantiation")
        try:
            import wasmtime
        except ImportError as exc:
            raise CodeModeUnavailable("QuickJS wasmtime runtime is not distributed") from exc
        engine = self._engine(wasmtime)
        module, _ = self._module(wasmtime, engine)
        limits = self.limits
        wall_s = min(limits.wall_milliseconds / 1000, wall_deadline_s or float("inf"))
        # Separate from QuickJS polling quanta: bounds configure/JSON/native work.
        wasm_fuel = limits.fuel * 10_000
        outcome, interrupted = {}, {}
        done, ready, proceed = threading.Event(), threading.Event(), threading.Event()
        clock_lock = threading.Lock()

        def target():
            clock = None
            try:
                clock = WorkerCPUClock()
                outcome["clock"] = clock
                ready.set()
                proceed.wait()
                if self._cancel.is_set():
                    raise CodeModeCancelled("cancelled before guest start")
                store = wasmtime.Store(engine)
                store.set_limits(memory_size=limits.memory_bytes, table_elements=16384,
                                 instances=1, tables=1, memories=1)
                store.set_fuel(wasm_fuel)
                store.set_epoch_deadline(1)
                linker = wasmtime.Linker(engine)
                memory, host_calls, host_fault = None, 0, None

                def host_call(req_ptr, req_len, res_ptr, res_cap):
                    nonlocal host_calls, host_fault
                    if self._cancel.is_set() or interrupted:
                        return -4
                    if memory is None or not 1 <= req_len <= 128 + limits.max_arg_bytes or not 1 <= res_cap <= limits.max_result_bytes:
                        return -3
                    try:
                        self._slice(memory, store, res_ptr, res_cap)
                        payload = json.loads(self._mem_read(memory, store, req_ptr, req_len))
                        if (not isinstance(payload, dict) or set(payload) != {"v", "tool", "args"}
                                or payload["v"] != 1 or not isinstance(payload["tool"], str)
                                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", payload["tool"])
                                or not isinstance(payload["args"], dict)):
                            return -3
                        args_raw = json.dumps(payload["args"], ensure_ascii=False, allow_nan=False,
                                              separators=(",", ":")).encode()
                        if len(args_raw) > limits.max_arg_bytes or host_calls >= limits.max_tool_calls:
                            return -4
                        host_calls += 1
                        value = bridge.call_sync(payload["tool"], payload["args"])
                        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
                        if len(encoded) > res_cap:
                            return -2
                        self._mem_write(memory, store, res_ptr, encoded)
                        return len(encoded)
                    except CodeModeUncertain as exc:
                        host_fault = exc
                        self._cancel.set()
                        return -1
                    except (CodeModeCancelled, CodeModeBudgetExceeded):
                        return -4
                    except PermissionError:
                        return -1
                    except Exception:
                        return -3

                linker.define_func("env", "sentra_host_call",
                    wasmtime.FuncType([wasmtime.ValType.i32()] * 4, [wasmtime.ValType.i32()]), host_call)
                instance = linker.instantiate(store, module)
                exports = instance.exports(store)
                memory = exports["memory"]
                rc = exports["configure"](store, limits.fuel, limits.memory_bytes, 256 * 1024,
                    limits.max_tool_calls, limits.max_arg_bytes, limits.max_result_bytes, limits.max_source_bytes)
                if rc != 0:
                    raise CodeModeUnavailable("guest configure rejected resource limits")
                exports["reset_heap"](store)
                ptr = int(exports["alloc"](store, len(raw)))
                self._mem_write(memory, store, ptr, raw)
                rc = int(exports["eval_source"](store, ptr, len(raw)))
                if host_fault is not None:
                    raise host_fault
                if self._cancel.is_set():
                    raise CodeModeCancelled("guest cancellation observed")
                if interrupted:
                    raise CodeModeBudgetExceeded("guest interrupted by budget watchdog")
                tools = int(exports["tool_count"](store))
                if tools != host_calls or tools > limits.max_tool_calls or bridge.calls > tools:
                    raise CodeModeUnavailable("guest/host tool outbox count mismatch")
                if rc != 0:
                    if rc in (-10, -11, -12, -14, -15) or (rc == 1 and exports["classify_exception"](store) in (10, 11, 12)):
                        raise CodeModeBudgetExceeded("guest resource bound exceeded")
                    # Exception text can contain private source or secrets.
                    raise RuntimeError("guest JavaScript failed; no result committed")
                size = int(exports["result_len"](store))
                if not 1 <= size <= limits.max_result_bytes:
                    raise CodeModeBudgetExceeded("guest result outside bounds")
                blob = self._mem_read(memory, store, int(exports["result_ptr"](store)), size)
                result = json.loads(blob)
                fuel = int(exports["fuel_used"](store))
                if not 0 <= fuel <= limits.fuel:
                    raise CodeModeUnavailable("guest fuel accounting mismatch")
                cpu_ms = clock.seconds() * 1000
                if cpu_ms > limits.cpu_milliseconds:
                    raise CodeModeBudgetExceeded("guest CPU budget exceeded")
                outcome["pair"] = (result, {"fuel_used": fuel, "tool_calls": tools, "result_bytes": size,
                    "wasm_fuel_used": wasm_fuel - store.get_fuel(), "cpu_milliseconds": cpu_ms,
                    "execution_proof": {"runtime": "wasmtime", "abi": 1, "guest_completed": True,
                        "wasm_sha256": self.artifact.wasm_sha256, "sbom_sha256": self.artifact.sbom_sha256,
                        "wasi_imports": False, "fuel_enforced": True, "memory_enforced": True,
                        "cpu_enforced": True, "epoch_enforced": True},
                    "tool_operations": list(getattr(bridge, "operations", []))})
            except BaseException as exc:
                outcome["error"] = exc
            finally:
                ready.set()
                # POSIX thread CPU identifiers must not be read after exit.
                with clock_lock:
                    done.set()
                    if clock is not None:
                        clock.close()

        worker = threading.Thread(target=target, name="sentra-quickjs-guest", daemon=True)
        started = time.monotonic()
        worker.start()
        while not ready.wait(0.005):
            if time.monotonic() - started >= wall_s:
                self._cancel.set()
                break
        proceed.set()
        while not done.wait(0.005):
            reason = None
            if self._cancel.is_set():
                reason = "cancel"
            elif time.monotonic() - started >= wall_s:
                reason = "wall"
            else:
                try:
                    with clock_lock:
                        if not done.is_set() and outcome.get("clock") and outcome["clock"].seconds() * 1000 >= limits.cpu_milliseconds:
                            reason = "CPU"
                except CodeModeUnavailable:
                    reason = "CPU accounting"
            if reason:
                interrupted["reason"] = reason
                engine.increment_epoch()
                if not done.wait(0.25):
                    self._cancel.set()
                    self._poisoned = True
                    # Waiter becomes UNCERTAIN while the parent's borrowed
                    # worker retains exclusion until the actual thread stops.
                    while not done.wait(0.05):
                        pass
                    raise CodeModeUncertain("guest termination delayed; reconcile without retry")
                break
        worker.join(timeout=0)
        if interrupted:
            if interrupted["reason"] == "cancel":
                raise CodeModeCancelled("guest cancellation confirmed")
            raise CodeModeBudgetExceeded("guest " + interrupted["reason"] + " budget exceeded")
        if "error" in outcome:
            error = outcome["error"]
            if isinstance(error, wasmtime.Trap):
                raise CodeModeBudgetExceeded("guest trapped under resource controls") from error
            raise error
        return outcome["pair"]
