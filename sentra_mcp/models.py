"""Typed wire-facing models used by SENTRA MCP."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = "2026-07-28"
SERVER_NAME = "sentra-mcp"
SERVER_VERSION = "2.0.0"
CAPABILITY_VERSION = "2"


class ErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class ResponseMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    server_name: str = SERVER_NAME
    server_version: str = SERVER_VERSION


class ResponseEnvelope(BaseModel):
    """Stable JSON envelope returned by SENTRA tools."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = PROTOCOL_VERSION
    ok: bool
    data: dict[str, Any] | None = None
    error: ErrorPayload | None = None
    meta: ResponseMeta = Field(default_factory=ResponseMeta)

    @classmethod
    def success(cls, data: dict[str, Any]) -> "ResponseEnvelope":
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, code: str, message: str) -> "ResponseEnvelope":
        return cls(ok=False, error=ErrorPayload(code=code, message=message))

    def to_stable_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


class CapabilityMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_version: str = CAPABILITY_VERSION
    protocol_version: str = PROTOCOL_VERSION
    transports: tuple[str, ...] = ("stdio", "streamable-http")
    health_tool: str = "sentra_health"
