"""Host-only Web MCP dispatch proof before central tool side effects.

The transport/broker supplies authenticated identity *outside MCP arguments*
via a host-implemented callback. HTTP headers alone are never proof.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sentra_mcp.identity import _principal_binding
from .browser_evidence import BrowserEvidenceService
from .chat_access import ChatAccessService, _ID, _PRINCIPAL, _validate


@dataclass(frozen=True)
class AuthenticatedWebLink:
    """Created ONLY by trusted authenticated connector/relay ingress.

    Account identity cannot be proven from this object. An enrolled
    extension/page observation is not account attestation.
    """
    principal: str
    request_id: str
    message_id: str
    extension_id: str
    worker: str
    document_id: str
    identity_epoch: str | None = None


class WebMCPMessageDispatchGuard:
    """Plug into ToolPolicyProxy(request_observer=guard.tool_observer).

    This callback is run after ChatAccess.require_allowed, but before the
    registered MCP function and before its central authorization/effect.
    Ingress *must* validate extension origin, source build, bearer, and
    actual connector call and create AuthenticatedWebLink on the HOST.
    """

    def __init__(self, *, chat_access: ChatAccessService,
                 browser_evidence: BrowserEvidenceService,
                 authenticated_link: Callable[[object], AuthenticatedWebLink | None],
                 verified_account: Callable[[object, AuthenticatedWebLink, str], bool] | None = None):
        if not callable(authenticated_link):
            raise TypeError("trusted connector correlation callback required")
        if verified_account is not None and not callable(verified_account):
            raise TypeError("verified account source must be a host callback")
        self.chat_access = chat_access
        self.browser_evidence = browser_evidence
        self.authenticated_link = authenticated_link
        # MUST be a local, host-attested current browser profile/account binding;
        # an enrolled extension, DOM text, route, login button or model label
        # alone is not account proof. Absent => deny every Web tool.
        self.verified_account = verified_account

    def tool_observer(self, context, name):
        if context is None or not isinstance(name, str) or not name:
            raise PermissionError("Web MCP identity missing at tool dispatch")
        verified = self.authenticated_link(context)
        if not isinstance(verified, AuthenticatedWebLink):
            raise PermissionError("Web MCP call has no authenticated broker binding")
        for label, value, pattern in (
            ("principal",verified.principal,_PRINCIPAL),
            ("request",verified.request_id,_ID),
            ("message",verified.message_id,_ID),
            ("document",verified.document_id,_ID)):
            _validate(label,value,pattern)
        try:
            request = context.request_context.request
            headers = request.headers
            inbound_id = headers.get("x-request-id")
        except (AttributeError, RuntimeError, TypeError):
            raise PermissionError("Web MCP request header unavailable") from None
        if (_principal_binding(context) != verified.principal
                or inbound_id != verified.request_id):
            raise PermissionError("Web MCP authenticated request/transport mismatch")
        if (not isinstance(verified.extension_id,str)
                or not isinstance(verified.worker,str)):
            raise PermissionError("Web MCP extension binding missing")
        with self.chat_access._db() as db:
            db.execute("BEGIN IMMEDIATE")
            allowed=self.chat_access.require_exact_message(
                verified.principal,verified.request_id,verified.message_id,_db=db)
            if allowed.get("source")!="proven":
                raise PermissionError("Web MCP request lacks enrolled page evidence")
            row=db.execute(
                "SELECT extension_id,worker,document_id FROM browser_request_messages "
                "WHERE principal=? AND request_id=?",
                (verified.principal,verified.request_id)).fetchone()
            if (row is None or (row["extension_id"],row["worker"],row["document_id"]) !=
                    (verified.extension_id,verified.worker,verified.document_id)):
                raise PermissionError("Web MCP tab/document/extension binding mismatch")
            bound=db.execute(
                "SELECT identity_epoch FROM browser_document_epochs "
                "WHERE extension_id=? AND worker=? AND document_id=?",
                (verified.extension_id,verified.worker,verified.document_id)
            ).fetchone()
            if bound and bound["identity_epoch"] != verified.identity_epoch:
                raise PermissionError("Web MCP identity epoch mismatch")
            if verified.identity_epoch is not None and not bound:
                raise PermissionError("Web MCP unbound identity epoch")
            self.browser_evidence.require_dispatch_ready(
                verified.principal,allowed["conversation_id"])
            if (self.verified_account is None or
                    self.verified_account(context,verified,allowed["conversation_id"]) is not True):
                raise PermissionError("Web MCP account identity unverified by trusted host")
        # Never creates an Operation or a grant. The original decorated tool
        # must still pass the central grant and durable gate.
        return {"allowed":True,"tool_name":name,
                "conversation_id":allowed["conversation_id"],
                "message_id":verified.message_id,
                "account_identity":"attested_by_host",
                "grants_created":False}


@dataclass(frozen=True)
class HostWebReceiptRef:
    """Opaque authenticated host routing decision, NEVER an MCP argument.

    The trusted host ingress resolves owner/run/job independently of request
    headers or model tool arguments. The SQLite receipt is authoritative.
    """
    owner: str
    run_id: str
    job_id: str


def guard_from_durable_web_receipts(*, control,
                                    host_receipt_ref: Callable[[object], HostWebReceiptRef | None],
                                    verified_account: Callable[[object, AuthenticatedWebLink, str], bool] | None = None):
    """Factory for the coordinator's ToolPolicyProxy(request_observer=...).

    A HostWebReceiptRef is supplied by the HOST's private authenticated
    request/job correlation, NOT by the model, URL, DOM or x-request-id.
    Looks up a previously attested receipt in the SAME central SQLite,
    reconstructs the bound extension/document/epoch, and uses the existing
    WebMCPMessageDispatchGuard. With no independent account attestor the guard
    remains DENY-ALL for account-sensitive Web calls.
    """
    if not callable(host_receipt_ref):
        raise TypeError("authenticated host receipt lookup callback required")

    def resolve(context):
        from sqlite3 import OperationalError

        ref = host_receipt_ref(context)
        if type(ref) is not HostWebReceiptRef:
            raise PermissionError("Web MCP request has no authenticated host job")
        for label, value in (("owner", ref.owner), ("run", ref.run_id),
                             ("job", ref.job_id)):
            _validate(label, value, _PRINCIPAL if label == "owner" else _ID)
        try:
            run = control.durable.run_status(ref.run_id, ref.owner, include_details=False)
            with control.session_checkpoints.store.connect("session_checkpoint") as db:
                receipt = db.execute(
                    "SELECT browser_principal,request_id,worker,message_id,"
                    "conversation_id,identity_epoch,workspace FROM authenticated_web_receipts "
                    "WHERE job_id=? AND owner=? AND run_id=?",
                    (ref.job_id, ref.owner, ref.run_id)).fetchone()
            if receipt is None or not run.get("workspace") or (
                    receipt["workspace"] != run["workspace"]):
                raise PermissionError("Web MCP host receipt is absent or wrong workspace")
            with control.session_checkpoints.store.connect("chat_access") as db:
                proofs = db.execute(
                    "SELECT m.extension_id,m.worker,m.document_id,ep.identity_epoch "
                    "FROM browser_request_messages m JOIN browser_document_epochs ep "
                    "ON ep.extension_id=m.extension_id AND ep.worker=m.worker "
                    "AND ep.document_id=m.document_id "
                    "WHERE m.principal=? AND m.request_id=? AND m.message_id=?",
                    (receipt["browser_principal"],receipt["request_id"],
                     receipt["message_id"])).fetchall()
            if len(proofs) != 1 or (
                    proofs[0]["worker"] != receipt["worker"]) or (
                    proofs[0]["identity_epoch"] != receipt["identity_epoch"]):
                raise PermissionError("Web MCP host receipt lost unique V2 document")
        except (KeyError, OperationalError) as exc:
            raise PermissionError("Web MCP authenticated host proof unavailable") from exc
        return AuthenticatedWebLink(
            principal=receipt["browser_principal"],
            request_id=receipt["request_id"], message_id=receipt["message_id"],
            extension_id=proofs[0]["extension_id"], worker=receipt["worker"],
            document_id=proofs[0]["document_id"],
            identity_epoch=proofs[0]["identity_epoch"])

    return WebMCPMessageDispatchGuard(
        chat_access=control.chat_access,
        browser_evidence=control.browser_evidence,
        authenticated_link=resolve,
        verified_account=verified_account)


def verified_account_from_catalog(control, *, provider: str = "chatgpt",
                                  max_age_s: float = 600.0):
    """Build the host `verified_account` callback from Brisa's catalog.

    Returns True only when `BrowserEvidenceService.account_catalog_status`
    reports a fresh verified catalog for the same principal/provider AND
    the dispatched conversation matches the attested binding. Anything
    else (missing/stale/unverified catalog, import failure) denies: with
    no independent account attestor the guard remains DENY-ALL, which is
    the correct closed state, not a capacity.
    """
    if provider not in {"chatgpt", "gemini"}:
        raise ValueError("catalog provider must be chatgpt or gemini")

    def check(context, link, conversation_id: str) -> bool:
        try:
            status = control.browser_evidence.account_catalog_status(
                link.principal, provider, max_age_s=max_age_s)
        except (AttributeError, ValueError, OSError):
            return False
        if not isinstance(status, dict) or status.get("verified") is not True:
            return False
        try:
            with control.session_checkpoints.store.connect("chat_access") as db:
                row = db.execute(
                    "SELECT conversation_id FROM browser_request_messages "
                    "WHERE principal=? AND request_id=?",
                    (link.principal, link.request_id)).fetchone()
        except (OSError, ValueError):
            return False
        return row is not None and row["conversation_id"] == conversation_id

    return check
