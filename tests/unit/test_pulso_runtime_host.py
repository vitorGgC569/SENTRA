"""Pulso runtime provider host: factory/config/restore/catalog/dispatch/submit.

Future validation only (not executed during integral implementation).
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from sentra_interop.workflow_runtime import RuntimeScope, RuntimeUnavailable
from sentra_interop.workflow_runtime_host import (
    PulsoWorkflowExecutor, RuntimeHostDenied, RuntimeProviderHost)


def _scope():
    return RuntimeScope(owner="owner1", run_id="run1", work_item_id="wi1",
                        principal_id="agent1", machine_id="m1")


class FakeTemporalHandle:
    def __init__(self, workflow_id):
        self.workflow_id = workflow_id
        self.run_id = "t-run-1"
        self.signalled: list = []

    async def signal(self, name, payload):
        self.signalled.append((name, payload))

    async def cancel(self):
        pass

    async def describe(self):
        return SimpleNamespace(status=SimpleNamespace(name="RUNNING"))


class FakeTemporalClient:
    sdk_version = "1.2.3-test"

    def __init__(self):
        self.handles: dict[str, FakeTemporalHandle] = {}

    async def start_workflow(self, workflow_type, inputs, *, id,
                             task_queue, id_reuse_policy, retry_policy, execution_timeout, memo):
        assert retry_policy.maximum_attempts == 1
        handle = FakeTemporalHandle(id)
        self.handles[id] = handle
        return handle

    def get_workflow_handle(self, workflow_id, *, first_execution_run_id=None):
        assert first_execution_run_id in (None, "t-run-1")
        return self.handles.setdefault(workflow_id,
                                       FakeTemporalHandle(workflow_id))


class FakeMachineHost:
    def __init__(self):
        def work_item_info(work_item_id, owner):
            if (work_item_id, owner) != ("wi1", "owner1"):
                raise FileNotFoundError("work item outside test authority scope")
            return {"work_item_id": work_item_id, "run_id": "run1",
                    "assignee_agent_id": "agent1"}
        self.control = SimpleNamespace(work_item_info=work_item_info)
        self.owner = "owner1"


def _host(tmp_path, **kwargs):
    host = RuntimeProviderHost(
        FakeMachineHost(), database=str(tmp_path / "host.sqlite3"),
        workspace=str(tmp_path), **kwargs)
    host.register_factory("test-temporal",
                          lambda options, secrets: FakeTemporalClient())
    return host


def _configure(host, **overrides):
    params = dict(scope=_scope(), provider="temporal",
                  server="tls://temporal:7233", scope_name="default",
                  target_name="mirror-workflow", sdk_name="temporalio",
                  sdk_version="1.2.3-test", worker_version="w1",
                  definition_id="doc", definition_version="v1",
                  factory="test-temporal", factory_options={"address": "x"},
                  operator_approved=True)
    params.update(overrides)
    return host.configure(**params)


def test_host_configure_catalog_restore(tmp_path):
    host = _host(tmp_path)
    record = _configure(host)
    assert record["binding_id"].startswith("rt-")
    assert record["factory"] == "test-temporal"
    catalog = host.catalog()
    assert [entry["binding_id"] for entry in catalog] == [record["binding_id"]]
    assert "address" not in str(catalog)
    host._adapters.clear()
    restored = asyncio.run(host.arestore(record["binding_id"]))
    assert restored._config is not None
    with pytest.raises(FileNotFoundError):
        asyncio.run(host.arestore("rt-missing"))


def test_host_rejects_secret_options_and_unknown_factory(tmp_path):
    host = _host(tmp_path)
    with pytest.raises(RuntimeHostDenied):
        _configure(host, factory_options={"api_token": "zzz"})
    with pytest.raises(RuntimeHostDenied):
        _configure(host, factory="nope")
    with pytest.raises(PermissionError):
        _configure(host, operator_approved=False)


def test_host_dispatch_request_shape(tmp_path):
    host = _host(tmp_path)
    record = _configure(host)
    intent = host.dispatch_request(
        record["binding_id"], operation="signal", workflow_id="wf1",
        occurrence="occ1", arguments={"signal_name": "tick"})
    assert intent["capability_id"] == "runtime:temporal:signal"
    assert intent["binding_id"] == record["binding_id"]
    assert intent["effects_started"] is False
    with pytest.raises(RuntimeHostDenied):
        host.dispatch_request(record["binding_id"], operation="fly",
                              workflow_id="wf1", occurrence="occ1")


def test_host_submit_requires_admission(tmp_path):
    host = _host(tmp_path)
    record = _configure(host)
    with pytest.raises(PermissionError):
        asyncio.run(host.submit(record["binding_id"], operation="signal",
                                scope=_scope(), workflow_id="wf1",
                                occurrence="occ1",
                                payload={"signal_name": "x"}))


def test_host_submit_inside_admission(tmp_path, monkeypatch):
    from sentra_interop.workflow_runtime import SubordinateRuntimeAdapter
    from pulso_test_sdk import install_temporal_value_objects
    install_temporal_value_objects(monkeypatch)

    class _Receipt:
        owner, run_id, operation_id = "owner1", "run1", "op1"

    class _Context:
        receipt = _Receipt()
        request = SimpleNamespace()
        def checkpoint(self):
            pass

    context = _Context()
    monkeypatch.setattr(SubordinateRuntimeAdapter, "_admission",
                        lambda self, scope: context)
    host = _host(tmp_path)
    record = _configure(host)
    asyncio.run(host.restore(record["binding_id"]).start(
        _scope(), workflow_id="wf1", occurrence="occ1", inputs={"fixture":1}))
    from sentra_runtime.contracts import OperationRequest
    from sentra_runtime.provider_content import text_digest
    payload = {"cursor": 1}
    context.request = OperationRequest("op1", "agent1", "m1", "runtime:temporal:signal", "wi1", "key1",
        {"binding_id": record["binding_id"], "workflow_id": "wf1", "occurrence": "occ1",
         "name": "tick", "payload_sha256": text_digest(payload)})
    outcome = asyncio.run(host.submit(
        record["binding_id"], operation="signal", scope=_scope(),
        workflow_id="wf1", occurrence="occ1",
        signal_name="tick", payload=payload))
    assert outcome["status"] == "SIGNALLED"
    assert outcome["replayed_effect"] is False


def test_workflow_executor_drives_admitted_request(tmp_path):
    seen = {}

    class FakeWorker:
        def host_handler(self, request):
            seen["capability"] = request.capability_id
            return {"workflow_id": "wf1", "status": "READY"}

    executor = PulsoWorkflowExecutor(
        bridge_lookup=lambda workflow_id, ns: FakeWorker())
    request = SimpleNamespace(
        capability_id="workflow:advance",
        arguments={"workflow_id": "wf1", "namespace": ""})
    outcome = asyncio.run(executor.execute(
        request=request,
        intent={"capability_id": "workflow:advance",
                "arguments": {"workflow_id": "wf1", "namespace": ""}}))
    assert outcome["value"]["status"] == "READY"
    assert seen["capability"] == "workflow:advance"
    bad = SimpleNamespace(capability_id="workflow:cancel", arguments={})
    with pytest.raises(RuntimeHostDenied):
        asyncio.run(executor.execute(
            request=bad,
            intent={"capability_id": "workflow:advance",
                    "arguments": {"workflow_id": "wf1"}}))
    with pytest.raises(RuntimeHostDenied):
        asyncio.run(PulsoWorkflowExecutor().execute(
            request=request, intent={"capability_id": "workflow:advance",
                                     "arguments": {}}))
