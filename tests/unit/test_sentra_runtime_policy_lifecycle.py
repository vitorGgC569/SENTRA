"""Prepared relationship/bundle/decision contracts; no validation run in wave4.

Recording HTTP classes are declared protocol fixtures. Only opt-in real OPA
CLI test validates Rego; fixtures never certify an OPA/OpenFGA deployment.
"""
import asyncio
import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from sentra_runtime.contracts import OperationRequest,PolicyDecision
from sentra_runtime.identity_state import ProtectedIdentityStore
from sentra_runtime.openfga_rebac import OpenFGACheckClient,OpenFGADenyVeto,OpenFGADiscoveryProjection
from sentra_runtime.opa_pdp import OPAClient,OPADenyVeto
from sentra_runtime.policy_bundle import OPABundleManager,OPAOfflineValidator
from sentra_runtime._policy_http import PolicyTransportUnavailable


def request(): return OperationRequest("op","agent1","machine","write","work1","idem",{"contextual_tuples":[{"user":"agent:agent1","relation":"admin"}]})


def test_openfga_discovery_is_filtered_changes_invalidate_and_live_write_is_high_consistency(tmp_path):
    class RecordingFGA:
        changed=False
        def __init__(self): self.calls=[]
        def post(self,path,body):
            self.calls.append(("POST",path,body))
            if path.endswith("/list-objects"): return {"objects":["document:allowed","document:core-denied"]}
            assert body["consistency"]=="HIGHER_CONSISTENCY" and "contextual_tuples" not in body
            return {"allowed":not self.changed}
        def get(self,path,*,params=None):
            self.calls.append(("GET",path,params))
            if path.endswith("/changes"):
                return {"changes":[{"tuple_key":{"user":"agent:agent1","relation":"reader","object":"document:allowed"},
                    "operation":"TUPLE_OPERATION_DELETE","timestamp":"2026-10-09T10:00:00Z"}],"continuation_token":"opaque-next"}
            return {"authorization_model_id":"model1","assertions":[]}
    http=RecordingFGA()
    fga=OpenFGACheckClient(endpoint="http://127.0.0.1:8080",bearer="not-used-fixture-transport",store_id="store1",authorization_model_id="model1",http=http,
                          consistency="MINIMIZE_LATENCY")
    store=ProtectedIdentityStore(tmp_path/"projection.sqlite",workspace=tmp_path,namespace="fga")
    invalidated=[]
    discovery=OpenFGADiscoveryProjection(fga,store=store,object_type="document",on_invalidate=lambda changes:invalidated.extend(changes))
    result=discovery.discover(principal_id="agent1",relation="reader",core_authorize_resource=lambda p,r:PolicyDecision(r=="document:allowed","core filter"))
    assert result["objects"]==["document:allowed"] and result["authorizes_effects"] is False
    core=lambda _:PolicyDecision(True,"core grant",{"roots":["workspace"]})
    veto=OpenFGADenyVeto(core,fga)
    assert veto(request()).allowed and veto(request()).constraints=={"roots":["workspace"]}
    http.changed=True
    assert discovery.poll_changes()["changed"] and invalidated
    assert store.get(discovery.key)["value"]["cursor"]=="opaque-next"
    assert veto(request()).allowed is False
    assert all(c[2]["consistency"]=="HIGHER_CONSISTENCY" for c in http.calls if c[0]=="POST")


def test_assertions_are_server_pinned_and_never_grants_or_caller_privileges():
    class AssertionsProtocol:
        calls=[]
        def get(self,path,**kwargs):
            return {"authorization_model_id":"model1","assertions":[{"tuple_key":{"user":"agent:a","relation":"reader","object":"document:1"},
                "expectation":False,"contextual_tuples":[{"user":"agent:a","relation":"other","object":"document:1"}]}]}
        def post(self,path,body): self.calls.append(body); return {"allowed":False}
        def put(self,path,body): self.calls.append(body); return {}
    http=AssertionsProtocol()
    fga=OpenFGACheckClient(endpoint="http://127.0.0.1:8080",bearer="not-used-fixture-transport",store_id="store1",authorization_model_id="model1",http=http)
    result=fga.evaluate_assertions()
    assert result["passed"] and result["results"][0]["creates_grants"] is False
    with pytest.raises(PermissionError): fga.write_assertions([],trusted_admin_authorize=lambda *args:False)
    deny=OpenFGADenyVeto(lambda _:PolicyDecision(False,"no core grant"),fga)
    before=len(http.calls)
    assert deny(request()).allowed is False and len(http.calls)==before


