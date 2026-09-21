from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from mcp import Client

from sentra_mcp.audit import AuditLogger
from sentra_mcp.config import ALLOWED_TRANSPORTS, MCPConfig, PROJECT_ROOT
from sentra_mcp.errors import ConfigurationError, sanitize_error
from sentra_mcp.main import config_from_args, parser
from sentra_mcp.models import PROTOCOL_VERSION, ResponseEnvelope
from sentra_mcp.server import SentraMCPServer


def test_secure_defaults_are_local_and_bounded() -> None:
    config = MCPConfig()

    assert config.allowed_roots == (PROJECT_ROOT.resolve(),)
    assert config.transport == "stdio"
    assert config.host == "127.0.0.1"
    assert config.allow_non_loopback is False
    assert config.max_read_bytes > 0
    assert config.max_write_bytes > 0
    assert config.max_output_bytes > 0
    assert config.max_processes > 0
    assert config.blocked_commands


def test_non_loopback_host_requires_explicit_authorization() -> None:
    with pytest.raises(ConfigurationError, match="non-loopback"):
        MCPConfig(host="0.0.0.0")

    with pytest.raises(ConfigurationError, match="requires OAuth"):
        MCPConfig(host="0.0.0.0", allow_non_loopback=True)

    authorized = MCPConfig(
        host="0.0.0.0",
        allow_non_loopback=True,
        oauth_issuer_url="https://auth.example.test/",
        oauth_resource_url="https://sentra.example.test/mcp",
        oauth_introspection_url="https://auth.example.test/oauth2/introspect",
    )
    assert authorized.host == "0.0.0.0"
    assert authorized.oauth_enabled is True


def test_secret_redaction_and_audit_jsonl(tmp_path: Path) -> None:
    message = "Authorization: Bearer top-secret api_key=abc123 password=hunter2"
    sanitized = sanitize_error(message)

    assert "top-secret" not in sanitized
    assert "abc123" not in sanitized
    assert "hunter2" not in sanitized
    assert sanitized.count("[REDACTED]") == 3

    audit_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(audit_path)
    logger.emit("test", "failed", {"token": "raw-token", "message": message})
    record = json.loads(audit_path.read_text(encoding="utf-8"))
    assert record["details"]["token"] == "[REDACTED]"
    assert "raw-token" not in audit_path.read_text(encoding="utf-8")
    assert "top-secret" not in audit_path.read_text(encoding="utf-8")


def test_response_envelope_has_stable_json() -> None:
    envelope = ResponseEnvelope.success({"z": 1, "a": 2})
    encoded = envelope.to_stable_json()

    assert encoded == envelope.to_stable_json()
    assert encoded == (
        '{"data":{"a":2,"z":1},"error":null,'
        '"meta":{"server_name":"sentra-mcp","server_version":"3.0.0"},'
        '"ok":true,"schema_version":"2026-07-28"}'
    )


def test_stdio_is_configurable_and_no_extra_transport_is_exposed() -> None:
    assert set(ALLOWED_TRANSPORTS) == {"stdio", "streamable-http"}

    env_config = MCPConfig.from_env({"SENTRA_MCP_TRANSPORT": "stdio"})
    args = parser().parse_args(["--transport", "stdio"])
    cli_config = config_from_args(args, env_config)
    assert cli_config.transport == "stdio"

    with pytest.raises(ConfigurationError, match="unsupported transport"):
        MCPConfig(transport="sse")


def test_discovery_list_and_call_tool_in_process(tmp_path: Path) -> None:
    async def probe() -> None:
        runtime = SentraMCPServer(MCPConfig(audit_log=tmp_path / "audit.jsonl"))

        async with Client(runtime.mcp) as client:
            assert client.protocol_version == PROTOCOL_VERSION
            tools = await client.list_tools()
            tool_names = [tool.name for tool in tools.tools]
            assert "sentra_health" in tool_names

            result = await client.call_tool("sentra_health", {})
            assert result.is_error is False
            assert result.structured_content is not None
            assert result.structured_content["schema_version"] == PROTOCOL_VERSION
            assert result.structured_content["ok"] is True
            capabilities = result.structured_content["data"]["capabilities"]
            assert capabilities["protocol_version"] == PROTOCOL_VERSION
            assert capabilities["transports"] == ["stdio", "streamable-http"]

        assert (tmp_path / "audit.jsonl").is_file()

    asyncio.run(probe())
