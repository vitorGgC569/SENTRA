"""Pulso subordinate runtimes: Temporal + LangGraph adapters.

Future validation only (not executed during integral implementation).
Fake clients implement the documented duck-typed surfaces; no live
Temporal server or LangGraph deployment is required. Admission is
simulated by installing a CentralEffectContext-compatible stub through
monkeypatched context — see helpers below.
"""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from sentra_interop.workflow_runtime import (
    LangGraphRuntimeAdapter, RuntimeScope, RuntimeUnavailable,
    SubordinateRuntimeAdapter, TemporalRuntimeAdapter)


def _scope():
    return RuntimeScope(owner="owner1", run_id="run1", work_item_id="wi1",
                        principal_id="agent1", machine_id="m1")


class _FakeReceipt:
    def __init__(self, owner="owner1", run_id="run1", operation_id="op1"):
        self.owner, self.run_id, self.operation_id = owner, run_id, operation_id


class _FakeContext:
    def __init__(self, scope):
        self.receipt = _FakeReceipt(scope.owner, scope.run_id)
        self.request = SimpleNamespace(work_item_id=scope.work_item_id,
                                       principal_id=scope.principal_id)
        self.checkpointed = 0

    def checkpoint(self):
        self.checkpointed += 1


@contextmanager
def _admission(monkeypatch, scope):
    context = _FakeContext(scope)

    def fake_admission(self, scope_arg):
        receipt = context.receipt
        if receipt.owner != scope_arg.owner or receipt.run_id != scope_arg.run_id:
            raise PermissionError("scope mismatch")
        context.checkpoint()
        return context

    monkeypatch.setattr(SubordinateRuntimeAdapter, "_admission", fake_admission)
    try:
        yield context
    finally:
        pass


class FakeTemporalHandle:
    def __init__(self, workflow_id):
        self.workflow_id = workflow_id
        self.run_id = "t-run-1"
        self.signalled: list = []
        self.cancelled = False

    async def signal(self, name, payload):
        self.signalled.append((name, payload))

    async def cancel(self):
        self.cancelled = True

    async def describe(self):
        status = SimpleNamespace(name="RUNNING")
        return SimpleNamespace(status=status)


class FakeTemporalClient:
    sdk_version = "1.2.3-test"

    def __init__(self):
        self.handles: dict[str, FakeTemporalHandle] = {}

    async def start_workflow(self, workflow_type, inputs, *, id,
                             task_queue, id_reuse_policy, memo):
        assert id_reuse_policy == "reject_duplicate"
        handle = FakeTemporalHandle(id)
        self.handles[id] = handle
        return handle

    def get_workflow_handle(self, workflow_id):
        return self.handles.setdefault(workflow_id,
                                       FakeTemporalHandle(workflow_id))


class FakeGraphState:
    def __init__(self, tasks=(), next_steps=("step",), values=None):
        self.tasks = list(tasks)
        self.next = list(next_steps)
        self.values = values or {"k": "v"}


class FakeLangGraphClient:
    sdk_version = "0.0.0-test"

    def __init__(self):
        self.threads: dict[str, dict] = {}

    async def ainvoke(self, inputs, config):
        thread = config["configurable"]["thread_id"]
        entry = self.threads.setdefault(thread, {"values": {"k": "v"}})
        if isinstance(inputs, dict):
            entry["values"].update(inputs)
        return dict(entry["values"])
    async def aget_state(self, config):
        thread = config["configurable"]["thread_id"]
        entry = self.threads.get(thread, {"values": {"k": "v"}})
        return FakeGraphState(values=dict(entry["values"]))

    async def aupdate_state(self, config, values):
        thread = config["configurable"]["thread_id"]
        entry = self.threads.setdefault(thread, {"values": {}})
        entry["values"].update(values)


def test_temporal_configure_requires_client(tmp_path):
    adapter = TemporalRuntimeAdapter(str(tmp_path / "rt.sqlite3"),
                                     workspace=str(tmp_path))
    with pytest.raises(RuntimeUnavailable):
        adapter.configure(owner="owner1", scope=_scope(), server="tls://t:7233",
                          scope_name="default", target_name="wf-type",
                          sdk_client=None, sdk_name="temporalio",
                          sdk_version="1.2.3-test", worker_version="w1",
                          definition_id="doc", definition_version="v1",
                          operator_approved=True)


