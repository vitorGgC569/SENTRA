"""Deferred hermetic checks for the owner-approved workspace-files machine.

Run after the coordinated freeze; no host workspace or network side effects.
"""
import asyncio
from types import SimpleNamespace

import pytest

from sentra_executors.rpa import AuthorizedPaths
from sentra_executors.workspace_files import WorkspaceFilesBinding, WorkspaceFilesExecutor


def _scope(tmp_path):
    paths = AuthorizedPaths((str(tmp_path),), (str(tmp_path),))
    bindings = tuple(WorkspaceFilesBinding(capability_id=cap, paths=paths, actions=actions)
                     for cap, actions in (
                         ("workspace:file.read", ("read", "stat")),
                         ("workspace:file.write", ("write", "edit")),
                         ("workspace:file.delete", ("delete",))))
    executor = WorkspaceFilesExecutor(machine_id="test-files", owner_principal_id="test-dot",
                                      bindings=bindings, policy=lambda request: None)
    return executor, {b.capability_id: b for b in bindings}


def _call(executor, binding, values):
    request = SimpleNamespace(arguments=values)
    return executor._execute(binding, executor._validate(request, binding))


def test_file_lifecycle_and_repeated_reads(tmp_path):
    executor, caps = _scope(tmp_path)
    read, write, delete = (caps["workspace:file." + kind] for kind in ("read", "write", "delete"))
    assert _call(executor, read, {"action": "stat", "path": "sentra_teste.txt"})["exists"] is False
    _call(executor, write, {"action": "write", "path": "sentra_teste.txt",
                            "content": "Teste inicial do SENTRA"})
    first = _call(executor, read, {"action": "read", "path": "sentra_teste.txt"})
    assert first["content"] == "Teste inicial do SENTRA"
    _call(executor, write, {"action": "edit", "path": "sentra_teste.txt",
                            "content": "Teste de edição realizado com sucesso",
                            "expected_sha256": first["sha256"]})
    second = _call(executor, read, {"action": "read", "path": "sentra_teste.txt"})
    assert second["content"] == "Teste de edição realizado com sucesso"
    assert second["sha256"] != first["sha256"]
    _call(executor, delete, {"action": "delete", "path": "sentra_teste.txt",
                            "expected_sha256": second["sha256"]})
    assert _call(executor, read, {"action": "stat", "path": "sentra_teste.txt"})["exists"] is False


def test_path_is_confined_and_mutations_use_cas(tmp_path):
    executor, caps = _scope(tmp_path)
    read, write, delete = (caps["workspace:file." + kind] for kind in ("read", "write", "delete"))
    for bad in ("../outside.txt", "/tmp/outside.txt", r"C:\outside.txt", "a/../b.txt", "a//b.txt"):
        with pytest.raises(ValueError):
            _call(executor, write, {"action": "write", "path": bad, "content": "secret"})
    _call(executor, write, {"action": "write", "path": "safe.txt", "content": "original"})
    original = _call(executor, read, {"action": "read", "path": "safe.txt"})
    with pytest.raises(Exception):
        _call(executor, write, {"action": "edit", "path": "safe.txt",
                                "content": "tampered", "expected_sha256": "0" * 64})
    with pytest.raises(Exception):
        _call(executor, delete, {"action": "delete", "path": "safe.txt",
                                 "expected_sha256": "0" * 64})
    assert _call(executor, read, {"action": "read", "path": "safe.txt"})["sha256"] == original["sha256"]


def test_machine_without_grant_denies_physical_write(tmp_path):
    executor, caps = _scope(tmp_path)
    request = SimpleNamespace(operation_id="op-denied", idempotency_key="test-denied",
                              machine_id="test-files", principal_id="test-dot",
                              work_item_id="WI-no-grant", capability_id="workspace:file.write",
                              arguments={"action": "write", "path": "blocked.txt", "content": "no"})
    result = asyncio.run(executor.start(request))
    assert result.state == "FAILED"
    assert not (tmp_path / "blocked.txt").exists()
