"""Fail-closed admission for bounded Code Mode execution.

Real bounded execution lives in :mod:`sentra_code_mode.bounded_js` (built-in
auditable JS-subset interpreter, stdlib only) and
:mod:`sentra_code_mode.quickjs_runtime` (real QuickJS WASM via wasmtime when a
pinned artifact + SBOM are configured). This package contains NO Python
eval/exec, no Node/VM subprocess and no WASI host imports. An SBOM/hash is a
supply-chain prerequisite, NEVER proof of CPU/fuel isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import json

from sentra_runtime.contracts import OperationRequest


class CodeModeDisabled(PermissionError):
    """Code dispatch not allowed without a reviewed sandbox and central gate."""


class CodeModeUnavailable(PermissionError):
    """Configured engine is explicitly unavailable (missing artifact/runtime)."""


class CodeModeCancelled(RuntimeError):
    """A running execution was cancelled via watchdog/cancel before completion."""


class CodeModeBudgetExceeded(RuntimeError):
    """Source, fuel, memory, wall-time, tool-call or result bound was exceeded."""


class CodeModeUncertain(RuntimeError):
    """A started worker/effect has no confirmed terminal outcome; never retry it."""


@dataclass(frozen=True)
class ResourceLimits:
    fuel: int = 500_000
    memory_bytes: int = 16 * 1024 * 1024
    cpu_milliseconds: int = 1000
    wall_milliseconds: int = 2000
    max_source_bytes: int = 64 * 1024
    max_result_bytes: int = 64 * 1024
    max_tool_calls: int = 8
    max_arg_bytes: int = 8 * 1024

    def __post_init__(self):
        caps = {"fuel": (1, 2_000_000), "memory_bytes": (1024 * 1024, 32 * 1024 * 1024),
                "cpu_milliseconds": (1, 2000), "wall_milliseconds": (1, 5000),
                "max_source_bytes": (1, 64 * 1024), "max_result_bytes": (1, 64 * 1024),
                "max_tool_calls": (0, 32), "max_arg_bytes": (1, 16 * 1024)}
        for field, (lo, hi) in caps.items():
            n = getattr(self, field)
            if type(n) is not int or not lo <= n <= hi:
                raise ValueError("unbounded Code Mode resource limit: " + field)

    def as_dict(self) -> dict[str, int]:
        return {key: getattr(self, key) for key in
                ("fuel", "memory_bytes", "cpu_milliseconds", "wall_milliseconds",
                 "max_source_bytes", "max_result_bytes", "max_tool_calls", "max_arg_bytes")}


@dataclass(frozen=True)
class QuickJSArtifact:
    """Pinned local QuickJS WASM artifact + CycloneDX SBOM (both required)."""
    wasm_path: str
    sbom_path: str
    wasm_sha256: str
    sbom_sha256: str

    def __post_init__(self):
        for name in ("wasm_sha256", "sbom_sha256"):
            value = getattr(self, name)
            if (type(value) is not str or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)):
                raise ValueError("both provenance digests must be explicit SHA256")


class QuickJSWasmAdmission:
    """Read-only local artifact inspection; never activates execution by itself.

    An audit must establish a sandboxed WASI-free engine with deterministic
    interrupt/fuel, memory and CPU watchdog, no host imports and a reviewed SBOM.
    The secure executor must then bind every tool call to the host's
    OperationRequest and DurableOperationGate (not to a JS-provided grant).
    """

    def __init__(self, *, limits: ResourceLimits | None = None,
                 artifact: QuickJSArtifact | None = None):
        self.limits = limits or ResourceLimits()
        self.artifact = artifact

    def status(self) -> dict[str, Any]:
        base: dict[str, Any] = {"engine": "quickjs-wasm",
                                "operation_required": True, "host_io": False,
                                "fallbacks": [], "execution_verified": False,
                                "interim_opt_in_engines": ["bounded-js"],
                                "limits": self.limits.as_dict()}
        if self.artifact is None:
            return {**base, "enabled": False,
                    "reason": "QUICKJS_ARTIFACT_UNCONFIGURED",
                    "remediation": "pin wasm_path/sbom_path + SHA256 via host config"}
        try:
            from .quickjs_runtime import QuickJSWasmRunner
            detail = QuickJSWasmRunner(self.artifact, self.limits).readiness()
            return {**base, **detail}
        except Exception as exc:
            return {**base, "enabled": False,
                    "reason": "QUICKJS_RUNTIME_UNAVAILABLE", "detail": str(exc)[:200]}

    def inspect_artifact(self, wasm_path: str | Path, sbom_path: str | Path,
                         *, expected_wasm_sha256: str,
                         expected_sbom_sha256: str) -> dict[str, Any]:
        """Check pinned local artifact bytes. No installation, execution or I/O imports."""
        if any(type(s) is not str or len(s) != 64 or
               any(c not in "0123456789abcdef" for c in s)
               for s in (expected_wasm_sha256, expected_sbom_sha256)):
            raise ValueError("both provenance digests must be explicit SHA256")
        wasm = Path(wasm_path)
        sbom = Path(sbom_path)
        if not wasm.is_file() or not sbom.is_file():
            raise FileNotFoundError("pinned QuickJS WASM and SBOM required")
        if wasm.stat().st_size > 32 * 1024 * 1024 or sbom.stat().st_size > 1024 * 1024:
            raise ValueError("unbounded runtime artifact")
        for candidate in (wasm, sbom):
            if candidate.is_symlink():
                raise ValueError("symlink runtime provenance is not accepted")
        wasm_bytes = wasm.read_bytes()
        sbom_bytes = sbom.read_bytes()
        if (not wasm_bytes.startswith(bytes.fromhex("0061736d")) or
                hashlib.sha256(wasm_bytes).hexdigest() != expected_wasm_sha256 or
                hashlib.sha256(sbom_bytes).hexdigest() != expected_sbom_sha256):
            raise ValueError("invalid or unpinned WASM artifact")
        meta = json.loads(sbom_bytes)
        if not isinstance(meta, dict) or not meta.get("bomFormat") == "CycloneDX":
            raise ValueError("reviewable CycloneDX SBOM required")
        return {"provenance_sha256": expected_wasm_sha256,
                "sbom_sha256": expected_sbom_sha256,
                "verified_bytes": len(wasm_bytes),
                "enabled": False,
                "reason": "provenance alone does not attest host isolation or fuel"}

    async def execute(self, *, request: OperationRequest, source: str,
                      control: Any = None) -> None:
        # Legacy deny entry-point kept for callers that have not migrated to
        # CodeModeDispatcher.dispatch(). It never executes: use the dispatcher.
        if not isinstance(request, OperationRequest):
            raise TypeError("host-created durable OperationRequest required")
        if type(source) is not str or len(source.encode("utf-8")) > self.limits.max_source_bytes:
            raise ValueError("source outside Code Mode bounds")
        raise CodeModeDisabled(
            "use CodeModeDispatcher.dispatch() with a WorkItem-bound proposal")
