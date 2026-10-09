"""Optional OpenFGA Check API v1 relationship veto.

Does not create/delete tuples, models or grants. The SENTRA durable grant
MUST allow the action first; OpenFGA can only narrow access. Local tests
exercise the HTTP wire protocol with a loopback fixture, not an installed
OpenFGA deployment or cross-device authorization.
"""
from __future__ import annotations
from collections.abc import Callable
import re
import time
from dataclasses import dataclass

from ._policy_http import LoopbackPolicyHTTP, PolicyTransportUnavailable, PinnedProviderHTTP
from .identity_state import identity_digest
from .contracts import OperationRequest, PolicyDecision

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class OpenFGACheckClient:
    def __init__(self, *, endpoint: str, bearer: str,
                 store_id: str, authorization_model_id: str,
                 timeout_s: float = 1.5, allow_remote: bool = False,
                 consistency: str = "HIGHER_CONSISTENCY", http=None,subject_type="agent"):
        if (not isinstance(store_id, str) or not _ID.fullmatch(store_id)
                or not isinstance(authorization_model_id, str)
                or not _ID.fullmatch(authorization_model_id)):
            raise ValueError("pinned OpenFGA store and model identifiers required")
        if consistency not in {"HIGHER_CONSISTENCY","MINIMIZE_LATENCY"}: raise ValueError("explicit OpenFGA consistency required")
        self.http = http or (PinnedProviderHTTP(base=endpoint,token=bearer,enabled=True,timeout_s=timeout_s) if allow_remote else
            LoopbackPolicyHTTP(base=endpoint, token=bearer,timeout_s=timeout_s))
        self.store_id = store_id
        self.authorization_model_id = authorization_model_id
        self.consistency=consistency
        if not isinstance(subject_type,str) or not _ID.fullmatch(subject_type): raise ValueError("pinned OpenFGA subject type required")
        self.subject_type=subject_type

    def allows(self, *, request: OperationRequest) -> bool:
        if not isinstance(request, OperationRequest):
            raise ValueError("typed SENTRA operation required")
        if (not _ID.fullmatch(request.principal_id)
                or not _ID.fullmatch(request.work_item_id)):
            raise ValueError("noncanonical principal or work item")
        # OpenFGA CheckRequest is POST /stores/{store_id}/check.
        # The caller pins the authorized model; no provider-supplied IDs.
        response = self.http.post("/stores/" + self.store_id + "/check", {
            "authorization_model_id": self.authorization_model_id,
            "consistency":"HIGHER_CONSISTENCY",
            "tuple_key": {
                "user": self.subject_type+":" + request.principal_id,
                "relation": "can_execute",
                "object": "work_item:" + request.work_item_id,
            },
        })
        if not isinstance(response.get("allowed"), bool):
            raise PolicyTransportUnavailable("OpenFGA boolean allowed missing")
        if set(response) - {"allowed", "resolution"}:
            raise PolicyTransportUnavailable("unexpected OpenFGA response")
        if "resolution" in response and not isinstance(response["resolution"], str):
            raise PolicyTransportUnavailable("invalid OpenFGA resolution")
        return response["allowed"]

    def list_objects(self,*,principal_id,object_type,relation,consistency=None):
        if not all(isinstance(v,str) and _ID.fullmatch(v) for v in (principal_id,object_type,relation)):
            raise ValueError("canonical host-derived discovery scope required")
        selected=consistency or self.consistency
        if selected not in {"HIGHER_CONSISTENCY","MINIMIZE_LATENCY"}: raise ValueError("invalid consistency")
        response=self.http.post("/stores/"+self.store_id+"/list-objects",{
            "authorization_model_id":self.authorization_model_id,"user":self.subject_type+":"+principal_id,
            "relation":relation,"type":object_type,"consistency":selected})
        objects=response.get("objects")
        if not isinstance(objects,list) or len(objects)>10000 or any(not isinstance(v,str) or not v.startswith(object_type+":") or len(v)>512 for v in objects):
            raise PolicyTransportUnavailable("malformed OpenFGA object discovery")
        return RelationshipDiscovery(tuple(dict.fromkeys(objects)),self.store_id,self.authorization_model_id,selected,False)

    def read_changes(self,*,object_type=None,continuation_token="",page_size=100,start_time=None):
        if object_type is not None and (not isinstance(object_type,str) or not _ID.fullmatch(object_type)): raise ValueError("invalid change object type")
        if not isinstance(continuation_token,str) or len(continuation_token)>8192 or type(page_size) is not int or not 1<=page_size<=100:
            raise ValueError("invalid bounded changes cursor")
        params={"page_size":page_size,"continuation_token":continuation_token}
        if object_type: params["type"]=object_type
        if start_time is not None:
            if continuation_token or not isinstance(start_time,str) or len(start_time)>64: raise ValueError("start_time only allowed on first changes page")
            params["start_time"]=start_time
        response=self.http.get("/stores/"+self.store_id+"/changes",params=params)
        changes,token=response.get("changes",[]),response.get("continuation_token","")
        if not isinstance(changes,list) or len(changes)>100 or not isinstance(token,str) or len(token)>8192:
            raise PolicyTransportUnavailable("malformed OpenFGA changes page")
        for change in changes:
            if (not isinstance(change,dict) or not isinstance(change.get("tuple_key"),dict) or
                change.get("operation") not in {"TUPLE_OPERATION_WRITE","TUPLE_OPERATION_DELETE"} or not isinstance(change.get("timestamp"),str)):
                raise PolicyTransportUnavailable("malformed tuple change")
        return {"changes":changes,"continuation_token":token,"store_id":self.store_id,"model_id":self.authorization_model_id}

    def read_assertions(self):
        response=self.http.get("/stores/"+self.store_id+"/assertions/"+self.authorization_model_id)
        if response.get("authorization_model_id",self.authorization_model_id)!=self.authorization_model_id or not isinstance(response.get("assertions",[]),list):
            raise PolicyTransportUnavailable("assertions model mismatch")
        return response.get("assertions",[])

    def evaluate_assertions(self):
        """Use only assertions configured on the pinned server model, not caller tuples."""
        results=[]
        assertions=self.read_assertions()
        if not assertions or len(assertions)>100: raise PolicyTransportUnavailable("meaningful bounded stored assertions required")
        for assertion in assertions:
            if not isinstance(assertion,dict) or not isinstance(assertion.get("tuple_key"),dict) or type(assertion.get("expectation")) is not bool:
                raise PolicyTransportUnavailable("invalid stored model assertion")
            body={"authorization_model_id":self.authorization_model_id,"tuple_key":assertion["tuple_key"],"consistency":"HIGHER_CONSISTENCY"}
            # Assertion fixtures are isolated checks, not live admission evidence.
            if assertion.get("contextual_tuples"): body["contextual_tuples"]={"tuple_keys":assertion["contextual_tuples"]}
            if assertion.get("context") is not None: body["context"]=assertion["context"]
            observed=self.http.post("/stores/"+self.store_id+"/check",body).get("allowed")
            if type(observed) is not bool: raise PolicyTransportUnavailable("assertion Check omitted boolean")
            results.append({"assertion_sha256":identity_digest(assertion),"expected":assertion["expectation"],"observed":observed,
                            "passed":observed==assertion["expectation"],"creates_grants":False})
        return {"model_id":self.authorization_model_id,"results":results,"passed":all(r["passed"] for r in results)}

    def write_assertions(self,assertions,*,trusted_admin_authorize):
        """Explicit model administration; never called by discovery/admission."""
        if not callable(trusted_admin_authorize) or trusted_admin_authorize(self.store_id,self.authorization_model_id,"write_assertions") is not True:
            raise PermissionError("host model administration authorization required")
        if not isinstance(assertions,list) or not 1<=len(assertions)<=100: raise ValueError("bounded assertions required")
        for item in assertions:
            if not isinstance(item,dict) or type(item.get("expectation")) is not bool or not isinstance(item.get("tuple_key"),dict):
                raise ValueError("invalid model assertion")
        self.http.put("/stores/"+self.store_id+"/assertions/"+self.authorization_model_id,{"assertions":assertions})
        return {"model_id":self.authorization_model_id,"assertions_sha256":identity_digest(assertions),"creates_grants":False}


