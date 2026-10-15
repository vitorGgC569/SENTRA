"""Real Wasmtime/QuickJS acceptance; local probes authorize no system effects."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sentra_code_mode import (QuickJSArtifact, ResourceLimits, CodeModeBudgetExceeded, CodeModeCancelled)
from sentra_code_mode.quickjs_runtime import QuickJSWasmRunner


class DeniedBridge:
    calls = 0
    operations = ()

    def call_sync(self, name, args):
        raise PermissionError("QA authorizes no system effects")


def verify(artifact_dir: Path, output: Path):
    artifact_dir = artifact_dir.resolve(strict=True)
    wasm, sbom = artifact_dir / "sentra_quickjs_guest.wasm", artifact_dir / "sbom.cdx.json"
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    artifact = QuickJSArtifact(str(wasm), str(sbom), sha(wasm), sha(sbom))
    readiness = QuickJSWasmRunner(artifact).readiness()
    assert readiness["enabled"], readiness
    cases = []

    def success(name, source, expected):
        started = time.monotonic()
        result, proof = QuickJSWasmRunner(artifact).run(source, bridge=DeniedBridge())
        assert result == expected, (name, result)
        assert proof["execution_proof"]["guest_completed"] is True
        assert proof["execution_proof"]["wasi_imports"] is False
        cases.append({"case": name, "passed": True, "ms": round((time.monotonic() - started) * 1000, 2), "proof": proof})

    def rejects(name, source, exception, *, limits=None, reason=None):
        started = time.monotonic()
        try:
            QuickJSWasmRunner(artifact, limits).run(source, bridge=DeniedBridge())
        except exception as error:
            if reason:
                assert reason in str(error), str(error)
            cases.append({"case": name, "passed": True, "exception": exception.__name__,
                          "ms": round((time.monotonic() - started) * 1000, 2)})
        else:
            raise AssertionError(name + " did not enforce its boundary")

    success("arithmetic", "6 * 7", 42)
    success("unicode_and_host_absence", '({unicode:"\\uD83E\\uDE90",date:typeof Date,process:typeof process,require:typeof require,fetch:typeof fetch})',
            {"unicode": "\U0001fa90", "date": "undefined", "process": "undefined", "require": "undefined", "fetch": "undefined"})
    success("denied_tool_cannot_create_an_effect", "try { call_tool('filesystem.write', {}); } catch (e) { 'denied'; }", "denied")
    rejects("infinite_loop", "while (true) {}", CodeModeBudgetExceeded)
    rejects("result_limit", '"x".repeat(70000)', CodeModeBudgetExceeded)
    rejects("memory_limit", "new Array(10000000).fill('bounded')", CodeModeBudgetExceeded)
    rejects("nondeterministic_random_disabled", "Math.random()", RuntimeError)
    rejects("javascript_exception", "throw new Error('public QA marker')", RuntimeError)
    expensive = 'const a="a".repeat(20000); /^(a+)+$/.test(a+"b")'
    rejects("native_worker_cpu_limit", expensive, CodeModeBudgetExceeded,
            limits=ResourceLimits(fuel=2000000, cpu_milliseconds=1, wall_milliseconds=5000), reason="CPU")
    rejects("wall_watchdog", expensive, CodeModeBudgetExceeded,
            limits=ResourceLimits(fuel=2000000, cpu_milliseconds=2000, wall_milliseconds=1), reason="wall")

    # Synchronize cancellation with a running worker, rather than cancelling
    # before it starts. The only callback is a local thread synchronization
    # probe, not a real tool or a forged Control Plane receipt.
    entered, release = threading.Event(), threading.Event()

    class ProbeBridge:
        calls = 0
        operations = ()

        def call_sync(self, name, args):
            assert name == "qa.probe" and args == {}
            self.calls += 1
            entered.set()
            assert release.wait(1)
            return {"probe": True}

    runner, outcome = QuickJSWasmRunner(artifact), []

    def run_cancelled():
        try:
            runner.run("call_tool('qa.probe', {}); while (true) {}", bridge=ProbeBridge())
        except BaseException as error:
            outcome.append(error)

    worker = threading.Thread(target=run_cancelled, daemon=True)
    worker.start()
    try:
        assert entered.wait(5), "worker did not reach the local probe"
        runner.cancel()
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive(), "cancelled worker did not terminate"
    assert outcome and isinstance(outcome[0], CodeModeCancelled), outcome
    cases.append({"case": "cancellation_during_worker_execution", "passed": True})
    report = {"wasm_sha256": artifact.wasm_sha256, "sbom_sha256": artifact.sbom_sha256,
              "runtime": "real wasmtime / compiled QuickJS", "cases": cases,
              "system_effects_authorized": False, "control_plane_tool_integration": False,
              "installed_release_journey": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases_passed": len(cases), "wasm_sha256": artifact.wasm_sha256, "report": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp/astra-quickjs-runtime.json")
    args = parser.parse_args()
    verify(args.artifact, args.output)
