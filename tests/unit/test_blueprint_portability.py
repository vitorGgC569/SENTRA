from __future__ import annotations

from pathlib import Path

import pytest

import sentra_mcp.services.governance as governance_module
from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService


def test_blueprint_dry_run_and_import_remap_identity_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(governance_module, "protect_secret", lambda value: "test:" + value)
    monkeypatch.setattr(
        governance_module, "unprotect_secret",
        lambda value: value.removeprefix("test:"),
    )
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra")
    control = ControlPlaneService(durable, context)
    try:
        source_owner = "owner-source"
        target_owner = "owner-target"
        source = durable.create_run(source_owner, workspace="C:/source/private")
        target = durable.create_run(target_owner, workspace="D:/target/private")

        parent = control.create_goal(
            source["run_id"], source_owner,
            objective="Ship portable governance",
            acceptance_criteria=["No secret values in export"],
        )
        child = control.create_goal(
            source["run_id"], source_owner,
            objective="Implement importer",
            parent_goal_id=parent["goal_id"],
        )
        agent = durable.assign_agent(
            source["run_id"], source_owner,
            role="builder", goal_id=child["goal_id"], agent_id="source-builder",
        )
        work = control.create_work_item(
            source["run_id"], source_owner,
            objective="Build importer",
            goal_id=child["goal_id"],
            assignee_agent_id=agent["agent_id"],
            execution_policy={
                "stages": [{"id": "review", "type": "review", "allow_any_authorized": True}]
            },
        )
        control.create_routine(
            source_owner,
            name="portable-routine",
            trigger_kind="api",
            trigger_spec={"key": "audit"},
            work_template={"objective": "Run imported audit", "goal_id": child["goal_id"]},
        )
        control.install_skill(
            source_owner,
            name="portable-skill",
            version="1.0.0",
            content="# Portable\nUse deterministic evidence.",
        )
        control.register_plugin(
            source_owner,
            manifest={
                "name": "portable-plugin",
                "version": "1.0.0",
                "capabilities": ["read", "write"],
            },
            verified_methods=["capability:read", "capability:write"],
            narrowed_capabilities=["read"],
            trusted_ui=True,
        )
        control.create_secret(
            source_owner,
            name="SOURCE_TOKEN",
            value="must-not-export",
            scope_type="project",
            scope_id="portable",
        )

        blueprint = control.export_blueprint(source["run_id"], source_owner)
        serialized = repr(blueprint)
        assert "must-not-export" not in serialized
        assert "C:/source/private" not in serialized
        assert "conversation_id" not in serialized
        assert "device_id" not in serialized
        assert blueprint["secret_requirements"][0]["name"] == "SOURCE_TOKEN"

        dry = control.import_blueprint(
            target["run_id"], target_owner, blueprint=blueprint, dry_run=True
        )
        assert dry["dry_run"] is True
        assert dry["counts"]["goals"] == 2
        assert dry["counts"]["work_items"] == 1
        assert dry["trust_policy"]["secret_values_imported"] is False
        assert control.list_work_items(target_owner, run_id=target["run_id"])["items"] == []

        applied = control.import_blueprint(
            target["run_id"], target_owner, blueprint=blueprint, dry_run=False
        )
        assert applied["created"] == {
            "goals": 2,
            "agents": 1,
            "work_items": 1,
            "routines": 1,
            "skills": 1,
            "plugins": 1,
        }
        imported = control.list_work_items(
            target_owner, run_id=target["run_id"]
        )["items"]
        assert len(imported) == 1
        assert imported[0]["work_item_id"] != work["work_item_id"]
        assert imported[0]["assignee_agent_id"] != agent["agent_id"]
        assert imported[0]["state"] == "PENDING"

        target_snapshot = control.governance.portable_snapshot(
            target_owner, run_id=target["run_id"]
        )
        assert target_snapshot["secret_requirements"] == []
        assert target_snapshot["plugins"][0]["name"] == "portable-plugin"
    finally:
        context.close()
        durable.close()


def test_blueprint_rejects_sensitive_runtime_fields(tmp_path: Path) -> None:
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra")
    control = ControlPlaneService(durable, context)
    try:
        owner = "owner"
        target = durable.create_run(owner, workspace="project")
        bad = {
            "kind": "sentra-governance-blueprint",
            "schema_version": 1,
            "contains_secret_values": False,
            "goals": [],
            "agents": [{"role": "builder", "conversation_url": "https://example.invalid/private"}],
            "work_items": [],
            "routines": [],
            "skills": [],
            "plugins": [],
            "secret_requirements": [],
        }
        with pytest.raises(ValueError, match="non-portable/sensitive"):
            control.import_blueprint(
                target["run_id"], owner, blueprint=bad, dry_run=True
            )
    finally:
        context.close()
        durable.close()
