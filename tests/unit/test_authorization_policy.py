from __future__ import annotations

from pathlib import Path

from sentra_mcp.services.authorization import AuthorizationService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.governance import GovernanceService
from sentra_mcp.tools import governance as governance_tools


def test_authorization_is_single_grant_authority_with_scope_and_conditions(tmp_path: Path) -> None:
    state = tmp_path / ".sentra"
    auth = AuthorizationService(state)
    durable = DurableRunService(state)
    governance = GovernanceService(state, durable=durable)
    owner = "owner-a"
    durable.create_run(owner, run_id="run-project-1")
    durable.bind_chat("run-project-1", owner, project_id="project-1")
    governance.create_work_item(
        "run-project-1", owner, objective="trusted item", work_item_id="WI-1"
    )

    grant = auth.grant(
        owner,
        principal_type="agent",
        principal_id="builder",
        capability="workspace.write",
        scope_type="project",
        scope_id="project-1",
        conditions={"workspace_permission": "write", "max_actual_cost": 2.0},
    )
    assert grant["effect"] == "allow"

    allowed = auth.authorize(
        owner,
        principal_type="agent",
        principal_id="builder",
        capability="workspace.write",
        scope_type="work_item",
        scope_id="WI-1",
        ancestors={"project": ["project-1"]},
        context={"workspace_permissions": ["read", "write"], "actual_cost": 1.5},
    )
    assert allowed["allowed"] is True
    assert allowed["grant_id"] == grant["grant_id"]

    denied_cost = auth.authorize(
        owner,
        principal_type="agent",
        principal_id="builder",
        capability="workspace.write",
        scope_type="work_item",
        scope_id="WI-1",
        ancestors={"project": ["project-1"]},
        context={"workspace_permissions": ["read", "write"], "actual_cost": 3.0},
    )
    assert denied_cost["allowed"] is False

    denied_scope = auth.authorize(
        owner,
        principal_type="agent",
        principal_id="builder",
        capability="workspace.write",
        scope_type="project",
        scope_id="project-2",
        context={"workspace_permissions": ["read", "write"]},
    )
    assert denied_scope["allowed"] is False

    auth.revoke(grant["grant_id"], owner)
    revoked = auth.authorize(
        owner,
        principal_type="agent",
        principal_id="builder",
        capability="workspace.write",
        scope_type="project",
        scope_id="project-1",
        context={"workspace_permissions": ["read", "write"]},
    )
    assert revoked["allowed"] is False
    durable.close()


def test_project_grant_ignores_spoofed_work_item_ancestors(tmp_path: Path) -> None:
    state = tmp_path / ".sentra"
    auth = AuthorizationService(state)
    durable = DurableRunService(state)
    governance = GovernanceService(state, durable=durable)
    owner = "owner-a"

    auth.grant(
        owner,
        principal_type="plugin",
        principal_id="plugin-a",
        capability="plugin.read",
        scope_type="project",
        scope_id="private-project",
    )
    durable.create_run(owner, run_id="run-unrelated")
    durable.bind_chat("run-unrelated", owner, project_id="other-project")
    governance.create_work_item(
        "run-unrelated", owner, objective="unrelated", work_item_id="WI-unrelated"
    )

    decision = auth.authorize(
        owner,
        principal_type="plugin",
        principal_id="plugin-a",
        capability="plugin.read",
        scope_type="work_item",
        scope_id="WI-unrelated",
        ancestors={"project": ["private-project"]},
    )

    assert decision["allowed"] is False
    assert decision["grant_id"] is None
    durable.close()


def test_governance_tool_binds_local_owner_shortcut_to_authenticated_local_principal() -> None:
    source = Path(governance_tools.__file__).read_text(encoding="utf-8")
    assert 'authorization_principal(ctx)[0] == "local-operator"' in source


def test_authorization_wildcards_and_local_owner_shortcut(tmp_path: Path) -> None:
    auth = AuthorizationService(tmp_path / ".sentra")
    owner = "owner-a"
    auth.grant(
        owner,
        principal_type="plugin",
        principal_id="plug",
        capability="artifact.*",
    )
    assert auth.authorize(
        owner,
        principal_type="plugin",
        principal_id="plug",
        capability="artifact.read",
    )["allowed"] is True
    assert auth.authorize(
        owner,
        principal_type="plugin",
        principal_id="plug",
        capability="secret.read",
    )["allowed"] is False

    local = auth.authorize(
        owner,
        principal_type="user",
        principal_id=owner,
        capability="anything",
        local_owner=True,
    )
    assert local == {
        "allowed": True,
        "source": "local_owner",
        "grant_id": None,
        "reason": "local owner authority",
    }
