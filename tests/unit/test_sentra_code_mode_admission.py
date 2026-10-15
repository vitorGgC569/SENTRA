"""Code Mode must not execute without audited QuickJS WASM isolation."""
import asyncio
import hashlib
import json
import pytest
from sentra_code_mode import QuickJSWasmAdmission, ResourceLimits, CodeModeDisabled
from sentra_runtime.contracts import OperationRequest


def test_denies_all_untrusted_execution_without_native_or_node_fallback(tmp_path):
    mode=QuickJSWasmAdmission()
    state=mode.status()
    assert not state["enabled"] and state["fallbacks"]==[] and state["host_io"] is False
    request=OperationRequest("op-wasm-123","agent-123","machine-123",
                             "code:execute","work-item-123","wasm-key-123",{})
    source="throw new Error('no I/O');"
    with pytest.raises(CodeModeDisabled,match="CodeModeDispatcher"):
        asyncio.run(mode.execute(request=request,source=source))
    # A hostile JS source is never evaluated; even a host-side side effect
    # expression embedded in the source stays an inert Python string.
    marker=tmp_path/"not-created"
    with pytest.raises(CodeModeDisabled):
        asyncio.run(mode.execute(request=request,
                     source="require('fs').writeFileSync("+repr(str(marker))+",'x')"))
    assert not marker.exists()
    with pytest.raises(ValueError,match="source"):
        asyncio.run(mode.execute(request=request,source="x"*65537))
    with pytest.raises(TypeError):
        asyncio.run(mode.execute(request=None,source="1+1"))
    with pytest.raises(ValueError):
        ResourceLimits(fuel=0)
    with pytest.raises(ValueError):
        ResourceLimits(memory_bytes=1<<40)
    with pytest.raises(ValueError):
        ResourceLimits(cpu_milliseconds=True)


def test_hash_and_sbom_do_not_accidentally_enable_wasm(tmp_path):
    wasm=tmp_path/"engine.wasm"
    wasm.write_bytes(bytes.fromhex("0061736d01000000"))
    sbom=tmp_path/"sbom.json"
    sbom.write_text(json.dumps({"bomFormat":"CycloneDX","specVersion":"1.5"}))
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    mode=QuickJSWasmAdmission()
    report=mode.inspect_artifact(wasm,sbom,expected_wasm_sha256=digest(wasm),
                                 expected_sbom_sha256=digest(sbom))
    assert report["enabled"] is False and not mode.status()["enabled"]
    with pytest.raises(ValueError,match="invalid or unpinned"):
        mode.inspect_artifact(wasm,sbom,expected_wasm_sha256="0"*64,
                              expected_sbom_sha256=digest(sbom))
    sbom.write_text('{"bomFormat":"unknown"}')
    with pytest.raises(ValueError,match="CycloneDX"):
        mode.inspect_artifact(wasm,sbom,expected_wasm_sha256=digest(wasm),
                              expected_sbom_sha256=digest(sbom))