def test_revisioned_opa_decisions_mask_evidence_and_deny_version_change():
    revision=["r1"]; events=[]
    class OPAProtocol:
        result={"result":{"allow":True,"revision":"r1"},"decision_id":"vendor-decision-1"}
        mutate=False
        def post(self,path,body):
            assert path=="/v1/data/sentra/decision" and "arguments" not in body["input"]
            if self.mutate: revision[0]="r2"
            return self.result
    http=OPAProtocol()
    opa=OPAClient(endpoint="http://127.0.0.1:8181",bearer="not-used-fixture-transport",decision_path="/v1/data/sentra/decision",http=http,
                  active_revision=lambda:revision[0],audit_sink=events.append)
    decision=opa.decide(request=request(),workspace_id="workspace")
    assert decision.revision=="r1" and decision.decision_id=="vendor-decision-1" and decision.creates_grants is False
    assert "principal" not in events[0] and "input" not in events[0] and "arguments" not in events[0]
    assert events[0]["principal_sha256"]!="agent1"
    veto=OPADenyVeto(lambda _:PolicyDecision(False,"core denied"),opa,trusted_workspace_id="workspace")
    assert veto(request()).allowed is False
    http.mutate=True
    with pytest.raises(PolicyTransportUnavailable): opa.decide(request=request(),workspace_id="workspace")


def make_archive(root,*,revision="r1",unsafe=None):
    path=root/(revision+".tar.gz")
    with tarfile.open(path,"w:gz") as tar:
        for name,data in ((".manifest",json.dumps({"revision":revision,"roots":["sentra"],"rego_version":1}).encode()),
            ("sentra.rego",b'package sentra\nimport rego.v1\ndefault allow := false\nallow if input.capability == "read"\n')):
            info=tarfile.TarInfo(name); info.size=len(data); tar.addfile(info,io.BytesIO(data))
        if unsafe:
            info=tarfile.TarInfo(unsafe); info.size=1; tar.addfile(info,io.BytesIO(b"x"))
    return path,hashlib.sha256(path.read_bytes()).hexdigest()


def test_unsafe_candidate_and_missing_real_validator_preserve_last_valid(tmp_path):
    store=ProtectedIdentityStore(tmp_path/"bundle.sqlite",workspace=tmp_path,namespace="opa")
    validator=OPAOfflineValidator(executable=str(tmp_path/"missing-opa.exe"),executable_sha256="0"*64,
        capabilities_file=str(tmp_path/"missing-capabilities.json"),capabilities_sha256="0"*64)
    manager=OPABundleManager(root=tmp_path/"bundles",workspace=tmp_path,store=store,validator=validator)
    # Explicit projection fixture, not fabricated evidence of daemon activation.
    store.put(manager.key,{"revision":"fixture-old","confirmed_revision":"fixture-old","runtime_activation_confirmed":True,
        "path":str(tmp_path/"unserved-old.tar.gz"),"sha256":"0"*64,"validation":{"fixture":True}})
    malicious,sha=make_archive(tmp_path,revision="unsafe",unsafe="../escape.rego")
    with pytest.raises(ValueError): manager.stage(malicious,expected_sha256=sha,expected_revision="unsafe")
    path,sha=make_archive(tmp_path,revision="r1")
    candidate=manager.stage(path,expected_sha256=sha,expected_revision="r1")
    async def case():
        with pytest.raises(ValueError): await manager.activate(candidate,acceptance_cases=[{"input":{"capability":"read"},"expected_allow":True}],trusted_admin_authorize=lambda *args:True)
        assert manager.active_revision()=="fixture-old" and manager.published_revision()=="fixture-old"
    asyncio.run(case())


def test_real_official_opa_cli_bundle_acceptance_opt_in(tmp_path):
    binary=os.environ.get("SENTRA_ACCEPTANCE_OPA_BINARY"); capabilities=os.environ.get("SENTRA_ACCEPTANCE_OPA_CAPABILITIES")
    if not binary or not capabilities: pytest.skip("actual OPA binary + offline capabilities required; no fake validator fallback")
    validator=OPAOfflineValidator(executable=str(Path(binary).resolve()),executable_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        capabilities_file=str(Path(capabilities).resolve()),capabilities_sha256=hashlib.sha256(Path(capabilities).read_bytes()).hexdigest())
    store=ProtectedIdentityStore(tmp_path/"bundle.sqlite",workspace=tmp_path,namespace="opa")
    manager=OPABundleManager(root=tmp_path/"bundles",workspace=tmp_path,store=store,validator=validator)
    path,sha=make_archive(tmp_path)
    candidate=manager.stage(path,expected_sha256=sha,expected_revision="r1")
    async def case():
        result=await manager.activate(candidate,acceptance_cases=[{"input":{"capability":"read"},"expected_allow":True},
            {"input":{"capability":"write"},"expected_allow":False}],trusted_admin_authorize=lambda *args:True)
        assert result["runtime_activation_confirmed"] is False and manager.active_revision() is None
        assert manager.resource()["body"]==path.read_bytes()
        assert manager.published_revision()=="r1"
    asyncio.run(case())
