import pytest
from pathlib import Path
from workspace.tool_gateway import ToolGateway, Permission, SecurityPolicyError


def test_tool_gateway_least_privilege(tmp_path):
    gateway = ToolGateway(tmp_path)

    # Planner only has READ_WORKSPACE; attempting to apply patch must fail
    with pytest.raises(SecurityPolicyError, match="not authorized"):
        gateway.check_permission("planner", Permission.APPLY_PATCH)

    # Executor is authorized to apply patches
    gateway.check_permission("executor", Permission.APPLY_PATCH)


@pytest.mark.asyncio
async def test_tool_gateway_idempotency_and_path_traversal(tmp_path):
    gateway = ToolGateway(tmp_path)

    # Path traversal check
    with pytest.raises(SecurityPolicyError, match="Path traversal detected"):
        await gateway.read_file("executor", "../../secret.env")

    # Untrusted data injection protection
    sanitized = gateway.sanitize_untrusted_data("DROP TABLE; ```malicious```")
    assert "<UNTRUSTED_EXTERNAL_DATA>" in sanitized
    assert "'''malicious'''" in sanitized