@dataclass(frozen=True)
class RelationshipDiscovery:
    objects: tuple
    store_id: str
    model_id: str
    consistency: str
    authorizes_effects: bool = False


class OpenFGADiscoveryProjection:
    """Persisted invalidation cursor; effect admission always does fresh Check."""
    def __init__(self,client,*,store,object_type,on_invalidate=None,clock=time.time):
        if not _ID.fullmatch(object_type): raise ValueError("invalid discovery type")
        self.client,self.store,self.object_type,self.on_invalidate,self.clock=client,store,object_type,on_invalidate,clock
        self.key="fga:"+identity_digest({"store":client.store_id,"model":client.authorization_model_id,"type":object_type})
    def poll_changes(self):
        record=self.store.get(self.key)
        state=record["value"] if record else {"cursor":"","generation":0}
        page=self.client.read_changes(object_type=self.object_type,continuation_token=state["cursor"])
        if page["changes"] and callable(self.on_invalidate): self.on_invalidate(page["changes"])
        state={"cursor":page["continuation_token"],"generation":state["generation"]+(1 if page["changes"] else 0),"last_poll":self.clock()}
        self.store.put(self.key,state,expected_revision=record["revision"] if record else None)
        return {"generation":state["generation"],"changed":bool(page["changes"]),"creates_grants":False}
    def discover(self,*,principal_id,relation,core_authorize_resource):
        if not callable(core_authorize_resource): raise ValueError("CorePDP resource filter required")
        snapshot=self.client.list_objects(principal_id=principal_id,object_type=self.object_type,relation=relation,consistency="HIGHER_CONSISTENCY")
        accessible=[]
        for resource in snapshot.objects:
            decision=core_authorize_resource(principal_id,resource)
            if isinstance(decision,PolicyDecision) and decision.allowed is True: accessible.append(resource)
        return {"objects":accessible,"store_id":snapshot.store_id,"model_id":snapshot.model_id,
                "consistency":snapshot.consistency,"authorizes_effects":False,"truncation_may_apply":True}


class OpenFGADenyVeto:
    def __init__(self, base_grant: Callable[[OperationRequest], PolicyDecision],
                 fga: OpenFGACheckClient):
        if not callable(base_grant) or not isinstance(fga, OpenFGACheckClient):
            raise ValueError("trusted SENTRA authority and OpenFGA client required")
        self.base_grant, self.fga = base_grant, fga

    def __call__(self, request: OperationRequest) -> PolicyDecision:
        try:
            decision = self.base_grant(request)
            if (not isinstance(decision, PolicyDecision)
                    or decision.allowed is not True):
                return PolicyDecision(False, "SENTRA grant absent or constrained")
            if not self.fga.allows(request=request):
                return PolicyDecision(False, "OpenFGA relationship denied")
            final=self.base_grant(request)
            if not isinstance(final,PolicyDecision) or final.allowed is not True: return PolicyDecision(False,"CorePDP changed during relationship check")
            return PolicyDecision(True, "SENTRA grant and OpenFGA relationship permit",final.constraints)
        except Exception:
            return PolicyDecision(False, "OpenFGA supplemental authority unavailable")
