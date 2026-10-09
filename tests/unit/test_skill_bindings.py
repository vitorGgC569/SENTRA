from __future__ import annotations

from pathlib import Path

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.context_projection import ControlPlaneContextBridge
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService


def test_versioned_skill_binding_projects_into_agent_context(tmp_path: Path) -> None:
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra")
    control = ControlPlaneService(durable, context)
    try:
        owner = "owner"
        run = durable.create_run(owner, workspace="project")
        seat = "run:validator.security"
        agent_id = ControlPlaneContextBridge._agent_id(seat)
        control.ensure_agent(
            run["run_id"], owner,
            agent_id=agent_id, role="validator.security",
        )
        first = control.install_skill(
            owner,
            name="secure-review",
            version="1.0.0",
            content="Require deterministic evidence before approving security claims.",
        )
        control.install_skill(
            owner,
            name="unbound-skill",
            version="1.0.0",
            content="THIS MUST NOT APPEAR",
        )
        binding = control.skill_bind(
            first["skill_id"], owner,
            run_id=run["run_id"], agent_id=agent_id, priority=10,
        )
        assert binding["enabled"] is True

        bridge = ControlPlaneContextBridge(control, owner, max_chars=8000)
        batch = bridge.prepare(
            run_id=run["run_id"],
            role="validator.security",
            task_id="T-1",
            seat=seat,
        )
        assert "[SKILL secure-review@1.0.0" in batch.text
        assert "Require deterministic evidence" in batch.text
        assert "THIS MUST NOT APPEAR" not in batch.text
    finally:
        context.close()
        durable.close()


def test_skill_projection_is_bounded(tmp_path: Path) -> None:
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra")
    control = ControlPlaneService(durable, context)
    try:
        owner = "owner"
        run = durable.create_run(owner, workspace="project")
        agent = control.ensure_agent(
            run["run_id"], owner,
            agent_id="agent-a", role="worker",
        )
        skill = control.install_skill(
            owner,
            name="large",
            version="1",
            content="x" * 10000,
        )
        control.skill_bind(
            skill["skill_id"], owner,
            run_id=run["run_id"], agent_id=agent["agent_id"],
        )
        projection = control.agent_skills(
            run["run_id"], owner, agent_id=agent["agent_id"], max_chars=1200
        )
        assert projection["truncated"] is True
        assert projection["chars"] <= 1200
        assert "SKILL TRUNCATED" in projection["text"]
    finally:
        context.close()
        durable.close()
