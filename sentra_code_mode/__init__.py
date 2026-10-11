"""Fail-closed admission for the not-yet-audited QuickJS WASM runtime.

This package deliberately contains NO Python eval/exec, node/vm, subprocess or
WASM host runner. An SBOM/hash is only a supply-chain prerequisite, NEVER proof
of CPU/fuel isolation or of no host I/O. Until a *separately audited* bounded
QuickJS WASM runtime is installed, all Code Mode dispatch is denied.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from sentra_runtime.contracts import OperationRequest

class CodeModeDisabled(PermissionError):
    """Code dispatch not allowed without a reviewed WASM sandbox and central gate."""


@dataclass(frozen=True)
class ResourceLimits:
    fuel: int = 500_000
    memory_bytes: int = 16 * 1024 * 1024
    cpu_milliseconds: int = 1000
    wall_milliseconds: int = 2000
    max_source_bytes: int = 64 * 1024
    max_result_bytes: int = 64 * 1024

    def __post_init__(self):
        caps = {"fuel":(1,2_000_000),"memory_bytes":(1024*1024,32*1024*1024),
                "cpu_milliseconds":(1,2000),"wall_milliseconds":(1,5000),
                "max_source_bytes":(1,64*1024),"max_result_bytes":(1,64*1024)}
        for field,(lo,hi) in caps.items():
            n=getattr(self,field)
            if type(n) is not int or not lo <= n <= hi:
                raise ValueError("unbounded Code Mode resource limit: " + field)


class QuickJSWasmAdmission:
    """Read-only local artifact inspection; never activates execution.

    An audit must establish a sandboxed WASI-free engine with deterministic
    interrupt/fuel, memory and CPU watchdog, no host imports and a reviewed SBOM.
    The secure executor must then bind every tool call to the host's
    OperationRequest and DurableOperationGate (not to a JS-provided grant).
    """

    def __init__(self, *, limits: ResourceLimits | None = None):
        self.limits = limits or ResourceLimits()

    def status(self) -> dict[str, Any]:
        return {"enabled": False, "engine": "quickjs-wasm",
                "reason": "AUDITED_ISOLATED_RUNTIME_UNAVAILABLE",
                "fallbacks": [], "host_io": False,
                "operation_required": True, "limits": {
                    key: getattr(self.limits,key) for key in
                    ("fuel","memory_bytes","cpu_milliseconds",
                     "wall_milliseconds","max_source_bytes","max_result_bytes")}}

    def inspect_artifact(self, wasm_path: str | Path, sbom_path: str | Path,
                         *, expected_wasm_sha256: str,
                         expected_sbom_sha256: str) -> dict[str, Any]:
        """Check pinned local artifact bytes. No installation, execution or I/O imports."""
        if any(type(s) is not str or len(s)!=64 or
               any(c not in "0123456789abcdef" for c in s)
               for s in (expected_wasm_sha256, expected_sbom_sha256)):
            raise ValueError("both provenance digests must be explicit SHA256")
        wasm=Path(wasm_path)
        sbom=Path(sbom_path)
        if not wasm.is_file() or not sbom.is_file():
            raise FileNotFoundError("pinned QuickJS WASM and SBOM required")
        if wasm.stat().st_size > 32*1024*1024 or sbom.stat().st_size > 1024*1024:
            raise ValueError("unbounded runtime artifact")
        # Confining to preinstalled regular files is the caller's responsibility;
        # no special file/device is ever used as a runtime.
        for candidate in (wasm,sbom):
            if candidate.is_symlink():
                raise ValueError("symlink runtime provenance is not accepted")
        wasm_bytes=wasm.read_bytes()
        sbom_bytes=sbom.read_bytes()
        if (not wasm_bytes.startswith(bytes.fromhex("0061736d")) or
            hashlib.sha256(wasm_bytes).hexdigest()!=expected_wasm_sha256 or
            hashlib.sha256(sbom_bytes).hexdigest()!=expected_sbom_sha256):
            raise ValueError("invalid or unpinned WASM artifact")
        meta=json.loads(sbom_bytes)
        if not isinstance(meta,dict) or not meta.get("bomFormat")=="CycloneDX":
            raise ValueError("reviewable CycloneDX SBOM required")
        return {"provenance_sha256":expected_wasm_sha256,
                "sbom_sha256":expected_sbom_sha256,
                "verified_bytes":len(wasm_bytes),
                "enabled":False,
                "reason":"provenance alone does not attest host isolation or fuel"}

    async def execute(self, *, request: OperationRequest, source: str,
                      control: Any = None) -> None:
        # Always DENY. Do not create grants, reserve operations, touch the host,
        # fall back to Python eval, Node VM, JS interpreters or a native process.
        if not isinstance(request,OperationRequest):
            raise TypeError("host-created durable OperationRequest required")
        if type(source) is not str or len(source.encode("utf-8")) > self.limits.max_source_bytes:
            raise ValueError("source outside Code Mode bounds")
        raise CodeModeDisabled("QuickJS WASM remains disabled: no audited physical sandbox")
