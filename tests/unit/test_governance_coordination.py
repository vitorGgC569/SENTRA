from __future__ import annotations

from pathlib import Path

import pytest

from sentra_mcp.services.context import ContextBusService
from sentra_mcp.services.control_plane import ControlPlaneService
from sentra_mcp.services.durable import DurableRunService
from sentra_mcp.services.event_ingress import IngressConflict
from sentra_mcp.services.execution_workspace import ExecutionWorkspaceConflict
from sentra_mcp.services.session_checkpoint import SessionCheckpointConflict


def _services(tmp_path: Path):
    durable = DurableRunService(tmp_path / ".sentra")
    context = ContextBusService(tmp_path / ".sentra")
    control = ControlPlaneService(durable, context)
    return durable, context, control


def test_source_event_ingress_advances_only_contiguous_sequences(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        run = durable.create_run(owner, workspace="project")

        second = control.ingest_source_event(
            owner,
            source_instance_id="edge-worker-a",
            source_epoch="boot-1",
            source_seq=2,
            payload={"kind": "progress", "value": 2},
            run_id=run["run_id"],
            idempotency_key="edge-2",
        )
        assert second["highest_contiguous_source_seq"] == 0

        first = control.ingest_source_event(
            owner,
            source_instance_id="edge-worker-a",
            source_epoch="boot-1",
            source_seq=1,
            payload={"kind": "progress", "value": 1},
            run_id=run["run_id"],
            idempotency_key="edge-1",
        )
        assert first["highest_contiguous_source_seq"] == 2

        replay = control.ingest_source_event(
            owner,
            source_instance_id="edge-worker-a",
            source_epoch="boot-1",
            source_seq=1,
            payload={"kind": "progress", "value": 1},
            run_id=run["run_id"],
            idempotency_key="edge-1",
        )
        assert replay["idempotent_replay"] is True
        assert replay["highest_contiguous_source_seq"] == 2

        with pytest.raises(IngressConflict):
            control.ingest_source_event(
                owner,
                source_instance_id="edge-worker-a",
                source_epoch="boot-1",
                source_seq=1,
                payload={"kind": "different"},
                run_id=run["run_id"],
                idempotency_key="edge-1",
            )

        status = control.source_stream_status(
            owner, source_instance_id="edge-worker-a", source_epoch="boot-1"
        )
        assert status["received_events"] == 2
        assert status["highest_contiguous_source_seq"] == 2
    finally:
        context.close()
        durable.close()


def test_session_checkpoint_is_bound_to_logical_chat_and_idempotent(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        run = durable.create_run(owner, workspace="project")
        control.ensure_agent(
            run["run_id"],
            owner,
            agent_id="agent-a",
            role="implementation",
        )
        durable.bind_chat(
            run["run_id"],
            owner,
            agent_id="agent-a",
            provider="chatgpt",
            conversation_id="conversation-a",
            chat_id="chat-a",
        )

        checkpoint = control.write_session_checkpoint(
            owner,
            run_id=run["run_id"],
            chat_id="chat-a",
            source_instance_id="chatgpt-adapter-a",
            source_epoch="boot-1",
            source_seq=1,
            checkpoint={"summary": "implemented module", "pending": ["tests"]},
            cursor={"provider_turn": 12},
        )
        assert checkpoint["agent_id"] == "agent-a"
        assert checkpoint["provider"] == "chatgpt"
        assert checkpoint["source_seq"] == 1

        replay = control.write_session_checkpoint(
            owner,
            run_id=run["run_id"],
            chat_id="chat-a",
            source_instance_id="chatgpt-adapter-a",
            source_epoch="boot-1",
            source_seq=1,
            checkpoint={"summary": "implemented module", "pending": ["tests"]},
            cursor={"provider_turn": 12},
        )
        assert replay["checkpoint_id"] == checkpoint["checkpoint_id"]

        latest = control.latest_session_checkpoint(
            owner,
            run_id=run["run_id"],
            chat_id="chat-a",
            source_instance_id="chatgpt-adapter-a",
            source_epoch="boot-1",
        )
        assert latest["checkpoint"]["pending"] == ["tests"]
        assert latest["cursor"]["provider_turn"] == 12

        with pytest.raises(SessionCheckpointConflict):
            control.write_session_checkpoint(
                owner,
                run_id=run["run_id"],
                chat_id="chat-a",
                source_instance_id="chatgpt-adapter-a",
                source_epoch="boot-1",
                source_seq=1,
                checkpoint={"summary": "different payload"},
            )

        with pytest.raises(ValueError, match="secret"):
            control.write_session_checkpoint(
                owner,
                run_id=run["run_id"],
                chat_id="chat-a",
                source_instance_id="chatgpt-adapter-a",
                source_epoch="boot-1",
                source_seq=2,
                checkpoint={"token": "plaintext"},
            )
    finally:
        context.close()
        durable.close()


def test_execution_workspace_has_explicit_lifecycle_and_fencing(tmp_path: Path) -> None:
    durable, context, control = _services(tmp_path)
    try:
        owner = "owner-a"
        authority = durable.create_run(owner, workspace="project")
        executor = durable.create_run(owner, workspace="project")
        item = control.create_work_item(
            authority["run_id"], owner, objective="Build isolated candidate"
        )
        xws = control.create_execution_workspace(
            owner,
            authority_run_id=authority["run_id"],
            work_item_id=item["work_item_id"],
            backend="sandbox",
            physical_ref="sandbox:test",
            base_revision="abc123",
        )
        assert xws["state"] == "PROVISIONING"

        ready = control.transition_execution_workspace(
            xws["execution_workspace_id"], owner, "READY"
        )
        assert ready["state"] == "READY"

        acquired = control.acquire_execution_workspace(
            xws["execution_workspace_id"], owner,
            execution_run_id=executor["run_id"], ttl_s=120,
        )
        token = acquired["workspace"]["fencing_token"]
        assert isinstance(token, int)
        assert acquired["workspace"]["state"] == "LEASED"
        assert acquired["workspace"]["lease_run_id"] == executor["run_id"]

        with pytest.raises(ExecutionWorkspaceConflict):
            control.release_execution_workspace(
                xws["execution_workspace_id"], owner,
                fencing_token=token + 1,
            )

        dirty = control.release_execution_workspace(
            xws["execution_workspace_id"], owner,
            fencing_token=token, dirty=True,
        )
        assert dirty["state"] == "DIRTY"
        assert dirty["fencing_token"] is None

        validating = control.transition_execution_workspace(
            xws["execution_workspace_id"], owner, "VALIDATING",
            current_revision="def456",
        )
        assert validating["current_revision"] == "def456"
        promoting = control.transition_execution_workspace(
            xws["execution_workspace_id"], owner, "PROMOTING"
        )
        promoted = control.transition_execution_workspace(
            xws["execution_workspace_id"], owner, "PROMOTED"
        )
        assert promoting["state"] == "PROMOTING"
        assert promoted["state"] == "PROMOTED"
    finally:
        context.close()
        durable.close()
