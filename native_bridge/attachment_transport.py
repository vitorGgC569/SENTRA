"""Shell transport facade for Web attachments (Rastro).

The shell bridge (Codex) and the CLI/Gateway multimodal dispatcher never
carry raw bytes: they pass scoped `attachment_ref` values that the bridge
validates (bounded ids + digest + Brisa exact request/message/document/epoch
binding) before the host materializes anything. Upload is proven ONLY by
the exact composer/host-observed delivery receipt (`web_uploaded` requires
a `sent` delivery with matching receipt); `READY_LOCAL`/bound/intent states
are never reported as uploaded.

Real dispatch path (same Operation/WorkItem, before any subprocess acts):

  dispatch_attachment(...) -> WebSendAuthority.admit(..., images=[data-url])
  -> fenced pre_send by the worker -> browser SEND -> exact delivery receipt
  -> authenticated attestation -> answer streaming

The returned value is the durable intent/job status plus the scoped ref.
Receipts are observed later via `receipt_status` / `AttachmentUploads`.
"""
from __future__ import annotations

import re
from typing import Any

_ID = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_OWNER = re.compile(r"^[^\x00-\x1f]{1,128}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _bounded(label: str, value: str, pattern) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{label} requires a stable bounded identifier")
    return value


def attachment_ref(control: Any, drafts: Any, owner: str, asset_id: str) -> dict[str, Any]:
    """Scoped, byte-free reference for bridge/CLI/Gateway payloads."""
    _bounded("owner", owner, _OWNER)
    _bounded("asset", asset_id, _ID)
    item = drafts._row(owner, asset_id)
    status = drafts.status(owner, asset_id)
    run = control._run(item["run_id"], owner)
    return {"asset_id": asset_id, "owner": owner,
            "workspace": run.get("workspace"),
            "run_id": item["run_id"], "work_item_id": item["work_item_id"],
            "principal_id": item["principal_id"],
            "conversation_id": item["conversation_id"],
            "message_id": item["message_id"],
            "content_type": item["content_type"],
            "expected_bytes": item["expected_bytes"],
            "sha256": item["expected_sha256"],
            "state": status["state"],
            "web_uploaded": False, "grants_created": False}


def validate_ref_for_bridge(control: Any, drafts: Any, ref: dict[str, Any], *,
                             browser_principal: str,
                             request_id: str) -> dict[str, Any]:
    """Bridge-side scoped validation combining Rastro + Brisa proofs.

    Checks bounded ref fields, the staged asset (state, digest, WorkItem
    grant liveness) and Brisa's exact request/message/document/epoch binding
    for the same conversation. Returns the ref with `bridge_admitted: True`;
    never returns bytes and never declares an upload.
    """
    from native_bridge.message_identity import resolve_by_request
    if not isinstance(ref, dict):
        raise ValueError("attachment ref must be an object")
    owner = _bounded("owner", ref.get("owner", ""), _OWNER)
    asset_id = _bounded("asset", ref.get("asset_id", ""), _ID)
    for key in ("conversation_id", "message_id"):
        _bounded(key, ref.get(key, ""), _ID)
    if not isinstance(ref.get("sha256"), str) or not _SHA.fullmatch(ref["sha256"]):
        raise ValueError("attachment ref digest required")
    live = attachment_ref(control, drafts, owner, asset_id)
    if (live["sha256"] != ref["sha256"]
            or live["conversation_id"] != ref["conversation_id"]
            or live["message_id"] != ref["message_id"]):
        raise PermissionError("attachment ref does not match staged bytes")
    if live["state"] not in ("RECEIVING", "READY_LOCAL"):
        raise PermissionError("attachment is not dispatchable")
    # Scope: the proven Web request must own the asset's conversation, on the
    # same enrolled document/epoch. DOM order or index never qualifies.
    proven = control.chat_access.require_exact_message(
        browser_principal, request_id, live["message_id"])
    if proven.get("source") != "proven" or proven.get("conversation_id") != live[
            "conversation_id"]:
        raise PermissionError("attachment conversation lacks proven request binding")
    binding = resolve_by_request(control, browser_principal=browser_principal,
                                 request_id=request_id)
    return {**live, "bridge_admitted": True,
            "request_id": request_id, "document_id": binding["document_id"],
            "identity_epoch": binding["identity_epoch"],
            "web_uploaded": False, "grants_created": False}


