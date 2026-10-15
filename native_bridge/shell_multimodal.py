"""One binary multimodal turn on the centrally fenced ChatGPT relay composer.

All bytes are staged in OS-protected, WorkItem/grant-scoped WebAssetDrafts.
Jobs contain only bounded immutable refs. The enrolled extension retrieves
64KiB chunks using its exact live worker lease, verifies every SHA and performs
one file-upload gesture and one Send. PDF/text/image files are transmitted whole.
No chunk truncation, inline text export, repeated prompt or automatic split.
Admission/storage is not upload: exact message+binary-set receipt and central
browser attestation are required. External upstream transport remains separate
and fails explicitly for binary refs until its composer path is configured.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

_IDENT = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
_OWNER = re.compile(r"^[^\x00-\x1f]{1,128}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_MIMES = {"image/png", "image/jpeg"}
_TEXT_MIMES = {"text/plain"}
_PDF_MIME = "application/pdf"
_CHUNK = 64 * 1024
_MAX_TEXT_CHARS = 20000
_MAX_PDF_PAGES = 20
_MAX_PDF_CHARS = 20000


def _bounded(label: str, value: str, pattern) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{label} requires a stable bounded identifier")
    return value


def _pre_send_message_id(owner: str, request_identity: str, index: int) -> str:
    """Stable pre-send correlation id for draft scope (receipt is the truth)."""
    digest = hashlib.sha256(
        (owner + "\x00" + request_identity + "\x00" + str(index)).encode()
    ).hexdigest()[:32]
    return "pending-" + digest


def dispatch_shell_turn(control: Any, jobs: Any, drafts: Any, web: Any, *,
                        owner: str, run_id: str, work_item_id: str,
                        operation_id: str, principal_id: str, grant_id: str,
                        workspace: str, project_id: str | None = None,
                        space_id: str | None = None, conversation_id: str,
                        conversation_url: str | None = None,
                        request_identity: str, prompt: str,
                        attachments: list[dict[str, Any]],
                        operator_approved: bool = False,
                        timeout_s: int = 180, requested_model: str | None = None,
                        requested_effort: str | None = None) -> dict[str, Any]:
    """Stage Brisa-resolved attachments and admit ONE multimodal turn.

    `attachments` items: Brisa `validate_attachments` rows plus `data` bytes
    from owner-checked `read_bytes`
    ({attachment_id, kind, name, mime, bytes, sha256, data}).
    Returns the single intent (job id), scoped refs and evidence;
    `web_uploaded` is always False here — the set receipt arrives via
    `attachment_transport.receipt_status` per asset (same job/receipt).
    """
    if operator_approved is not True:
        raise PermissionError("human consent required to dispatch attachments")
    if not isinstance(request_identity, str) or not 1 <= len(request_identity) <= 8192:
        raise ValueError("bounded stable request_identity required")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt text required")
    _bounded("owner", owner, _OWNER)
    _bounded("conversation", conversation_id, _IDENT)
    if not isinstance(attachments, list) or len(attachments) > 4:
        raise ValueError("attachments must be a list of 0..4 resolved items")
    # Full files travel through the binary composer. No PDF/text truncation,
    # inline expansion, image split or repeated prompt is permitted.
    validated = []
    for position, item in enumerate(attachments):
        if not isinstance(item, dict):
            raise ValueError("attachment must be a resolved descriptor")
        data, mime = item.get("data"), item.get("mime")
        maximum = 8 * 1024 * 1024 if mime in _IMAGE_MIMES else 20 * 1024 * 1024
        if (mime not in (_IMAGE_MIMES | _TEXT_MIMES | {_PDF_MIME}) or not isinstance(data, bytes)
                or not 1 <= len(data) <= maximum or len(data) != item.get("bytes")
                or hashlib.sha256(data).hexdigest() != item.get("sha256")):
            raise PermissionError("attachment bytes/type/digest/size differ from admitted scope")
        validated.append(item)
    asset_ids, file_refs = [], []
    for position, item in enumerate(validated):
        data, mime = item["data"], item["mime"]
        stage_key = hashlib.sha256((request_identity + ":" + str(position)).encode()).hexdigest()
        asset = drafts.begin(owner, run_id=run_id, work_item_id=work_item_id,
            principal_id=principal_id, conversation_id=conversation_id,
            message_id=_pre_send_message_id(owner, request_identity, position),
            content_type=mime, expected_bytes=len(data), expected_sha256=item["sha256"],
            request_key="binary-stage:" + stage_key, operator_approved=True)
        asset_id = asset["asset_id"]
        if asset["state"] == "RECEIVING":
            for offset in range(0, len(data), _CHUNK):
                drafts.put_chunk(owner, asset_id, part=offset // _CHUNK, content=data[offset:offset + _CHUNK])
            drafts.finish(owner, asset_id)
        elif asset["state"] != "READY_LOCAL":
            raise PermissionError("staged attachment requires reconciliation")
        suffix = {"image/png": "png", "image/jpeg": "jpg", "application/pdf": "pdf", "text/plain": "txt"}[mime]
        file_refs.append({"asset_id": asset_id, "name": "sentra-" + asset_id.removeprefix("web-asset-") + "." + suffix,
                          "mime": mime, "bytes": len(data), "sha256": item["sha256"]})
        asset_ids.append(asset_id)
    admitted = web.admit(owner, request_identity=request_identity, submission_index=0,
        run_id=run_id, operation_id=operation_id, work_item_id=work_item_id,
        principal_id=principal_id, grant_id=grant_id, workspace=workspace,
        conversation_key="conversation://" + conversation_id, prompt=prompt,
        conversation_url=conversation_url, timeout_s=timeout_s,
        requested_model=requested_model, requested_effort=requested_effort,
        dispatch_mode="relay", attachments=file_refs)
    from .attachment_upload import AttachmentUploads
    if asset_ids:
        AttachmentUploads(control, jobs, drafts).bind_asset_set(owner,
            [(ref["asset_id"], ref["sha256"]) for ref in file_refs], admitted["job_id"])
    intent = {"submission_index": 0, "job_id": admitted["job_id"], "asset_ids": asset_ids,
              "state": admitted.get("state"), "send_fence": admitted.get("send_fence")}
    refs = file_refs
    return {"owner": owner, "run_id": run_id, "operation_id": operation_id,
            "work_item_id": work_item_id, "request_identity_sha256":
                hashlib.sha256(request_identity.encode()).hexdigest(),
            "project_id": project_id, "space_id": space_id,
            "conversation_id": conversation_id, "intent": intent, "refs": refs,
            "evidence": {"attachments": len(asset_ids), "binary_transport": "relay-composer",
                         "bytes": sum(item["bytes"] for item in validated),
                         "sha256": [str(item.get("sha256")) for item in attachments
                                    if isinstance(item, dict)]},
            "web_uploaded": False, "requires_operator_reconciliation": False,
            "automatic_resend": False, "generated_asset_verified": False,
            "admission_status": "ADMITTED", "image_bytes_verified": False}


def project_native_image(verdict):
    """Canvas-facing projection. Admission and an uncertain transfer are not delivery."""
    if not isinstance(verdict, dict):
        raise ValueError("native image verdict required")
    status = verdict.get("status")
    base = {"automatic_resend": False, "generated_asset_verified": False, "success": False, "assets": []}
    if status == "UNCERTAIN_NO_RESEND":
        return {**base, "status": "UNCERTAIN_NO_RESEND", "reason": verdict.get("reason")}
    if status != "VERIFIED" or verdict.get("generated_asset_verified") is not True or verdict.get("success") is not True:
        return {**base, "status": "ADMITTED"}
    assets = verdict.get("assets")
    if not isinstance(assets, list) or not assets:
        return {**base, "status": "ADMITTED"}
    projected = []
    for item in assets:
        if not isinstance(item, dict):
            return {**base, "status": "ADMITTED"}
        mime, count, digest = item.get("mime_type"), item.get("byte_length"), item.get("sha256")
        if (mime not in _IMAGE_MIMES or type(count) is not int or count < 1
                or not isinstance(digest, str) or not _SHA.fullmatch(digest)):
            return {**base, "status": "ADMITTED"}
        projected.append({"asset_id": item.get("asset_id"), "mime_type": mime,
                          "byte_length": count, "sha256": digest})
    return {"status": "VERIFIED", "generated_asset_verified": True, "automatic_resend": False,
            "success": True, "assets": projected,
            "run_id": verdict.get("run_id"), "work_item_id": verdict.get("work_item_id"),
            "operation_id": verdict.get("operation_id")}
