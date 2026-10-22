import json
import os

import pytest

from sentra_mcp.services import durable as module


@pytest.mark.skipif(os.name != "nt", reason="Windows replacement sharing semantics")
def test_projection_retries_replacement_without_replaying_events(tmp_path, monkeypatch):
    service = module.DurableRunService(tmp_path)
    try:
        run = service.create_run("owner", run_id="projection-run")
        before = service.run_status(run["run_id"], "owner")["last_event_seq"]
        replace = module.os.replace
        attempts = []
        def transient(source, destination):
            attempts.append(source)
            if len(attempts) < 3:
                raise PermissionError("transient destination reader")
            return replace(source, destination)
        monkeypatch.setattr(module.os, "replace", transient)
        with service.lock:
            service._project_locked(run["run_id"])
        assert len(attempts) == 3 and len(set(attempts)) == 1
        assert service.run_status(run["run_id"], "owner")["last_event_seq"] == before
        assert json.loads(service._state_path(run["run_id"]).read_text())["run_id"] == run["run_id"]
        assert not list(service._state_path(run["run_id"]).parent.glob("*.tmp"))
    finally:
        service.close()
