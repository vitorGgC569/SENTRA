"""Owned TLS JetStream ingress; signal completion and broker ACK are separate."""
import base64
import json
from sentra_runtime.effect_boundary import current_effect_context
from .workflow_contracts import digest


class NATSWorkflowTransport:
    def __init__(self, *, provider, control, owner, signal_bridge, signal_name, reference_mapper=None):
        if provider.config.owner != owner or signal_bridge.control is not control:
            raise PermissionError("same central authority and TLS provider scope required")
        self.provider, self.control, self.owner, self.bridge = provider, control, owner, signal_bridge
        self.signal_name, self.mapper = signal_name, reference_mapper
        self.handles = {}
        signal_bridge.pull_events = self.pull_events

    def checkpoint(self):
        context = current_effect_context.get()
        if context is None or context.receipt.owner != self.owner:
            raise PermissionError("NATS IO requires admitted observation/effect")
        item = self.control.work_item_info(context.request.work_item_id, self.owner)
        if item.get("metadata", {}).get("workspace_id") != self.provider.config.workspace_id:
            raise PermissionError("NATS WorkItem outside configured workspace")
        context.checkpoint()

    async def pull_events(self, max_messages):
        self.checkpoint()
        result = await self.provider.bridge.call("pull", {"batch": min(max_messages, self.provider.config.batch)})
        events = []
        for message in result["messages"]:
            data = base64.b64decode(message["data"], validate=True)
            if len(data) > self.provider.config.max_payload_bytes:
                raise ValueError("NATS envelope exceeds configured bound")
            from .a2a_provider import decode
            body = decode(data)
            self.provider._validate(body)
            if message["subject"] != self.provider.subject(body):
                raise PermissionError("NATS subject outside pinned scope")
            # Broker data only contains typed references. Mapping never selects
            # capability, workspace, Run, WorkItem, Grant or arbitrary actions.
            payload = self.mapper(body) if self.mapper else {"references": body["references"]}
            if not isinstance(payload, dict):
                raise ValueError("host reference mapper must return a mapping")
            payload = {**payload, "provenance": {"provider": "nats", "event_id": body["event_id"],
                "scope_sha256": self.provider.store.scope, "profile_sha256": self.provider.profile_sha256,
                "stream": self.provider.config.stream, "stream_sequence": message["stream_sequence"],
                "body_sha256": digest(body)}, "chat_trust_inherited": False}
            key = "js:" + digest([self.provider.profile_sha256, body["event_id"]])
            self.bridge.stage(event_key=key, signal_name=self.signal_name, payload=payload)
            self.handles[key] = message["handle"]
            events.append({"event_key": key, "signal_name": self.signal_name, "payload": payload})
        return events

    async def confirm(self, *, event_key, operation_id, work_item_id):
        with self.bridge._db() as db:
            row = db.execute("SELECT * FROM nats_workflow_events WHERE event_key=?", (event_key,)).fetchone()
        operation = self.control.durable.operation_status(operation_id, self.owner)
        progress = operation.get("progress") or {}
        if row is None or row["admitted_operation_id"] != operation_id or progress.get("work_item_id") != work_item_id or progress.get("capability_id") != "workflow:signal":
            raise PermissionError("broker ACK must reference its exact admitted signal")
        from sentra_runtime.contracts import OperationRequest
        from .gate import _fingerprint
        request = OperationRequest(operation_id, progress["principal_id"], progress["machine_id"],
            "workflow:signal", work_item_id, operation["idempotency_key"], self.bridge._intent(dict(row))["arguments"])
        with self.control.durable.lock:
            recorded = self.control.durable._operation_row(operation_id, self.owner)["intent_sha256"]
        if recorded != _fingerprint(request):
            raise PermissionError("NATS signal intent mismatch")
        if operation["state"] != "SUCCEEDED":
            return {"status": "UNCERTAIN", "broker_acknowledged": False, "automatic_replay": False}
        handle = self.handles.get(event_key)
        if handle is None:
            return {"status": "WAITING_REDELIVERY", "broker_acknowledged": False, "signal_replayed": False}
        self.checkpoint()
        result = await self.provider.ack(handle)
        self.handles.pop(event_key, None)
        return {"status": "ACKNOWLEDGED", "provider_ack": result, "operation_id": operation_id}