def test_temporal_start_signal_observe(tmp_path, monkeypatch):
    adapter = TemporalRuntimeAdapter(str(tmp_path / "rt.sqlite3"),
                                     workspace=str(tmp_path))
    client = FakeTemporalClient()
    scope = _scope()
    record = adapter.configure(
        owner="owner1", scope=scope, server="tls://temporal:7233",
        scope_name="default", target_name="mirror-workflow",
        sdk_client=client, sdk_name="temporalio", sdk_version="1.2.3-test",
        worker_version="w1", definition_id="doc", definition_version="v1",
        operator_approved=True)
    assert record["binding_id"].startswith("rt-")
    with _admission(monkeypatch, scope):
        started = asyncio.run(adapter.start(
            scope, workflow_id="wf1", occurrence="occ1", inputs={"a": 1}))
        assert started["status"] == "STARTED"
        assert started["replayed_effect"] is False
        signalled = asyncio.run(adapter.signal(
            scope, workflow_id="wf1", occurrence="occ1", name="sentra_advance",
            payload={"cursor": 2}))
        assert signalled["status"] == "SIGNALLED"
        observed = asyncio.run(adapter.observe(
            scope, workflow_id="wf1", occurrence="occ1"))
        assert observed["status"] in {"RUNNING", "UNCERTAIN"}
        cancelled = asyncio.run(adapter.cancel(
            scope, workflow_id="wf1", occurrence="occ1"))
        assert cancelled["status"] == "CANCEL_REQUESTED"
    assert len(adapter.external_ids(record["binding_id"])) >= 1


def test_temporal_version_pin_conflict(tmp_path):
    adapter = TemporalRuntimeAdapter(str(tmp_path / "rt.sqlite3"),
                                     workspace=str(tmp_path))
    client = FakeTemporalClient()
    with pytest.raises(Exception):
        adapter.configure(
            owner="owner1", scope=_scope(), server="tls://temporal:7233",
            scope_name="default", target_name="mirror-workflow",
            sdk_client=client, sdk_name="temporalio", sdk_version="9.9.9",
            worker_version="w1", definition_id="doc", definition_version="v1",
            operator_approved=True)


def test_langgraph_start_advance_fork(tmp_path, monkeypatch):
    adapter = LangGraphRuntimeAdapter(str(tmp_path / "rt.sqlite3"),
                                      workspace=str(tmp_path))
    client = FakeLangGraphClient()
    scope = _scope()
    adapter.configure(
        owner="owner1", scope=scope, server="in-process",
        scope_name="default", target_name="doc-graph",
        sdk_client=client, sdk_name="langgraph", sdk_version="0.0.0-test",
        worker_version="w1", definition_id="doc", definition_version="v1",
        operator_approved=True)
    with _admission(monkeypatch, scope):
        started = asyncio.run(adapter.start(
            scope, workflow_id="wf1", occurrence="occ1", inputs={"a": 1}))
        assert started["status"] == "STARTED"
        assert started["history_rewritten"] is not True
        advanced = asyncio.run(adapter.advance(
            scope, workflow_id="wf1", occurrence="occ1"))
        assert advanced["status"] in {"ADVANCED", "WAITING_INTERRUPT"}
        forked = asyncio.run(adapter.fork(
            scope, workflow_id="wf1", occurrence="occ1",
            new_occurrence="occ2"))
        assert forked["status"] == "FORKED"
        assert forked["history_rewritten"] is False
        observed = asyncio.run(adapter.observe(
            scope, workflow_id="wf1", occurrence="occ2"))
        assert observed["status"] in {"READY", "SUCCEEDED", "WAITING_INTERRUPT"}


def test_langgraph_resume_needs_approval(tmp_path, monkeypatch):
    adapter = LangGraphRuntimeAdapter(str(tmp_path / "rt.sqlite3"),
                                      workspace=str(tmp_path))
    scope = _scope()
    adapter.configure(
        owner="owner1", scope=scope, server="in-process",
        scope_name="default", target_name="doc-graph",
        sdk_client=FakeLangGraphClient(), sdk_name="langgraph",
        sdk_version="0.0.0-test", worker_version="w1",
        definition_id="doc", definition_version="v1",
        operator_approved=True)
    with _admission(monkeypatch, scope), pytest.raises(PermissionError):
        asyncio.run(adapter.resume(scope, workflow_id="wf1", occurrence="occ1",
                                   values={"ok": True}))


def test_runtime_retry_kwargs(tmp_path):
    adapter = TemporalRuntimeAdapter(str(tmp_path / "rt.sqlite3"),
                                     workspace=str(tmp_path))
    adapter.configure(
        owner="owner1", scope=_scope(), server="tls://temporal:7233",
        scope_name="default", target_name="mirror-workflow",
        sdk_client=FakeTemporalClient(), sdk_name="temporalio",
        sdk_version="1.2.3-test", worker_version="w1",
        definition_id="doc", definition_version="v1",
        operator_approved=True)
    kwargs = adapter.retry_kwargs()
    assert kwargs["maximum_attempts"] == 3
    assert "ACCEPTANCE_FAILED" in kwargs["non_retryable_error_types"]
