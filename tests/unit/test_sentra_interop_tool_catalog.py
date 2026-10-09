"""Discovery acceptance only; semantic doubles never authorize execution."""
import asyncio
import pytest
from sentra_interop.gate import InteropGate, EffectRejected
from sentra_interop.tool_catalog import AuthorizedToolCatalog, ToolDescriptor
from sentra_runtime.contracts import Capability,Machine,OperationRequest,PolicyDecision


def tool(name,version="1",schema=None):
    return ToolDescriptor.from_mapping({"tool_id":name,"capability_id":"tool:"+name,"name":name,
        "description":"Read file content in workspace" if name=="read_file" else "Search catalog and documents "+"details "*100,
        "version":version,"inputSchema":schema or {"type":"object","properties":{"path":{"type":"string"}}}})


def setup(authorize=None,embedding=None):
    gate=InteropGate(Machine("machine","catalog","owner",(Capability("tools:discover","discover"),)),
                      lambda _:PolicyDecision(True,"test discovery grant"))
    return AuthorizedToolCatalog(gate,authorize_tool=authorize,embedding=embedding)


def request(name,semantic=False):
    return OperationRequest("op-"+name,"owner","machine","tools:discover","work","key-"+name,
        {"query":"read file","limit":1,"semantic":semantic,"semantic_weight":.35})


def test_lexical_discovery_filters_authorization_and_estimates_actual_catalog_savings():
    async def case():
        catalog=setup(lambda descriptor,req:PolicyDecision(descriptor.tool_id!="secret","visibility"))
        catalog.replace([tool("read_file"),tool("search"),tool("secret")])
        result=await catalog.discover(request("lexical"),query="read file",limit=1)
        assert result.operation.state=="SUCCEEDED"
        assert [t["tool_id"] for t in result.payload["tools"]]==["read_file"]
        assert result.payload["authorized_count"]==2
        assert result.payload["token_metrics"]["savings_percent"]>0
        assert result.payload["execution_authorization_required"] is True
    asyncio.run(case())


def test_schema_and_version_change_invalidate_discovery_fingerprint():
    catalog=setup()
    old=tool("read_file")
    catalog.replace([old])
    assert catalog.require_current("read_file",fingerprint=old.fingerprint)==old
    catalog.replace([tool("read_file",schema={"type":"object","required":["new"]})])
    with pytest.raises(EffectRejected): catalog.require_current("read_file",fingerprint=old.fingerprint)
    new=tool("read_file",version="2")
    catalog.replace([new])
    assert new.fingerprint!=old.fingerprint


def test_semantic_provider_only_receives_authorized_descriptors_and_revocation_is_rechecked():
    async def case():
        state={"revoked":False}
        class ExplicitEmbeddingDouble:
            identity="unit-provider/model/revision"
            calls=[]
            async def embed(self,texts):
                self.calls.append(texts)
                if texts==["read file"]: state["revoked"]=True
                return [[1.,0.] for _ in texts]
        provider=ExplicitEmbeddingDouble()
        catalog=setup(lambda d,r:PolicyDecision(d.tool_id!="secret" and not state["revoked"],"visibility"),provider)
        catalog.replace([tool("read_file"),tool("secret")])
        result=await catalog.discover(request("semantic",True),query="read file",limit=1,semantic=True)
        assert result.operation.state=="SUCCEEDED" and result.payload["tools"]==[]
        assert not any("secret" in text for batch in provider.calls for text in batch)
    asyncio.run(case())


def test_no_authorizer_and_no_implicit_embedding_provider_fail_closed():
    async def case():
        catalog=setup()
        catalog.replace([tool("read_file")])
        assert (await catalog.discover(request("no-pdp"),query="read file",limit=1)).operation.state=="FAILED"
        catalog=setup(lambda d,r:PolicyDecision(True,"visibility"))
        catalog.replace([tool("read_file")])
        assert (await catalog.discover(request("no-embedding",True),query="read file",limit=1,semantic=True)).operation.state=="FAILED"
    asyncio.run(case())
