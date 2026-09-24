"""Typed wire-facing models used by SENTRA MCP."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .version import CAPABILITY_VERSION, PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION


class ErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    category: str | None = None
    retryable: bool | None = None
    operation_id: str | None = None
    details: dict[str, Any] | None = None


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
    def failure(
        cls,
        code: str,
        message: str,
        *,
        category: str | None = None,
        retryable: bool | None = None,
        operation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> "ResponseEnvelope":
        return cls(
            ok=False,
            error=ErrorPayload(
                code=code,
                message=message,
                category=category,
                retryable=retryable,
                operation_id=operation_id,
                details=details,
            ),
        )

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
