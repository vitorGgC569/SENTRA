"""MCP TypeScript SDK-shaped 2025-06-18 stdio interop, no npm dependency.

A local transport-only client; privileged tools still go through
ToolHiveMCPBoundary. Explicitly pinned resource/prompt names and read grants
avoid exposing arbitrary filesystem/resources or agent-initiated operations.
"""
from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import urlsplit
from .mcp_stdio import MCPStdioClient, MCPStdioError
from .mcp import _deny_obvious_secret_values
from sentra_runtime.contracts import OperationRequest

MCP_VERSION = "2025-06-18"


class MCPTypescriptCompatClient(MCPStdioClient):
    """Wire compatibility only, *not* TypeScript SDK runtime."""

    def configure_readonly(self, *, resources: frozenset[str],
                           prompts: frozenset[str]) -> None:
        if (not isinstance(resources, frozenset) or not isinstance(prompts, frozenset)
            or any(not isinstance(x,str) or not x or len(x)>256
                   for x in (*resources,*prompts))
            or any(not x.startswith("sentra://") or urlsplit(x).netloc != "fixture"
                   or urlsplit(x).query or urlsplit(x).fragment
                   for x in resources)):
            raise MCPStdioError("resource/prompt allowlist must be explicit")
        self._approved_resources = resources
        self._approved_prompts = prompts

    async def _verify(self, request: OperationRequest, *,
                      capability: str, payload: Mapping[str, Any]) -> None:
        if (not self._initialized or not hasattr(self,"_approved_resources")
            or request.capability_id != capability
            or request.machine_id != self.gate.machine.machine_id
            or request.arguments != payload
            or not (await self.gate.decision(request)).allowed):
            raise MCPStdioError("MCP SDK read-only access denied")

    async def list_resources(self, request: OperationRequest) -> tuple[str, ...]:
        await self._verify(request,capability="mcp:resources_list",
                           payload={"server_id":self.server_id})
        result = await self._call("resources/list",{},3)
        values = result.get("resources")
        if not isinstance(values,list) or len(values)>128:
            raise MCPStdioError("invalid MCP resources/list result")
        names=[]
        for item in values:
            if not isinstance(item,Mapping) or not isinstance(item.get("uri"),str):
                raise MCPStdioError("invalid MCP resource descriptor")
            names.append(item["uri"])
        if len(names)!=len(set(names)) or set(names)-self._approved_resources:
            raise MCPStdioError("unapproved MCP resource advertised")
        await self._verify(request,capability="mcp:resources_list",
                           payload={"server_id":self.server_id})
        return tuple(names)

    async def read_resource(self, request: OperationRequest, *, uri: str
                            ) -> Mapping[str, Any]:
        if uri not in getattr(self,"_approved_resources",frozenset()):
            raise MCPStdioError("resource URI outside allowlist")
        await self._verify(request,capability="mcp:resource_read",
                           payload={"server_id":self.server_id,"uri":uri})
        result = await self._call("resources/read",{"uri":uri},3)
        contents = result.get("contents")
        if (not isinstance(contents,list) or len(contents)!=1
            or not isinstance(contents[0],Mapping)
            or set(contents[0])!={"uri","mimeType","text"}
            or contents[0]["uri"]!=uri
            or contents[0]["mimeType"]!="text/plain"
            or not isinstance(contents[0]["text"],str)
            or len(contents[0]["text"].encode("utf-8"))>16384):
            raise MCPStdioError("invalid MCP resource response")
        _deny_obvious_secret_values(result)
        await self._verify(request,capability="mcp:resource_read",
                           payload={"server_id":self.server_id,"uri":uri})
        return {"uri":uri,"text":contents[0]["text"]}

    async def list_prompts(self, request: OperationRequest) -> tuple[str, ...]:
        await self._verify(request,capability="mcp:prompts_list",
                           payload={"server_id":self.server_id})
        result = await self._call("prompts/list",{},3)
        prompts = result.get("prompts")
        if not isinstance(prompts,list) or len(prompts)>128:
            raise MCPStdioError("invalid MCP prompts/list result")
        names=[]
        for item in prompts:
            if not isinstance(item,Mapping) or not isinstance(item.get("name"),str):
                raise MCPStdioError("invalid MCP prompt descriptor")
            names.append(item["name"])
        if len(names)!=len(set(names)) or set(names)-self._approved_prompts:
            raise MCPStdioError("unapproved MCP prompt advertised")
        await self._verify(request,capability="mcp:prompts_list",
                           payload={"server_id":self.server_id})
        return tuple(names)

    async def get_prompt(self, request: OperationRequest, *, name: str
                         ) -> Mapping[str, Any]:
        if name not in getattr(self,"_approved_prompts",frozenset()):
            raise MCPStdioError("prompt outside allowlist")
        await self._verify(request,capability="mcp:prompt_read",
                           payload={"server_id":self.server_id,"name":name})
        result = await self._call("prompts/get",{"name":name,"arguments":{}},3)
        messages=result.get("messages")
        if (not isinstance(messages,list) or len(messages)!=1 or
            not isinstance(messages[0],Mapping) or
            messages[0].get("role")!="user" or
            not isinstance(messages[0].get("content"),Mapping) or
            set(messages[0]["content"])!={"type","text"} or
            messages[0]["content"]["type"]!="text" or
            not isinstance(messages[0]["content"]["text"],str) or
            len(messages[0]["content"]["text"].encode("utf-8"))>16384):
            raise MCPStdioError("unsupported MCP prompt response")
        _deny_obvious_secret_values(result)
        await self._verify(request,capability="mcp:prompt_read",
                           payload={"server_id":self.server_id,"name":name})
        return {"name":name,"text":messages[0]["content"]["text"]}
