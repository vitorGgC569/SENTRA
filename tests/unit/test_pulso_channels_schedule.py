"""Pulso channels + timezone scheduling + terminal GC.

Future validation only (not executed during integral implementation).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sentra_interop.workflow_channels import (
    ChannelTriggerBridge, verify_slack_signature, verify_telegram_secret,
    verify_whatsapp_signature, ChannelDenied)
from sentra_mcp.services.routine_scheduler import (
    RoutinePolicyStore, RoutineScheduleTZ)


# -- signature verifiers -------------------------------------------------
def test_slack_signature_roundtrip():
    import hashlib
    import hmac as hmac_module
    secret, body, ts = "s3cr3t", b'{"type":"url_verification"}', "1700000000"
    signature = "v0=" + hmac_module.new(
        secret.encode(), f"v0:{ts}:".encode() + body,
        hashlib.sha256).hexdigest()
    verify_slack_signature(secret=secret, timestamp=ts, raw_body=body,
                           signature=signature, now=1700000000.0)
    with pytest.raises(ChannelDenied):
        verify_slack_signature(secret=secret, timestamp=ts, raw_body=body,
                               signature="v0=" + "0" * 64, now=1700000000.0)
    with pytest.raises(ChannelDenied):
        verify_slack_signature(secret=secret, timestamp=ts, raw_body=body,
                               signature=signature, now=1700000000.0 + 301)


def test_telegram_and_whatsapp_verifiers():
    verify_telegram_secret(expected_token="tok", provided_token="tok")
    with pytest.raises(ChannelDenied):
        verify_telegram_secret(expected_token="tok", provided_token="nope")
    import hashlib
    import hmac as hmac_module
    secret, body = "app-secret", b'{"entry":[]}'
    signature = "sha256=" + hmac_module.new(
        secret.encode(), body, hashlib.sha256).hexdigest()
    verify_whatsapp_signature(secret=secret, raw_body=body, signature=signature)
    with pytest.raises(ChannelDenied):
        verify_whatsapp_signature(secret=secret, raw_body=body,
                                  signature="sha256=" + "0" * 64)


# -- channel lifecycle + triggers ----------------------------------------
def _bridge(tmp_path, **kwargs):
    admitted = {}

    def fake_admitter(channel, subscription_id, event_key, event):
        admitted[event_key] = event
        return {"work_item_id": "w-" + event_key}

    def fake_lookup(subscription_id, event_key):
        return {"work_item_id": "w-" + event_key} if event_key in admitted else None

    return ChannelTriggerBridge(
        str(tmp_path / "chan.sqlite3"), workspace=str(tmp_path),
        secret_resolver=lambda secret_id: "s3cr3t" if secret_id == "sec1" else "",
        trigger_admitter=fake_admitter, trigger_lookup=fake_lookup,
        outbound_sender=lambda request, channel, recipient, payload: {
            "provider_message_id": "pm-1"},
        external_unsubscriber=lambda channel, external_id: {
            "removed": True, "reference": external_id},
        **kwargs)


def test_channel_enable_ingest_dedupe_disable(tmp_path):
    import hashlib
    import hmac as hmac_module
    bridge = _bridge(tmp_path)
    bridge.enable(owner="o", subscription_id="sub1", channel="slack",
                  project_id="ws1", allow_workspaces=["ws-team"],
                  allow_users=["U123"], secret_id="sec1",
                  external_subscription_id="ext-9",
                  operator_approved=True)
    body = b'{"event_id":"e1"}'
    ts = str(int(bridge.clock()))
    signature = "v0=" + hmac_module.new(
        b"s3cr3t", f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    first = bridge.ingest(subscription_id="sub1", event_id="e1",
                          sender="U123", sender_workspace="ws-team",
                          payload={"text": "hi"}, raw_body=body,
                          signature=signature, timestamp=ts)
    assert first["status"] == "ADMITTED"
    second = bridge.ingest(subscription_id="sub1", event_id="e1",
                           sender="U123", sender_workspace="ws-team",
                           payload={"text": "hi"}, raw_body=body,
                           signature=signature, timestamp=ts)
    assert second["status"] == "REUSED"
    with pytest.raises(ChannelDenied):
        bridge.ingest(subscription_id="sub1", event_id="e2",
                      sender="intruder", sender_workspace="ws-team",
                      payload={"text": "hi"}, raw_body=body,
                      signature=signature, timestamp=ts)
    disabled = bridge.disable(owner="o", subscription_id="sub1",
                              operator_approved=True)
    assert disabled["removal_receipt"]["removed"] is True
    revoked = bridge.revoke(owner="o", subscription_id="sub1",
                            operator_approved=True)
    assert revoked["state"] == "REVOKED"
    assert revoked["secret_purged"] is True


def test_channel_outbound_two_stage_receipt(tmp_path):
    from pulso_test_authority import make_authority
    from sentra_runtime.contracts import OperationRequest
    from sentra_interop.workflow_contracts import digest
    bridge = _bridge(tmp_path)
    bridge.enable(owner="o", subscription_id="sub1", channel="telegram",
                  project_id="ws1", allow_workspaces=["ws-team"],
                  allow_users=["U123"], secret_id="sec1",
                  operator_approved=True)
    staged = bridge.stage_notification(
        owner="o", subscription_id="sub1", recipient="U123",
        payload={"text": "digest ready"}, dedupe_key="ntfy-0001")
    assert staged["state"] == "STAGED"
    with pytest.raises(ChannelDenied, match="admitted"):
        asyncio.run(bridge.send_staged(dedupe_key="ntfy-0001"))
    bridge.bind_sender(owner="o", subscription_id="sub1", connector_id="tg1", operator_approved=True)
    authority = make_authority(tmp_path / "central", "channel:send", owner="o")
    async def provider(request):
        return await bridge.send_staged(dedupe_key="ntfy-0001")
    authority.bind_provider("channel:send", provider)
    request = OperationRequest("op-send", "agent1", "machine1", "channel:send", "wi1", "send-0001",
        {"connector_id":"tg1", "recipient":"U123", "text_sha256":digest("digest ready")})
    try:
        result = asyncio.run(authority.start(request))
        assert result.state == "SUCCEEDED", result
        sent = result.evidence["payload"]
    finally:
        authority.control.durable.close()
    assert sent["state"] == "SENT"
    assert sent["delivered"] is False
    with pytest.raises(ChannelDenied):
        bridge.mark_delivered(dedupe_key="missing", receipt_id="r1")
    receipt = {"provider_receipt":{"external_message_id":"pm-1"}}
    bridge.channel_service = SimpleNamespace(owner="o", owner_receipt=lambda **kwargs: receipt)
    bridge.note_provider_ack(owner="o", dedupe_key="ntfy-0001", operation_id="op-send")
    with pytest.raises(ChannelDenied, match="provider ACK is insufficient"):
        bridge.mark_delivered(dedupe_key="ntfy-0001", receipt_id="op-send")
    receipt["recipient_receipt"] = {"status":"delivered"}
    delivered = bridge.mark_delivered(dedupe_key="ntfy-0001", receipt_id="op-send")
    assert delivered["state"] == "DELIVERED"
    assert delivered["receipt_id"] == "op-send"


# -- timezone scheduling -------------------------------------------------
def test_tz_cron_matches_utc_equivalent():
    spec = {"cron": "0 12 * * *", "timezone": "UTC"}
    after = datetime(2026, 1, 4, 10, 0, tzinfo=timezone.utc).timestamp()
    due = RoutineScheduleTZ.next_due(spec, after)
    assert datetime.fromtimestamp(due, tz=timezone.utc).hour == 12


def test_tz_cron_sao_paulo_offset():
    spec = {"cron": "0 9 * * *", "timezone": "America/Sao_Paulo"}
    after = datetime(2026, 1, 4, 10, 0, tzinfo=timezone.utc).timestamp()
    due = RoutineScheduleTZ.next_due(spec, after)
    from zoneinfo import ZoneInfo
    local = datetime.fromtimestamp(due, tz=ZoneInfo("America/Sao_Paulo"))
    assert (local.hour, local.minute) == (9, 0)


def test_tz_unknown_zone_fails_explicitly():
    with pytest.raises(ValueError, match="unknown timezone"):
        RoutineScheduleTZ.next_due(
            {"cron": "* * * * *", "timezone": "Mars/Olympus"}, 0.0)


def test_calendar_exclusions_skip():
    from zoneinfo import ZoneInfo
    spec = {"cron": "0 9 * * *", "timezone": "America/Sao_Paulo",
            "calendar_exclusions": ["2026-01-05"]}
    after = datetime(2026, 1, 4, 13, 0, tzinfo=timezone.utc).timestamp()
    due = RoutineScheduleTZ.next_due(spec, after)
    local = datetime.fromtimestamp(due, tz=ZoneInfo("America/Sao_Paulo"))
    assert local.date().isoformat() == "2026-01-06"


def test_after_completion_single_occurrence():
    spec = {"every_after_completion_seconds": 3600}
    assert RoutineScheduleTZ.occurrences_until(spec, 1000.0, 99999.0,
                                              limit=5) == [1000.0]
    assert RoutineScheduleTZ.next_due_after_completion(spec, 1000.0, 0.0) == 4600.0


# -- terminal GC -----------------------------------------------------------
def test_conpty_gc_plan_review_only(tmp_path):
    import sqlite3
    from contextlib import contextmanager
    from sentra_executors.conpty_sessions import PersistentConPTYLedger

    path = str(tmp_path / "ctrl.sqlite3")

    def connect(name):
        assert name == "execution_workspace"
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    control = SimpleNamespace(store=SimpleNamespace(connect=connect))
    ledger = PersistentConPTYLedger(control)
    ledger.register("o", workspace_id="ws", terminal_id="t1", run_id="r",
                    work_item_id="w", principal_id="a", name="main",
                    shell="powershell")
    plan = ledger.gc_plan("o", "ws", idle_before=ledger.clock() + 1)
    assert len(plan["candidates"]) == 1
    assert plan["candidates"][0]["may_close_process"] is False
    assert plan["destructive_actions_executed"] == 0
    assert plan["gc_supported_for_unknown_handle"] is False


# -- sender binding + gate -------------------------------------------------
def test_channel_resolve_send_server_side(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.enable(owner="o", subscription_id="sub1", channel="telegram",
                  project_id="ws1", allow_workspaces=["ws-team"],
                  allow_users=["U123"], secret_id="sec1",
                  operator_approved=True)
    bridge.bind_sender(owner="o", subscription_id="sub1",
                       connector_id="tg-connector-1", operator_approved=True)
    bridge.stage_notification(owner="o", subscription_id="sub1",
                              recipient="U123",
                              payload={"text": "digest ready"},
                              dedupe_key="ntfy-0002")
    resolved = bridge.resolve_send("o", "ntfy-0002")
    assert resolved == {"connector_id": "tg-connector-1",
                        "recipient": "U123", "text": "digest ready",
                        "subscription_id": "sub1", "dedupe_key": "ntfy-0002"}
    with pytest.raises(PermissionError, match="another owner"):
        bridge.resolve_send("someone-else", "ntfy-0002")


def test_terminal_write_gate_fenced(tmp_path):
    import hashlib
    import sqlite3
    from contextlib import contextmanager
    from sentra_executors.conpty_sessions import (
        PersistentConPTYLedger, TerminalWriteGate)

    path = str(tmp_path / "ctrl.sqlite3")

    def connect(name):
        assert name == "execution_workspace"
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    control = SimpleNamespace(store=SimpleNamespace(connect=connect))
    canvas = SimpleNamespace(store=SimpleNamespace(
        principal="vitor",
        workspace=lambda ws: {"owner": "vitor", "path": str(tmp_path)},
        resource=lambda *args: {}))
    PersistentConPTYLedger(control).register(
        "canvas:vitor", workspace_id="ws1", terminal_id="t1", run_id="run1",
        work_item_id="wi1", principal_id="agent1", name="main",
        shell="powershell")
    gate = TerminalWriteGate(control=control, canvas=canvas)
    fenced = gate.request("canvas:vitor", workspace_id="ws1",
                          terminal_id="t1", data="ls\n", principal="vitor")
    assert fenced["capability_id"] == "terminal:write"
    from sentra_executors.conpty_sessions import text_digest
    assert fenced["arguments"]["payload_sha256"] == text_digest("ls\n")
    assert fenced["scope"]["run_id"] == "run1"
    assert fenced["effects_started"] is False
    with pytest.raises(PermissionError):
        gate.execute(request=SimpleNamespace(
            capability_id="terminal:write", arguments=fenced["arguments"]),
            data="ls\n", owner="canvas:vitor", run_id="run1",
            work_item_id="wi1", principal_id="agent1", workspace_id="ws1",
            terminal_id="t1", principal="vitor")


# -- policy store ----------------------------------------------------------
def test_policy_pause_and_cost_gate(tmp_path):
    import sqlite3
    from contextlib import contextmanager

    path = str(tmp_path / "gov.sqlite3")

    def connect():
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    store = RoutinePolicyStore(connect)
    routine = {"routine_id": "r1", "owner": "o",
               "metadata": {"_pulso_cost_cap_usd": 1.0,
                            "_pulso_max_consecutive_failures": 2}}
    assert store.check_before_fire(routine) is None
    store.note_completion("r1", "o", terminal_state="FAILED", cost_usd=0.4)
    store.note_completion("r1", "o", terminal_state="FAILED", cost_usd=0.4)
    state = store.get("r1")
    assert state["consecutive_failures"] == 2
    store.note_completion("r1", "o", terminal_state="FAILED", cost_usd=0.4)
    assert "cost cap reached" in (store.check_before_fire(routine) or "")
