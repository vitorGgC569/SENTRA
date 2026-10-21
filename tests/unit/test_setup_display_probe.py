"""Setup must verify actual display evidence, not just an Electron process exit."""
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from sentra_remote import display_probe, installer


def record(directory: Path, **changes):
    value = {"schema": 1, "nonce": "a" * 32, **{key: True for key in display_probe.CHECKS}}
    value.update(changes)
    (directory / "result.json").write_text(json.dumps(value))


def test_probe_requires_consumed_ticket_observed_page_and_no_foreign_requests(tmp_path):
    ticket = tmp_path / "ticket"
    record(tmp_path)
    assert display_probe._verified_record(tmp_path, "a" * 32, 0, ticket, 1, 0)
    for code, page_requests, foreign_requests in [(4, 1, 0), (0, 0, 0), (0, 1, 1)]:
        assert not display_probe._verified_record(tmp_path, "a" * 32, code, ticket,
                                                  page_requests, foreign_requests)
    ticket.write_text("synthetic one-use bootstrap")
    assert not display_probe._verified_record(tmp_path, "a" * 32, 0, ticket, 1, 0)


@pytest.mark.parametrize("changed", [*display_probe.CHECKS, "nonce", "schema", "extra"])
def test_probe_rejects_partial_stale_or_unrecognized_evidence(tmp_path, changed):
    value = False if changed in display_probe.CHECKS else "wrong"
    record(tmp_path, **{changed: value})
    assert not display_probe._verified_record(tmp_path, "a" * 32, 0, tmp_path / "ticket", 1, 0)


def test_successful_exit_without_result_is_not_a_working_display(tmp_path):
    assert not display_probe._verified_record(tmp_path, "a" * 32, 0, tmp_path / "ticket", 1, 0)
    (tmp_path / "result.json").write_bytes(b"x" * 2049)
    assert not display_probe._verified_record(tmp_path, "a" * 32, 0, tmp_path / "ticket", 1, 0)


def test_no_display_process_runs_before_payload_integrity(tmp_path, monkeypatch):
    run = Mock(side_effect=AssertionError("must not execute unverified bytes"))
    monkeypatch.setattr(display_probe, "_run_display_probe", run)
    assert display_probe.probe_installed_display(tmp_path) == {"ok": False, "reason": "display_payload_invalid"}
    run.assert_not_called()


def test_repair_blocks_launch_and_success_report_after_renderer_failure(tmp_path, monkeypatch):
    installer._write_install_marker(tmp_path)
    ready = {"core_ready": True, "chatgpt_onboarding": {"ready": True},
             "status": {"mcp": {"ok": True}, "tunnel": {"ok": True},
                        "web_models": {key: True for key in ("payload_complete", "ready", "catalog_ready", "turn_ready")}}}
    runtime = Mock()
    runtime.connect_and_verify.return_value = ready
    monkeypatch.setattr(installer, "LocalRuntime", Mock(return_value=runtime))
    monkeypatch.setattr(installer, "configure_codex", lambda *_, **__: {"ready": True})
    monkeypatch.setattr(display_probe, "probe_installed_display", lambda *_: {"ok": False, "reason": "display_probe_failed"})
    launch = Mock(side_effect=AssertionError("do not launch a failed renderer"))
    monkeypatch.setattr(installer.subprocess, "Popen", launch)
    result = installer.verify_installed_local(install_dir=tmp_path)
    assert not installer._installation_ready(result["connect_verify"])
    assert not installer._installation_ready(result["connect_verify"], openai_required=False)
    launch.assert_not_called()
    runtime.stop_all.assert_not_called()
    report = tmp_path / "report.json"
    installer._write_setup_report(report, "install", result, 2)
    evidence = json.loads(report.read_text())
    assert evidence["display_required"] and not evidence["checks"]["display"]
    assert not evidence["ready"] and not evidence["homologated"]


def test_silent_setup_does_not_enroll_account_after_a_failed_display(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "install", lambda **_: {"connect_verify": {
        "core_ready": True, "display_required": True, "status": {"display": {"ok": False}}}})
    enroll = Mock(side_effect=AssertionError("a failed local installation must not create account resources"))
    monkeypatch.setattr("sentra_remote.openai_auto_setup.run_setup_enrollment", enroll)
    assert installer.main(["--silent", "--browser-setup", "--report-file", str(tmp_path / "report.json")]) == 2
    enroll.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows display lifecycle")
@pytest.mark.parametrize("failure", ["startup", "timeout", "thread"])
def test_failed_probe_cleans_its_bootstrap_servers_and_owned_process(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(display_probe.tempfile, "gettempdir", lambda: str(tmp_path))
    task = Mock(returncode=None)
    task.communicate.side_effect = [subprocess.TimeoutExpired("synthetic", 1), (None, None)]
    start = Mock(return_value=task) if failure == "timeout" else Mock(side_effect=OSError("private-diagnostic"))
    monkeypatch.setattr("sentra_canvas.owned_process.TaskProcess", start)
    if failure == "thread":
        monkeypatch.setattr(display_probe.threading.Thread, "start", Mock(side_effect=RuntimeError("private-diagnostic")))
    result = display_probe._run_display_probe(tmp_path, timeout_s=1)
    assert not result["ok"] and "private-diagnostic" not in json.dumps(result)
    assert not list(tmp_path.iterdir())
    if failure == "timeout":
        task.terminate_tree.assert_called_once()
        assert task.communicate.call_count == 2
        assert result["reason"] == "display_probe_timeout"
