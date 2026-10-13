"""Stable Code Mode signatures + JSON schemas for central composition.

Owner: Pacto. Consumer: Codex (sentra_canvas/service.py, server.py, shell
bridge actions ``code_propose``/``code_execute``/``code_status``/``code_cancel``).
No second authority: the dispatcher binds the ControlPlaneService passed by
the host; this module only describes the contract.
"""
from __future__ import annotations

CODE_MODE_SIGNATURE = {
    "service": "sentra_code_mode.dispatcher.CodeModeDispatcher",
    "engines": ["quickjs-wasm", "bounded-js"],
    "default_engine": "quickjs-wasm",
    "a08_statement": "A08 is satisfied ONLY by engine 'quickjs-wasm' with the "
                     "pinned guest artifact (guest/ABI.md v1, guest/build.sh, "
                     "guest/PROVENANCE.md). 'bounded-js' is an explicit opt-in "
                     "interim engine; every bounded-js receipt carries "
                     "a08_satisfied=false and it is never the A08 solution.",
    "methods": {
        "propose": {
            "params": ["owner", "workspace", "run_id", "work_item_id",
                       "agent_id", "source", "engine?"],
            "returns": ["proposal_id", "source_sha256", "source_bytes",
                        "engine", "state", "grants_created", "worker_started", "effect"],
            "effects": "none (inert, content-addressed admission)",
        },
        "execute": {
            "params": ["owner", "proposal_id", "operation_id",
                       "idempotency_key", "source?", "tools?"],
            "returns": ["proposal_id", "ok", "engine", "result",
                        "result_sha256", "result_bytes", "tool_calls",
                        "fuel_used", "grants_created", "operation_id"],
            "effects": "bounded run; one OperationRequest per call_tool via central gate",
            "idempotent": "replay with same operation_id returns stored receipt",
        },
        "dispatch": {
            "params": ["owner", "workspace", "run_id", "work_item_id",
                       "agent_id", "source", "operation_id",
                       "idempotency_key", "tools?", "engine?"],
            "returns": "execute() receipt or {ok:false, error, error_type}",
            "effects": "propose + execute",
        },
        "status": {
            "params": ["owner", "proposal_id"],
            "returns": ["proposal fields", "limits", "executions", "cancel_requested"],
            "effects": "none (read-only)",
        },
        "cancel": {
            "params": ["owner", "proposal_id"],
            "returns": ["proposal_id", "cancel_requested", "state", "grants_created"],
            "effects": "sets cancel flag observed by watchdog/interrupt",
        },
        "inventory": {
            "params": ["owner", "limit?"],
            "returns": ["owner", "items(proposal_id, run_id, work_item_id, agent_id, "
                        "source_sha256, source_bytes, engine, state, last_execution, "
                        "a08_satisfied)", "grants_created"],
            "effects": "none (read-only, same authority)",
        },
        "discovery": {
            "params": [],
            "returns": ["signature", "engine", "artifact_configured", "admission"],
            "effects": "none (read-only, same authority, no owner data)",
        },
    },
    "central_helpers": {
        "module": "sentra_code_mode.composition",
        "compose_quickjs_dispatcher": "control + host-approved artifact/env pins -> "
                                      "CodeModeDispatcher(engine='quickjs-wasm'); "
                                      "quickjs-only, no subset counted as A08",
        "approve_artifact": "host-approved wasm/sbom paths + SHA256 -> QuickJSArtifact "
                            "(bytes verified at admission/readiness/every run)",
        "build_fenced_tool_map": "host-selected name->callable map (max 32, charset "
                                 "enforced); each inner call is its OWN OperationRequest; "
                                 "empty map denies call_tool; creates no grants",
        "declare_code_machine": "owner + tool names -> Machine(code:configure/restore/"
                                "inventory/discovery + code-tool:<name>), same central "
                                "authority, mints no grants",
        "machine_adapter": "(machine, CentralInteropAdapter) for Nexo/root; lifecycle "
                           "mapping configure->propose, restore->cancel+idempotent replay, "
                           "inventory->inventory(), discovery->discovery()",
    },
    "tool_bridge": {
        "js_surface": "call_tool(name: string, args: object) -> value",
        "handler_source": "host-selected callables keyed by allowlisted name; "
                          "never JS-provided, never model-provided",
        "grant": "one OperationRequest per call (capability code-tool:<name>), "
                 "decided + fenced by CentralInteropAdapter; sandbox mints no grants",
        "bounds": ["max_tool_calls", "max_arg_bytes"],
    },
    "limits_schema": {
        "fuel": {"type": "int", "min": 1, "max": 2000000, "default": 500000},
        "memory_bytes": {"type": "int", "min": 1048576, "max": 33554432,
                         "default": 16777216},
        "cpu_milliseconds": {"type": "int", "min": 1, "max": 2000, "default": 1000},
        "wall_milliseconds": {"type": "int", "min": 1, "max": 5000, "default": 2000},
        "max_source_bytes": {"type": "int", "min": 1, "max": 65536, "default": 65536},
        "max_result_bytes": {"type": "int", "min": 1, "max": 65536, "default": 65536},
        "max_tool_calls": {"type": "int", "min": 0, "max": 32, "default": 8},
        "max_arg_bytes": {"type": "int", "min": 1, "max": 16384, "default": 8192},
    },
    "quickjs_artifact_schema": {
        "wasm_path": "pinned local .wasm file (magic 00 61 73 6d, <=32MiB, no symlink)",
        "sbom_path": "pinned local CycloneDX SBOM (<=1MiB, no symlink)",
        "wasm_sha256": "64 hex chars",
        "sbom_sha256": "64 hex chars",
    },
    "shell_bridge_actions": ["code_propose", "code_execute", "code_status", "code_cancel", "code_discovery"],
    "shell_bridge_schema": {
        "code_propose": ["machine_id", "work_item_id", "source"],
        "code_execute": ["machine_id", "work_item_id", "proposal_id"],
        "code_cancel": ["machine_id", "work_item_id", "proposal_id"],
        "code_status": ["machine_id", "proposal_id"], "code_discovery": ["machine_id?"],
        "common": ["project_id", "space_id?", "conversation_id?", "request_key (mutations)"],
        "result": "operation_id/state/evidence/value?; private value only after central SUCCEEDED + receipt hash",
    },
    "errors": ["CodeModeDisabled", "CodeModeUnavailable", "CodeModeCancelled",
               "CodeModeBudgetExceeded", "CodeModeUncertain", "PermissionError", "ValueError", "FileNotFoundError"],
    "invariants": [
        "no Python eval/exec, no Node/VM subprocess, no WASI imports, no host I/O in sandbox",
        "ChatTrust/block + read/action consent never create grants",
        "deny-only removed: bounded-js executes real code; quickjs-wasm reports explicit UNAVAILABLE until reviewed",
    ],
}
