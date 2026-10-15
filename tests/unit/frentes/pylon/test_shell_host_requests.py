"""Host request failures keep a sanitized phase and do not run again."""
from contextlib import closing
import json

import pytest

from sentra_canvas.shell_requests import ShellHostRequests
from sentra_mcp.services.durable import DurableRunService


def _host(tmp_path):
    durable = DurableRunService(tmp_path / ".sentra")
    return ShellHostRequests(durable, "pylon-host"), durable


def _calls():
    seen = []

    def callback():
        seen.append("run")
        raise RuntimeError("token=SECRET stdout C:\\private\\leak")

    return seen, callback


def test_unmarked_effect_then_exception_stays_uncertain_and_does_not_replay(tmp_path):
    host, durable = _host(tmp_path)
    try:
        seen = []

        def callback():
            seen.append("effect")
            raise RuntimeError("token=SECRET stdout C:\\private\\leak")

        with pytest.raises(RuntimeError):
            host.invoke("project-a", "installation.verify", {"probe": 1},
                "verify-unmarked-effect", callback)
        assert seen == ["effect"]
        receipt = host.invoke("project-a", "installation.verify", {"probe": 1},
            "verify-unmarked-effect", callback)
        assert seen == ["effect"]
        assert receipt["status"] == "uncertain"
        assert receipt["phase"] is None
        assert receipt["query_failed"] is False
        assert receipt["effect_uncertain"] is True
        assert receipt["success"] is False
        assert receipt["automatic_retry"] is False
        assert receipt["may_resend"] is False
        assert receipt["diagnosis"]["code"] == "phase_unattested"
        assert receipt["diagnosis"]["operation_id"] is None
        rendered = json.dumps(receipt)
        assert "unknown" not in rendered
        assert "SECRET" not in rendered
        assert "private" not in rendered
        with closing(durable.store.connect("shell")) as db:
            row = db.execute("SELECT phase,state FROM canvas_shell_host_requests WHERE request_key=?",
                ("verify-unmarked-effect",)).fetchone()
        assert row["phase"] is None
        assert row["state"] == "uncertain"
    finally:
        durable.close()


def test_explicit_before_admission_is_a_failed_query(tmp_path):
    host, durable = _host(tmp_path)
    try:
        seen = []

        def callback():
            seen.append("query")
            host.note_before_admission("project-a", "verify-before-admission")
            raise RuntimeError("token=SECRET stdout C:\\private\\leak")

        with pytest.raises(RuntimeError):
            host.invoke("project-a", "installation.verify", {"probe": 1},
                "verify-before-admission", callback)
        receipt = host.invoke("project-a", "installation.verify", {"probe": 1},
            "verify-before-admission", callback)
        assert seen == ["query"]
        assert receipt["status"] == "admission_failed"
        assert receipt["phase"] == "before_admission"
        assert receipt["query_failed"] is True
        assert receipt["effect_uncertain"] is False
        assert receipt["success"] is False
        assert receipt["may_resend"] is False
        assert "SECRET" not in json.dumps(receipt)
    finally:
        durable.close()


def test_exception_after_possible_effect_stays_uncertain_and_does_not_replay(tmp_path):
    host, durable = _host(tmp_path)
    try:
        seen = []

        def callback():
            seen.append("run")
            host.note_effect_possible("project-a", "verify-after-effect",
                operation_id="op-shell-verify")
            raise RuntimeError("password=SECRET worker log")

        with pytest.raises(RuntimeError):
            host.invoke("project-a", "installation.verify", {"probe": 2},
                "verify-after-effect", callback)
        assert seen == ["run"]
        receipt = host.invoke("project-a", "installation.verify", {"probe": 2},
            "verify-after-effect", callback)
        assert seen == ["run"]
        assert receipt["status"] == "uncertain"
        assert receipt["request_key"] == "verify-after-effect"
        assert receipt["receipt_id"] is None
        assert receipt["automatic_retry"] is False
        assert receipt["may_resend"] is False
        assert receipt["success"] is False
        assert receipt["query_failed"] is False
        assert receipt["effect_uncertain"] is True
        assert receipt["phase"] == "after_possible_effect"
        assert receipt["reason"] == "request admitted; observe its outcome before resubmitting"
        assert receipt["diagnosis"]["code"] == "effect_uncertain"
        assert receipt["diagnosis"]["exception_class"] == "RuntimeError"
        assert receipt["diagnosis"]["operation_id"] == "op-shell-verify"
        rendered = json.dumps(receipt)
        assert "SECRET" not in rendered
        assert "password" not in rendered
        assert receipt["status"] != "succeeded"
        reopened = ShellHostRequests(durable, "pylon-host")
        again = reopened.invoke("project-a", "installation.verify", {"probe": 2},
            "verify-after-effect", callback)
        assert again["diagnosis"]["operation_id"] == "op-shell-verify"
        assert again["phase"] == "after_possible_effect"
        assert seen == ["run"]
    finally:
        durable.close()
