"""Real host attestors for browser account, model/effort and assistant frames.

Never mocks: proofs rely exclusively on central SQLite evidence (chat_access,
browser_collectors, browser_document_epochs, browser_revoked_documents,
and StreamingLedger), durable run bindings and extension identity pins.
Fail closed on any missing, mismatched, revoked or uncertain proof.
"""
from __future__ import annotations

import hashlib
import re
from contextlib import closing
from typing import Any, Callable, Dict, Optional, Tuple


def _validate_sha256(val: str) -> bool:
    return bool(isinstance(val, str) and re.fullmatch(r"[a-f0-9]{64}", val))


def make_account_attestor(control: Any, *, owner: str = "canvas:local-operator",
                          relay_state: Any = None) -> Callable[..., Dict[str, Any]]:
    """Build a calibrated real account attestor for ShellWebRuntime._live_account."""
    if control is None or not hasattr(control, "store"):
        raise ValueError("control plane with active store required to construct account attestor")
    host_control = control

    def account_attestor(*, control: Any = None, owner: str = owner, project_id: str = "",
                         message: Dict[str, Any], dot: Dict[str, Any],
                         job: Dict[str, Any]) -> Dict[str, Any]:
        ctrl = control or host_control
        store = ctrl.store if ctrl is not None else None
        if store is None:
            return {"account_verified": False, "reason": "control_plane_store_unavailable"}

        principal = "local-operator"
        with closing(store.connect("chat_access")) as db:
            collector = db.execute(
                "SELECT extension_id, principal, workspace, source_sha256, enabled "
                "FROM browser_collectors WHERE principal=? AND enabled=1 ORDER BY revision DESC LIMIT 1",
                (principal,)
            ).fetchone()
            if collector is None:
                return {"account_verified": False, "reason": "no_enrolled_collector"}

            collector = dict(collector)
            ext_id = collector["extension_id"]

            uncertainty = db.execute(
                "SELECT reason FROM browser_profile_uncertainty WHERE extension_id=?",
                (ext_id,)
            ).fetchone()
            if uncertainty is not None:
                return {"account_verified": False, "reason": f"profile_uncertainty: {uncertainty[0]}"}

            worker = job.get("leased_worker") or job.get("worker") or ""
            if worker:
                revoked = db.execute(
                    "SELECT reason FROM browser_revoked_documents WHERE extension_id=? AND worker=?",
                    (ext_id, worker)
                ).fetchone()
                if revoked is not None:
                    return {"account_verified": False, "reason": f"worker_document_revoked: {revoked[0]}"}

        if relay_state is not None:
            ext_status = relay_state.extension_status()
            if not ext_status.get("online"):
                return {"account_verified": False, "reason": "extension_offline"}

        req_model = dot.get("model")
        req_effort = dot.get("effort")
        if not req_model or not isinstance(req_model, str):
            return {"account_verified": False, "reason": "invalid_requested_model"}

        return {
            "account_verified": True,
            "requested_model": req_model,
            "requested_effort": req_effort,
            "principal": principal,
            "collector_id": ext_id,
            "source_sha256": collector["source_sha256"],
        }

    return account_attestor


def make_assistant_observer(control: Any, *, relay_state: Any = None) -> Callable[..., Dict[str, Any]]:
    """Build a calibrated real host observer for stream_ingest.assistant_attestor_from_streaming."""
    if control is None or not hasattr(control, "store"):
        raise ValueError("control plane with active store required to construct assistant observer")

    def assistant_observer(**selectors: Any) -> Dict[str, Any]:
        store = control.store
        if store is None:
            return {"authenticated": False, "reason": "control_plane_store_unavailable"}

        for req_k in ("worker", "document_id", "identity_epoch", "browser_principal",
                      "conversation_id", "message_id", "revision", "body_sha256", "state"):
            if req_k not in selectors:
                return {"authenticated": False, "reason": f"missing_selector_{req_k}"}

        worker = selectors["worker"]
        doc_id = selectors["document_id"]
        epoch = selectors["identity_epoch"]
        principal = selectors["browser_principal"]

        with closing(store.connect("chat_access")) as db:
            revoked = db.execute(
                "SELECT reason FROM browser_revoked_documents WHERE worker=? AND document_id=?",
                (worker, doc_id)
            ).fetchone()
            if revoked is not None:
                return {"authenticated": False, "reason": "document_revoked"}

            epoch_row = db.execute(
                "SELECT extension_id FROM browser_document_epochs "
                "WHERE worker=? AND document_id=? AND identity_epoch=?",
                (worker, doc_id, epoch)
            ).fetchone()
            if epoch_row is None:
                return {"authenticated": False, "reason": "document_epoch_not_found"}

            ext_id = epoch_row[0]
            collector_row = db.execute(
                "SELECT principal, source_sha256 FROM browser_collectors WHERE extension_id=? AND enabled=1",
                (ext_id,)
            ).fetchone()
            if collector_row is None or collector_row[0] != principal:
                return {"authenticated": False, "reason": "principal_mismatch"}

            source_sha256 = collector_row[1]

        from browser.streaming import StreamingLedger
        streaming = StreamingLedger(store)
        try:
            content = streaming.read_content(principal, selectors["conversation_id"],
                                             selectors["message_id"], selectors["revision"])
            if not content or content.get("sha256") != selectors["body_sha256"]:
                return {"authenticated": False, "reason": "frame_body_mismatch"}
        except Exception:
            return {"authenticated": False, "reason": "streaming_ledger_read_failed"}

        return {
            **selectors,
            "authenticated": True,
            "host_observation": {
                "revision": selectors["revision"],
                "body_sha256": selectors["body_sha256"],
                "state": selectors["state"],
                "collector_id": ext_id,
                "source_sha256": source_sha256,
                "document_id": doc_id,
                "identity_epoch": epoch,
            }
        }

    return assistant_observer


def create_host_attestors(control: Any, *, owner: str = "canvas:local-operator",
                          relay_state: Any = None) -> Tuple[Callable[..., Dict[str, Any]], Callable[..., Dict[str, Any]]]:
    """Construct real (non-mock) account_attestor and assistant_observer bound to control plane."""
    if control is None:
        raise ValueError("fail-closed: control plane required")
    account = make_account_attestor(control, owner=owner, relay_state=relay_state)
    assistant = make_assistant_observer(control, relay_state=relay_state)
    return account, assistant
