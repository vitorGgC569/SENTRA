"""Host boot + shell/CLI projections for Rastro continuity/outbox (Rastro).

Central composition (bridge routes, CLI commands, boot sequence) belongs to
Codex/Nexo/Vitra and is NOT edited here. This module exposes the pure
host-side entry points they compose:

- `boot_recovery(control, jobs, owner)`: observation-only crash recovery
  over outbox, continuations and WebSend intents for host startup. Never
  sends, rebinds or resends; returns operator action items.
- `shell_projection(...)` / `cli_status(...)`: JSON-safe read models for
  the shell bridge (`conversation_list`, `message_list`, delivery views),
  the CLI `/model` + `/resume` surfaces and the gateway account view.
  Every projection carries `automatic_resend: False` and explicit
  freshness; absence of configuration is reported as
  `status: unavailable|<reason>`, never as invented data.

Wire-up request for Codex (central files untouched by Rastro):
- call `boot_recovery` during host startup and surface
  `requires_operator_reconciliation` items in Doctor/shell home;
- serve `shell_projection` through `POST /api/shell/bridge` actions
  (`conversation_list`, `message_list`, outbox/delivery views) and
  `cli_status` through `sentra_cli/repl.py /model|/resume`;
- inject Brisa attestors via `attach_attestors` (account + assistant) so
  `DurableWebTransport` and `WebSendAuthority` stop failing closed.
"""
from __future__ import annotations

from typing import Any


def boot_recovery(control: Any, jobs: Any, owner: str) -> dict[str, Any]:
    from native_bridge.outbox_recovery import (
        recover_continuations, recover_outbox, recover_web_sends)
    outbox = recover_outbox(jobs, control=control)
    continuations = recover_continuations(control, owner)
    sends = recover_web_sends(control, jobs, owner)
    needs_operator = (
        [item for item in outbox["jobs"] if item["requires_operator_reconciliation"]]
        + [item for item in continuations["open"]
           if item["requires_operator_reconciliation"]]
        + [item for item in sends["intents"]
           if item["requires_operator_reconciliation"]])
    return {"owner": owner, "outbox": outbox, "continuations": continuations,
            "web_sends": sends,
            "requires_operator_reconciliation": bool(needs_operator),
            "operator_items": needs_operator, "automatic_resend": False}


def attach_attestors(*, web_transport=None, web_send=None,
                     control=None, streaming=None, host_observer=None) -> dict[str, bool]:
    """Plug real Brisa-backed attestors into Rastro transports.

    - account: HostAccountAttestor reads the same enrolled Electron Host live,
      checks reviewed account/profile/source and the original pinned request.
    - assistant: an independent SERVER-SELECTED host observer plus exact
      original receipt and protected FULL streaming content. Ledger is data.
    Returns which slots were actually populated; unpopulated slots keep
    failing closed (DENY), which is correct, not a capacity.
    """
    from native_bridge.stream_ingest import assistant_attestor_from_streaming
    attached: dict[str, bool] = {"account": False, "assistant": False}
    if web_send is not None and streaming is not None and control is not None and callable(host_observer):
        web_send.assistant_attestor = assistant_attestor_from_streaming(
            control, streaming, host_observer=host_observer)
        attached["assistant"] = True
    if web_transport is not None and control is not None:
        from sentra_model_gateway.account_attestation import HostAccountAttestor
        web_transport.account_attestor = HostAccountAttestor(control)
        attached["account"] = True
    return attached


def shell_projection(control: Any, jobs: Any, owner: str, workspace: str, *,
                     conversation_id: str | None = None,
                     limit: int = 50) -> dict[str, Any]:
    """Read-only shell home inputs owned by Rastro (history + outbox + usage)."""
    from sentra_mcp.services.web_history_store import WebHistoryStore
    history = WebHistoryStore(control.durable.state_root, store=control.store)
    conversations = history.list_observed_conversations(
        owner, workspace, limit=limit)
    messages = (history.messages(owner, workspace, conversation_id, limit=100)
                if conversation_id else [])
    return {"conversations": conversations, "messages": messages,
            "outbox": boot_recovery(control, jobs, owner)["outbox"],
            "quota_note": "ChatGPT-observed limits are separate from "
                          "SENTRA-accounted usage; query usage_projection per "
                          "account_fingerprint+quota_bucket",
            "automatic_resend": False}


def usage_projection(control: Any, owner: str, workspace: str,
                     *, account_fingerprint: str,
                     quota_bucket: str) -> dict[str, Any]:
    """Side-by-side SENTRA-accounted vs Web-observed usage (never conflated)."""
    from sentra_mcp.services.web_history_usage import WebQuotaObservations
    quota = WebQuotaObservations(control.durable.state_root, store=control.store)
    try:
        # UsageLedger projects conversation outboxes into this SAME governance
        # authority. Read existing reported events here; never create another
        # factory/SQLite ledger or manufacture provider-accounted usage.
        from contextlib import closing
        with closing(control.store.connect("governance")) as db:
            row = db.execute("SELECT COUNT(*) count,COALESCE(SUM(input_tokens),0) input_tokens,"
                "COALESCE(SUM(output_tokens),0) output_tokens,COALESCE(SUM(reasoning_tokens),0) reasoning_tokens,"
                "COALESCE(SUM(actual_cost),0) actual_cost FROM cost_events WHERE owner=? AND workspace=?",
                (owner,workspace)).fetchone()
        accounted = {"status":"reported","workspace":workspace,**dict(row)}
    except (ImportError, OSError, ValueError, AttributeError) as exc:
        accounted = {"status": "unavailable", "reason": "reported_usage_projection_unavailable"}
    observed = quota.latest(owner, workspace, account_fingerprint, quota_bucket)
    return {"sentra_accounted": accounted, "web_observed": observed,
            "equivalent": False, "automatic_resend": False}


def cli_status(gateway_server: Any,
               account_fingerprint: str | None = None) -> dict[str, Any]:
    """Safe `/model` projection for the CLI (no auth material, no inference)."""
    try:
        view = gateway_server.account_model_view(account_fingerprint)
    except (ValueError, RuntimeError, AttributeError) as exc:
        return {"status": "unavailable", "reason": str(exc)[:200],
                "models": [], "automatic_resend": False}
    return {**view, "automatic_resend": False}
