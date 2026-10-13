"""Trusted root resolver: public domain parameters -> executed central receipt."""
import uuid
from .workflow_shell import PulsoShellDenied


def server_operation_id(ctx, capability):
    return "pulso-" + uuid.uuid5(uuid.NAMESPACE_URL,
        "sentra:pulso:" + ctx["owner"] + ":" + ctx["project_id"] + ":" +
        ctx["request_key"] + ":" + capability).hex


class PulsoMachineResolver:
    """machine_lookup(ctx, domain, params) resolves machine + WorkItem server-side.

    lookup returns {machine_id,work_item_id}; it must use configured project
    routing/assignment. No request can supply an authority identity to lookup.
    MachineHost verifies the resulting owner/agent/Run/workspace/machine binding.
    """
    def __init__(self, machine_host, *, domain, machine_lookup, channel_bridge=None):
        if domain not in {"workflow", "runtime", "terminal", "channel"} or not callable(machine_lookup):
            raise ValueError("trusted domain and machine lookup required")
        self.host, self.domain, self.lookup = machine_host, domain, machine_lookup
        self.channel_bridge = channel_bridge

    def __call__(self, action, ctx, params):
        if ctx["owner"] != self.host.owner:
            raise PermissionError("resolver owner mismatch")
        parameters = dict(params)
        binding = self.lookup(ctx, self.domain, parameters)
        if not isinstance(binding, dict) or not binding.get("machine_id") or not binding.get("work_item_id"):
            raise PulsoShellDenied("configured machine assignment unavailable")
        if self.domain == "workflow":
            operation = parameters.pop("intent_kind", action)
            operation = "observe" if action == "observe" else "output" if action == "output" else operation
            if "signal_name" in parameters:
                parameters["name"] = parameters.pop("signal_name")
            cap = "workflow:" + operation
        elif self.domain == "runtime":
            provider = parameters.pop("provider")
            operation = parameters.pop("operation", "observe" if action == "observe" else "")
            selected_binding = parameters.pop("binding_id", None)
            factory = self.host._factories.get(binding["machine_id"])
            if selected_binding is not None and selected_binding != getattr(factory, "binding_id", None):
                raise PermissionError("configured runtime binding mismatch")
            cap = "runtime:" + provider + ":" + operation
        elif self.domain == "terminal":
            operation = parameters.pop("operation", "read" if action == "observe" else "write")
            cap = "terminal:" + operation
        else:
            cap = "channel:send"
            staged = parameters.get("staged")
            if self.channel_bridge is None or not isinstance(staged, dict):
                raise PulsoShellDenied("staged notification resolver unavailable")
            parameters = self.channel_bridge.resolve_send(
                ctx["owner"], dedupe_key=parameters["dedupe_key"])
            from .workflow_contracts import digest
            ctx = {**ctx, "request_key": "notification-" + digest([ctx["owner"], ctx["project_id"], parameters["dedupe_key"]])}
            dedupe_key = parameters["dedupe_key"]
            parameters = {key: parameters[key] for key in ("connector_id", "recipient", "text")}
        parameters.pop("target_operation_id", None)
        result = self.host.dispatch(workspace_id=ctx["project_id"],
            work_item_id=binding["work_item_id"], machine_id=binding["machine_id"],
            capability_id=cap, operation_id=server_operation_id(ctx, cap),
            arguments=parameters, idempotency_key="pulso:" + ctx["request_key"])
        if self.domain == "channel":
            self.channel_bridge.note_provider_ack(owner=ctx["owner"], dedupe_key=dedupe_key, operation_id=result["operation_id"])
        from sentra_executors.operation_receipts import HumanReceiptViews
        receipt = HumanReceiptViews(self.host.control).human_receipt(
            ctx["owner"], result["operation_id"], work_item_id=binding["work_item_id"])
        return {**result, "receipt": receipt}
