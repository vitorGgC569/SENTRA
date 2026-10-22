"""Real central receipt matching; the synthetic broker never certifies NATS IO."""
import asyncio
from types import SimpleNamespace

import pytest

from pulso_test_authority import make_authority
from sentra_interop.workflow_nats import NATSWorkflowSignalBridge
from sentra_interop.workflow_nats_transport import NATSWorkflowTransport
from sentra_runtime.contracts import OperationRequest


def test_nats_ack_matches_runtime_fingerprint_and_refuses_changed_intent(tmp_path):
    center = make_authority(tmp_path / "central", ("workflow:signal", "channel:receipt"))
    calls = []
    async def ack(handle):
        calls.append(handle)
        return {"synthetic_ack":True}
    provider = SimpleNamespace(config=SimpleNamespace(owner="owner1", workspace_id="ws1"), ack=ack)
    bridge = NATSWorkflowSignalBridge(str(tmp_path / "nats.sqlite"), workspace=str(tmp_path),
        workflow_id="flow", control=center.control)
    transport = NATSWorkflowTransport(provider=provider, control=center.control, owner="owner1",
        signal_bridge=bridge, signal_name="ready")
    async def signal(request):
        return {"signal_id":request.arguments["signal_id"]}
    async def confirm(request):
        return await transport.confirm(event_key="event-1", operation_id="op-signal", work_item_id="wi1")
    center.bind_provider("workflow:signal", signal)
    center.bind_provider("channel:receipt", confirm)
    try:
        intent = bridge.stage(event_key="event-1", signal_name="ready", payload={"reference":"artifact-1"})
        bridge.mark_admitted("event-1", "op-signal")
        transport.handles["event-1"] = "handle-1"
        request = OperationRequest("op-signal", "agent1", "machine1", "workflow:signal", "wi1", "signal-1", intent["arguments"])
        result = asyncio.run(center.start(request))
        assert result.state == "SUCCEEDED", result
        result = asyncio.run(center.start(OperationRequest("op-confirm", "agent1", "machine1", "channel:receipt", "wi1", "confirm-1", {})))
        assert result.state == "SUCCEEDED", result
        assert result.evidence["payload"]["status"] == "ACKNOWLEDGED"
        assert calls == ["handle-1"]

        intent = bridge.stage(event_key="event-2", signal_name="ready", payload={"reference":"artifact-2"})
        bridge.mark_admitted("event-2", "op-changed")
        transport.handles["event-2"] = "handle-2"
        request = OperationRequest("op-changed", "agent1", "machine1", "workflow:signal", "wi1", "signal-2", {**intent["arguments"], "name":"other"})
        assert asyncio.run(center.start(request)).state == "SUCCEEDED"
        with pytest.raises(PermissionError, match="signal intent mismatch"):
            asyncio.run(transport.confirm(event_key="event-2", operation_id="op-changed", work_item_id="wi1"))
        assert calls == ["handle-1"] and transport.handles["event-2"] == "handle-2"
    finally:
        center.control.durable.close()
