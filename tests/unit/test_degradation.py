"""Dead-path matrix + budget clock: pure logic, fakes only, no live calls."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from orchestrator.providers.base import AgentResponse
from orchestrator.providers.degradation import (
    ABORT,
    DEGRADE_ONCE,
    RECONCILE,
    RETRY,
    DeadPathBudget,
    decide,
    is_dead_path,
    mark_degraded,
)


@pytest.mark.parametrize("error", [
    "[TOOL_ERROR] task=T-1 no extension connected: nenhum worker fez poll",
    "[MODEL_ERROR] task=T-2 [sw=1.4.0] LEASE_LOST",
    "LEASE_EXPIRED before ack",
    "TAB_STALE: content-script obsoleto persistente na tab 12",
    "TAB_ERROR tab=7: tab sumiu durante navegacao",
])
def test_dead_path_markers_detected(error):
    assert is_dead_path(error) is True
    assert decide(error) == DEGRADE_ONCE


@pytest.mark.parametrize("error", [
    "[MODEL_ERROR] task=T-1 gotcha",
    "QUALITY: verdict uncertain, needs repair",
    "PATCH_SYNTAX: hunk counts do not match",
    "[CONTEXT_BUDGET] prompt exceeds 20000 characters; no text was sent",
    "[CONVERSATION_MISMATCH] result came from another conversation",
    "[IMAGE_ERROR] evidence file not found; no text was sent",
    "planner provider failed",
    "",
])
def test_content_quality_never_dead_path_never_degrades(error):
    assert is_dead_path(error) is False
    assert decide(error) == ABORT


@pytest.mark.parametrize("error", [
    "[MODEL_ERROR] DELIVERY_UNCERTAIN: state unknown",
    "[MODEL_ERROR] SUBMISSION_UNCERTAIN: not confirmed",
    "DELIVERY_EXPIRED: execution uncertain; not automatically resent",
])
def test_uncertain_delivery_reconciles(error):
    assert decide(error) == RECONCILE
    # Even with a lease marker inside, uncertainty wins (except the
    # pre-submit no-extension override below).
    assert decide(error + " LEASE_LOST") == RECONCILE


@pytest.mark.parametrize("error", [
    "[MODEL_ERROR] ACCOUNT_LIMIT reached",
    "RATE_LIMIT: slow down",
    "QUOTA_EXCEEDED for today",
    "[CONVERSATION_BLOCKED] seat requires reconciliation",
    "relay pairing required: start python main.py --relay",
    "PAIRING_REQUIRED",
])
def test_blocked_quota_pairing_aborts_fast(error):
    assert decide(error) == ABORT


@pytest.mark.parametrize("error", [
    "[TIMEOUT] provider 'extension': job exceeded 300s",
    "provider timed out after 30s",
    "STALE_CONVERSATION: conversa nao mudou apos new_chat",
    "IN_FLIGHT intent already persisted",
    "SUBMIT_FAILED:unreachable",
])
def test_transient_delivery_retries(error):
    assert decide(error) == RETRY


def test_no_extension_overrides_misleading_uncertain_metadata():
    error = "[TOOL_ERROR] task=T-9 no extension connected: nenhum worker fez poll"
    uncertain = {"delivery_state": "UNCERTAIN", "retry_safe": False}
    assert decide(error, uncertain) == DEGRADE_ONCE


def test_uncertain_metadata_forces_reconcile_for_lease():
    error = "[MODEL_ERROR] task=T-3 [sw=1.4.0] LEASE_LOST"
    assert decide(error) == DEGRADE_ONCE  # clean metadata: degradable
    uncertain = {"delivery_state": "UNCERTAIN", "retry_safe": False}
    assert decide(error, uncertain) == RECONCILE  # may have sent: reconcile
    blocked = {"delivery_state": "BLOCKED", "retry_safe": False}
    assert decide(error, blocked) == RECONCILE


def test_not_sent_prompt_integrity_does_not_degrade():
    for code in ("PROMPT_MISMATCH", "FILL_FAILED", "CLEAR_FAILED", "STALE_DRAFT"):
        assert decide(f"{code}: composer divergiu") == ABORT


def test_budget_counts_streak_and_trips_ceiling():
    budget = DeadPathBudget(max_consecutive_dead_path=3)
    assert budget.should_abort() is False
    assert budget.record_dead_path() is False
    assert budget.record_dead_path() is False
    assert budget.consecutive_dead_path == 2
    assert budget.record_dead_path() is True
    assert budget.should_abort() is True


def test_budget_degraded_success_still_counts_path_dead():
    budget = DeadPathBudget(max_consecutive_dead_path=2)
    budget.record_degraded()
    assert budget.should_abort() is False
    budget.record_degraded()
    assert budget.should_abort() is True
    assert budget.total_degraded == 2


def test_budget_resets_only_on_primary_success():
    budget = DeadPathBudget(max_consecutive_dead_path=3)
    budget.record_dead_path()
    budget.record_dead_path()
    budget.record_success()
    assert budget.consecutive_dead_path == 0
    assert budget.should_abort() is False
    # Totals are preserved for observability.
    assert budget.total_dead_path == 2


def test_budget_rejects_bad_ceiling():
    with pytest.raises(ValueError):
        DeadPathBudget(max_consecutive_dead_path=0)
    with pytest.raises(ValueError):
        DeadPathBudget(max_consecutive_dead_path=11)


def test_mark_degraded_labels_weak_evidence_honestly():
    resp = AgentResponse(content="weak answer", success=True, model="qwen-local",
                         metadata={"foo": "bar"})
    out = mark_degraded(resp, "[TOOL_ERROR] no extension connected")
    assert out.metadata["degraded"] is True
    assert "no extension connected" in out.metadata["original_error"]
    assert out.metadata["degraded_reason"] == "dead-path-fallback"
    assert out.content == "weak answer"
    assert out.model == "qwen-local"  # weak model name preserved, never upgraded
    # First error wins on double marking.
    mark_degraded(out, "second error")
    assert "no extension connected" in out.metadata["original_error"]


def test_probe_refuses_non_loopback():
    from orchestrator.providers.local_provider import probe_local_endpoint
    with pytest.raises(ValueError, match="loopback"):
        probe_local_endpoint("http://192.168.1.10:11434/v1", timeout_s=1.0)


def test_probe_reports_unreachable_without_prompts():
    from orchestrator.providers.local_provider import probe_local_endpoint
    # Port 9 (discard) is never a model server; GET version must fail fast
    # with reachable False and no exception escaping.
    result = probe_local_endpoint("http://127.0.0.1:9/v1", timeout_s=1.0)
    assert result["reachable"] is False
    assert len(result["checked"]) == 2
    assert result["error"]


def test_probe_reads_version_from_loopback_stub():
    from orchestrator.providers.local_provider import probe_local_endpoint

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/version":
                body = json.dumps({"version": "stub-0.0.1"}).encode()
            elif self.path == "/v1/models":
                body = json.dumps({"data": [{"id": "stub-model"}]}).encode()
            else:
                body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/v1"
        result = probe_local_endpoint(base, timeout_s=2.0)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert result["reachable"] is True
