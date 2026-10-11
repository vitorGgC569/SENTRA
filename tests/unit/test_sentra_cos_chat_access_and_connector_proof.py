"""Core SENTRA integrations adapted from CoS, with no upstream process."""
from __future__ import annotations
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sentra_mcp.services.chat_access import ChatAccessService
from sentra_mcp.tool_policy import ToolPolicyProxy
from sentra_remote.connector_proof import ConnectorProof
from sentra_remote.diagnostics import shareable_report
from sentra_remote.onboarding import chatgpt_plugin_install_plan


def test_exact_chat_access_durable_deny_and_conflict(tmp_path):
    svc=ChatAccessService(tmp_path)
    p="local-operator"
    first="chat-first-12345678"
    second="chat-second-12345678"
    req="request-12345678"
    assert svc.require_allowed(p,None)["source"]=="unattributed"
    assert svc.set_strict(p,True,expected_revision=0)["revision"]==1
    with pytest.raises(PermissionError,match="unproven"):
        svc.require_allowed(p,None)
    assert svc.bind_verified_request(p,req,first,evidence_sha256="a"*64)["state"]=="proven"
    with pytest.raises(PermissionError,match="not explicitly trusted"):
        svc.require_allowed(p,req)
    with pytest.raises(PermissionError,match="already owned"):
        svc.bind_verified_request(p,req,second,evidence_sha256="b"*64)
    assert svc.set_chat(p,first,trusted=True,blocked=False,expected_revision=0)["revision"]==1
    assert svc.require_allowed(p,req)["conversation_id"]==first
    with pytest.raises(ValueError,match="revision changed"):
        svc.set_chat(p,first,trusted=True,blocked=False,expected_revision=0)
    assert svc.set_chat(p,first,trusted=False,blocked=True,expected_revision=1)["blocked"]
    with pytest.raises(PermissionError,match="blocked"):
        svc.require_allowed(p,req)
    assert svc.set_strict(p,False,expected_revision=1)["strict"] is False
    with pytest.raises(PermissionError,match="blocked"):
        svc.require_allowed(p,req)
    assert ChatAccessService(tmp_path).chat_status(p,first)["blocked"]
    assert svc.require_allowed("oauth:other",req)["source"]=="unattributed"


def test_tool_policy_wraps_even_without_context_and_preserves_annotations(tmp_path):
    service=ChatAccessService(tmp_path)
    installed={}
    class Server:
        def tool(self,*args,**kwargs):
            def register(func):
                installed[func.__name__]=func
                return func
            return register
    proxy=ToolPolicyProxy(Server(),(),chat_access=service)
    @proxy.tool()
    def read_work(*,count:int=1)->int:
        return count+1
    assert inspect.signature(read_work).parameters["count"].annotation in (int,"int")
    assert read_work(count=3)==4
    service.set_strict("local-operator",True,expected_revision=0)
    with pytest.raises(PermissionError,match="unproven"):
        read_work(count=1)


def test_connector_proof_is_tunnel_bound_and_never_claims_account(tmp_path):
    proof=ConnectorProof(tmp_path)
    a="tunnel_1234567890abcdef"
    b="tunnel_abcdef1234567890"
    (tmp_path/"tunnel.json").write_text(json.dumps({"tunnel_id":a}))
    assert proof.status()["mcp_tool_observed"] is False
    proof.record_tool(surface="core",transport="streamable-http",authenticated=True)
    verified=ConnectorProof(tmp_path).status(a)
    assert verified["authenticated_tool_observed"]
    assert verified["surfaces"][0]["calls"]==1
    assert verified["plugin_installed_in_chatgpt"]=="unverified"
    assert a not in json.dumps(verified)
    assert proof.status(b)["mcp_tool_observed"] is False
    (tmp_path/"tunnel.json").write_text(json.dumps({"tunnel_id":b}))
    assert proof.status()["mcp_tool_observed"] is False


def test_safe_support_export_is_allowlist_only():
    secret="sk-test-UNSAFE-verylong-secretvalue"
    machine="company-private-host"
    raw={"python":"3.12.5","platform":"Windows-10-privatebuild","hostname":machine,
         "config_exists":True,"config_error":secret,
         "device":{"device_id":secret,"name":machine,
                   "allowed_roots":[r"C:\\Users\\private\\Payroll"],
                   "relay_url":"https://secret.example/?token="+secret,
                   "audit_log":r"C:\\private\\files.log","tool_surfaces":["core","browser"],
                   "token_present":True,"profile":"Safe"},
         "relay":{"ok":True,"sensitive":"x"},"audit_exists":True}
    safe=shareable_report(raw)
    encoded=json.dumps(safe)
    for sensitive in (secret,machine,"private","Payroll","secret.example","sensitive"):
        assert sensitive not in encoded
    assert safe["config_parse_ok"] is False
    assert safe["device"]["workspace_count"]==1
    assert safe["relay"]["healthy"] is True