def dispatch_attachment(control: Any, jobs: Any, drafts: Any, web: Any, *,
                        owner: str, asset_id: str, request_identity: str,
                        run_id: str, operation_id: str, work_item_id: str,
                        principal_id: str, grant_id: str, workspace: str,
                        conversation_key: str, prompt: str,
                        conversation_url: str | None = None,
                        submission_index: int = 0,
                        timeout_s: int = 180) -> dict[str, Any]:
    """REAL multimodal dispatcher callable for CLI/Gateway/shell paths.

    Same Operation/WorkItem fencing as every Web send: authority is checked
    by `WebSendAuthority.admit` (run/op/workitem/grant binding) BEFORE the
    outbox job exists, so no subprocess/worker can act on bytes that were
    never admitted. Staged bytes are materialized into the admitted intent's
    images; the intent digest covers them, so a replay with different bytes
    is a conflict. The composer/host-observed exact receipt remains the only
    upload proof (`receipt_status`).
    """
    from native_bridge.attachment_upload import AttachmentUploads
    _bounded("owner", owner, _OWNER)
    _bounded("asset", asset_id, _ID)
    staged = drafts.status(owner, asset_id)
    if staged["state"] != "READY_LOCAL":
        raise ValueError("attachment is not finalized (READY_LOCAL required)")
    if staged["work_item_id"] != work_item_id:
        raise PermissionError("attachment belongs to another WorkItem")
    uploads = AttachmentUploads(control, jobs, drafts)
    image = uploads.bound_image(owner, asset_id)
    admitted = web.admit(
        owner, request_identity=request_identity, run_id=run_id,
        operation_id=operation_id, work_item_id=work_item_id,
        principal_id=principal_id, grant_id=grant_id, workspace=workspace,
        conversation_key=conversation_key, prompt=prompt,
        conversation_url=conversation_url, submission_index=submission_index,
        timeout_s=timeout_s, images=[image])
    job_id = admitted["job_id"]
    uploads.bind_asset_to_job(owner, asset_id, job_id)
    ref = attachment_ref(control, drafts, owner, asset_id)
    return {"job_id": job_id, "asset_id": asset_id, "ref": ref,
            "state": admitted.get("state"), "send_fence": admitted.get("send_fence"),
            "web_uploaded": False, "requires_operator_reconciliation": bool(
                admitted.get("requires_operator_reconciliation")),
            "automatic_resend": False}


def dispatch_asset_set(control: Any, jobs: Any, drafts: Any, web: Any, *,
                       owner: str, asset_ids: list[str], request_identity: str,
                       run_id: str, operation_id: str, work_item_id: str,
                       principal_id: str, grant_id: str, workspace: str,
                       conversation_key: str, prompt: str,
                       conversation_url: str | None = None,
                       submission_index: int = 0,
                       timeout_s: int = 180) -> dict[str, Any]:
    """ATOMIC multimodal admission: ONE intent carrying the whole set.

    All assets ride a single `WebSendAuthority.admit` (same Operation/
    WorkItem, one fence, one job, one delivery receipt covering the set).
    More images than the composer accepts fail closed HERE with an explicit
    quota error — never an automatic split into N sends (that would fork
    conversational intent inside one Operation). Each asset must already be
    READY_LOCAL in the same WorkItem with an exact digest.
    """
    from native_bridge.attachment_upload import AttachmentUploads
    _bounded("owner", owner, _OWNER)
    if not isinstance(asset_ids, list) or not 1 <= len(asset_ids) <= 2:
        raise ValueError(
            "asset set holds 1..2 images per send (composer quota until the "
            "Brisa composer path expands); larger sets are refused, never split")
    for asset_id in asset_ids:
        _bounded("asset", asset_id, _ID)
    uploads = AttachmentUploads(control, jobs, drafts)
    pairs: list[tuple[str, str]] = []
    images: list[str] = []
    for asset_id in asset_ids:
        staged = drafts.status(owner, asset_id)
        if staged["state"] != "READY_LOCAL":
            raise ValueError("attachment set member is not finalized")
        if staged["work_item_id"] != work_item_id:
            raise PermissionError("attachment set member belongs to another WorkItem")
        images.append(uploads.bound_image(owner, asset_id))
        pairs.append((asset_id, staged["sha256"]))
    admitted = web.admit(
        owner, request_identity=request_identity, run_id=run_id,
        operation_id=operation_id, work_item_id=work_item_id,
        principal_id=principal_id, grant_id=grant_id, workspace=workspace,
        conversation_key=conversation_key, prompt=prompt,
        conversation_url=conversation_url, submission_index=submission_index,
        timeout_s=timeout_s, images=images)
    uploads.bind_asset_set(owner, pairs, admitted["job_id"])
    refs = [attachment_ref(control, drafts, owner, asset_id) for asset_id in asset_ids]
    return {"job_id": admitted["job_id"], "asset_ids": list(asset_ids), "refs": refs,
            "state": admitted.get("state"), "send_fence": admitted.get("send_fence"),
            "web_uploaded": False, "requires_operator_reconciliation": bool(
                admitted.get("requires_operator_reconciliation")),
            "automatic_resend": False}


def receipt_status(control: Any, jobs: Any, drafts: Any, owner: str,
                   asset_id: str) -> dict[str, Any]:
    """Upload truth from the composer/host-observed receipt (never local state)."""
    from native_bridge.attachment_upload import AttachmentUploads
    uploads = AttachmentUploads(control, jobs, drafts)
    return uploads.upload_status(owner, asset_id)


def resolve_ref_for_host(control: Any, drafts: Any, ref: dict[str, Any], *,
                          browser_principal: str,
                          request_id: str) -> bytes:
    """Host-only byte materialization after full bridge+Brisa validation."""
    validated = validate_ref_for_bridge(
        control, drafts, ref, browser_principal=browser_principal,
        request_id=request_id)
    from native_bridge.attachment_upload import AttachmentUploads
    raw = AttachmentUploads(control, None, drafts).read_asset(
        validated["owner"], validated["asset_id"])
    return raw
