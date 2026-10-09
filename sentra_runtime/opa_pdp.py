"""Optional OPA REST policy veto; SENTRA grants remain authoritative.

Connects to a pinned local Open Policy Agent-compatible /v1/data endpoint.
The OPA result can DENY an otherwise granted action, never CREATE a grant.
A real OPA daemon was not installed or used by local protocol tests.
"""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from ._policy_http import LoopbackPolicyHTTP, PolicyTransportUnavailable, PinnedProviderHTTP
from .identity_state import identity_digest
from .contracts import OperationRequest, PolicyDecision


class OPAClient:
    def __init__(self, *, endpoint: str, bearer: str,
                 decision_path: str = "/v1/data/sentra/allow",
                 timeout_s: float = 1.5,allow_remote=False,http=None,
                 active_revision=None,audit_sink=None):
        if decision_path not in {"/v1/data/sentra/allow","/v1/data/sentra/decision"}:
            raise ValueError("OPA decision path must be pinned")
        if decision_path.endswith("/decision") and not callable(active_revision): raise ValueError("revisioned decision requires trusted active revision reader")
        self.http = http or (PinnedProviderHTTP(base=endpoint,token=bearer,enabled=True,timeout_s=timeout_s) if allow_remote else
            LoopbackPolicyHTTP(base=endpoint, token=bearer,timeout_s=timeout_s))
        self.decision_path = decision_path
        self.active_revision,self.audit_sink=active_revision,audit_sink

    def allows(self, *, request: OperationRequest, workspace_id: str) -> bool:
        return self.decide(request=request,workspace_id=workspace_id).allowed

    def decide(self,*,request,workspace_id):
        if (not isinstance(request, OperationRequest)
                or not isinstance(workspace_id, str)
                or not 0 < len(workspace_id) <= 128):
            raise ValueError("trusted scoped request required")
        revision_before=self.active_revision() if self.active_revision else None
        response = self.http.post(self.decision_path, {"input": {
            "principal": request.principal_id,
            "machine": request.machine_id,
            "capability": request.capability_id,
            "work_item": request.work_item_id,
            "workspace": workspace_id,
        }})
        if set(response) - {"result", "decision_id"}:
            raise PolicyTransportUnavailable("unrecognized OPA policy output")
        decision_id=response.get("decision_id")
        if decision_id is not None and (not isinstance(decision_id,str) or not 1<=len(decision_id)<=128): raise PolicyTransportUnavailable("invalid OPA decision ID")
        result=response.get("result")
        revision=None
        if self.decision_path.endswith("/decision"):
            if not isinstance(result,dict) or set(result)-{"allow","revision","reason_code"} or type(result.get("allow")) is not bool:
                raise PolicyTransportUnavailable("revisioned OPA decision undefined/malformed")
            revision=result.get("revision")
            if not isinstance(revision,str) or not revision or revision!=revision_before or revision!=self.active_revision():
                raise PolicyTransportUnavailable("OPA bundle revision changed/not activated")
            allowed=result["allow"]
        else:
            if type(result) is not bool: raise PolicyTransportUnavailable("OPA boolean result required")
            allowed=result
        decision=OPADecision(allowed,revision,decision_id)
        if callable(self.audit_sink):
            # Never log raw input, arbitrary provider reason, tokens or args.
            self.audit_sink({"provider":"opa","allowed":allowed,"revision":revision,"decision_id":decision_id,
                "principal_sha256":identity_digest(request.principal_id),"machine_sha256":identity_digest(request.machine_id),
                "work_item_sha256":identity_digest(request.work_item_id),"operation_id":request.operation_id,"capability_id":request.capability_id})
        return decision


@dataclass(frozen=True)
class OPADecision:
    allowed: bool
    revision: str | None
    decision_id: str | None
    creates_grants: bool = False


class OPADenyVeto:
    """AND-compose with existing SENTRA AuthorizationService; cannot grant."""

    def __init__(self, base_grant: Callable[[OperationRequest], PolicyDecision],
                 opa: OPAClient, *, trusted_workspace_id: str):
        if not callable(base_grant) or not isinstance(opa, OPAClient):
            raise ValueError("trusted grant and OPA policy client required")
        if not trusted_workspace_id:
            raise ValueError("trusted workspace required")
        self.base_grant, self.opa, self.workspace_id = (
            base_grant, opa, trusted_workspace_id,
        )

    def __call__(self, request: OperationRequest) -> PolicyDecision:
        try:
            initial = self.base_grant(request)
            if (not isinstance(initial, PolicyDecision) or initial.allowed is not True):
                return PolicyDecision(False, "SENTRA grant absent or constrained")
            if not self.opa.allows(request=request, workspace_id=self.workspace_id):
                return PolicyDecision(False, "OPA supplemental policy denied")
            final=self.base_grant(request)
            if not isinstance(final,PolicyDecision) or final.allowed is not True: return PolicyDecision(False,"CorePDP changed during OPA decision")
            return PolicyDecision(True, "SENTRA grant and OPA permit",final.constraints)
        except Exception:
            return PolicyDecision(False, "OPA supplemental authority unavailable")