def test_onboarding_evidence_never_auto_approves_chatgpt():
    result=chatgpt_plugin_install_plan(
        {"mcp":{"ok":True},"tunnel":{"configured":True,"ok":True},
         "plugin_proof":{"mcp_tool_observed":True,"authenticated_tool_observed":True}},
        tunnel_id="tunnel_1234567890"
    )
    assert result["ready_to_install"]
    assert result["requires_account_authorization"]
    assert result["plugin_evidence"]["plugin_installed_in_chatgpt"]=="unverified"



def test_mcp_invocation_context_denies_untrusted_chat_before_any_side_effect(tmp_path):
    from types import SimpleNamespace
    svc=ChatAccessService(tmp_path)
    principal="local-operator"
    req="request-abcdef123456"
    chat="conversation-abcdef123456"
    svc.bind_verified_request(principal,req,chat,evidence_sha256="a"*64)
    svc.set_strict(principal,True,expected_revision=0)
    effects=[]
    observed=[]
    class MCP:
        def tool(self):
            return lambda func:func
    proxy=ToolPolicyProxy(MCP(),(),chat_access=svc,
        request_observer=lambda ctx,name:observed.append(name))
    @proxy.tool()
    def read_documents(*,ctx):
        effects.append("read")
        return 7
    context=SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(headers={"x-request-id":req})))
    with pytest.raises(PermissionError,match="not explicitly trusted"):
        read_documents(ctx=context)
    assert effects==[] and observed==[]
    svc.set_chat(principal,chat,trusted=True,blocked=False,expected_revision=0)
    assert read_documents(ctx=context)==7
    assert effects==["read"] and observed==["read_documents"]
    svc.set_chat(principal,chat,trusted=False,blocked=True,expected_revision=1)
    with pytest.raises(PermissionError,match="blocked"):
        read_documents(ctx=context)
    assert effects==["read"]


def test_mcp_strict_mode_rejects_unknown_request_header(tmp_path):
    from types import SimpleNamespace
    svc=ChatAccessService(tmp_path)
    svc.set_strict("local-operator",True,expected_revision=0)
    class MCP:
        def tool(self):
            return lambda func:func
    proxy=ToolPolicyProxy(MCP(),(),chat_access=svc)
    @proxy.tool()
    def observe(*,ctx):
        pytest.fail("unknown request must not call tool body")
    ctx=SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(headers={"x-request-id":"attacker-request-123456"})))
    with pytest.raises(PermissionError,match="unproven"):
        observe(ctx=ctx)

def test_local_schema_fingerprint_never_claims_chatgpt_refresh(tmp_path):
    from sentra_remote.connector_proof import ConnectorProof
    tunnel="tunnel_schema12345678"
    (tmp_path/"tunnel.json").write_text(json.dumps({"tunnel_id":tunnel}))
    service=ConnectorProof(tmp_path)
    service.record_local_schema(schema_sha256="a"*64,method_count=19)
    assert service.status()["local_schemas"][0]["method_count"]==19
    service.record_tool(authenticated=True,transport="streamable-http")
    service.record_local_schema(schema_sha256="b"*64,method_count=20)
    state=ConnectorProof(tmp_path).status(tunnel)
    assert state["local_schema_changed_since_authenticated_call"] is True
    assert state["schema_current_in_chatgpt"]=="unverified"
    service.record_tool(authenticated=False)
    assert service.status()["local_schema_changed_since_authenticated_call"] is True
    service.record_tool(authenticated=True)
    state=service.status()
    assert state["local_schema_changed_since_authenticated_call"] is False
    assert state["schema_current_in_chatgpt"]=="unverified"
    with pytest.raises(ValueError):
        service.record_local_schema(schema_sha256="invalid",method_count=5)
    assert service.status("tunnel_other12345678")["mcp_tool_observed"] is False


def test_server_fingerprint_tracks_actual_registered_schema(tmp_path):
    from types import SimpleNamespace
    from sentra_mcp.server import SentraMCPServer
    from sentra_remote.connector_proof import ConnectorProof
    (tmp_path/"tunnel.json").write_text(json.dumps({"tunnel_id":"tunnel_registered123456"}))
    server=SentraMCPServer.__new__(SentraMCPServer)
    server.connector_proof=ConnectorProof(tmp_path)
    class Registry:
        items=[SimpleNamespace(name="sentra_health",parameters={"type":"object"},
                               output_schema=None)]
        def list_tools(self):
            return self.items
    registry=Registry()
    server.mcp=SimpleNamespace(_tool_manager=registry)
    server._publish_local_schema()
    first=server.connector_proof.status()["local_schemas"][0]
    server._publish_local_schema()
    assert first["schema_sha256"]==server.connector_proof.status()["local_schemas"][0]["schema_sha256"]
    registry.items.append(SimpleNamespace(name="new_tool",parameters={"type":"object","required":["name"]},
                                          output_schema={"type":"object"}))
    server._publish_local_schema()
    latest=server.connector_proof.status()["local_schemas"][0]
    assert latest["method_count"]==2 and latest["schema_sha256"]!=first["schema_sha256"]
