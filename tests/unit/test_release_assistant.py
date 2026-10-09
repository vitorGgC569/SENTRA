"""Tests for local, non-publishing QA/release orchestration."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.commander import release_assistant as release


def test_readonly_release_preflight_reports_missing_inputs(tmp_path):
    report = release.preflight(tmp_path)
    assert not report["ok"]
    ids = {check["id"] for check in report["checks"]}
    assert {"release_inputs", "clean_tree", "git"}.issubset(ids)
    assert report["candidate_only"]


def test_qa_never_runs_without_explicit_approval(monkeypatch):
    called = []
    monkeypatch.setattr(release, "run_qa", lambda **kw: called.append(kw))
    report = release.run_workflow("qa", approved=False)
    assert not report["ok"]
    assert "approve-run" in report["blocker"]
    assert not called


def test_dirty_tree_blocks_candidate_by_default(monkeypatch):
    monkeypatch.setattr(
        release, "preflight",
        lambda _root: {"ok": True, "clean_tree": False, "checks": []},
    )
    monkeypatch.setattr(
        release, "run_qa",
        lambda **_kw: pytest.fail("must not execute tests on blocked candidate"),
    )
    report = release.run_workflow("candidate", approved=True)
    assert not report["ok"]
    assert "dirty" in report["blocker"]


def test_candidate_aborts_build_when_tests_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(
        release, "preflight",
        lambda _root: {"ok": True, "clean_tree": True, "checks": []},
    )
    archive = tmp_path / "tunnel.zip"
    archive.write_bytes(b"test archive")
    monkeypatch.setattr(release, "_digest", lambda _path: "test-digest")
    monkeypatch.setattr(release, "_pinned_tunnel_sha256", lambda: "test-digest")
    monkeypatch.setattr(release, "run_qa", lambda **kw: {"ok": False})
    monkeypatch.setattr(
        release, "make_candidate",
        lambda *_a: pytest.fail("must not build if tests fail"),
    )
    report = release.run_workflow(
        "candidate", approved=True, tunnel_archive=archive
    )
    assert report["ok"] is False
    assert report["tests"]["ok"] is False


def test_candidate_requires_pinned_archive_before_testing_or_building(monkeypatch):
    monkeypatch.setattr(
        release, "preflight",
        lambda _root: {"ok": True, "clean_tree": True, "checks": []},
    )
    monkeypatch.setattr(
        release, "run_qa",
        lambda **_kw: pytest.fail("cannot run without required release input"),
    )
    report = release.run_workflow("candidate", approved=True)
    assert not report["ok"]
    assert "--tunnel-archive" in report["blocker"]


def test_candidate_rejects_untrusted_tunnel_archive_before_build(tmp_path, monkeypatch):
    monkeypatch.setattr(
        release, "preflight",
        lambda _root: {"ok": True, "clean_tree": True, "checks": []},
    )
    monkeypatch.setattr(
        release, "run_qa",
        lambda **_kw: pytest.fail("cannot test/build before SHA-256 check"),
    )
    archive = tmp_path / "tunnel.zip"
    archive.write_bytes(b"not the pinned client")
    report = release.run_workflow(
        "candidate", approved=True, tunnel_archive=archive
    )
    assert not report["ok"]
    assert "SHA-256" in report["blocker"]


def test_smoke_requires_approval_and_pinned_archive(monkeypatch):
    monkeypatch.setattr(
        release, "preflight",
        lambda _root: {"ok": True, "clean_tree": True, "checks": []},
    )
    monkeypatch.setattr(
        release, "smoke_candidate",
        lambda *_a, **_kw: pytest.fail("must not launch unapproved Setup"),
    )
    assert release.run_workflow("smoke")["ok"] is False
    assert "--approve-run" in release.run_workflow("smoke")["blocker"]


def test_smoke_candidate_is_isolated_and_uninstalls(monkeypatch, tmp_path):
    import shutil
    from sentra_remote import installer

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "SENTRA-Setup.exe").write_bytes(b"fake-setup")
    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"fake-official")
    monkeypatch.setattr(release, "_digest", lambda _p: installer.TUNNEL_SHA256)

    invoked: list[list[str]] = []
    def simulate(command, *, timeout=900):
        invoked.append(command)
        if "--silent" in command:
            install = Path(command[command.index("--install-dir") + 1])
            for name in (
                "sentra-desktop.exe", "sentra-cli.exe", "sentra-installer.exe",
                "docs/START_HERE.md",
                "docs/onboarding_media/SENTRA_SETUP_GUIDE.html",
                "docs/onboarding_media/mcp-create-tunnel.mp4",
                "docs/onboarding_media/mcp-connect-connector.mp4",
            ):
                target = install / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"QA")
        elif "--uninstall" in command:
            folder = Path(command[command.index("--install-dir") + 1])
            shutil.rmtree(folder)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(release, "_run", simulate)
    result = release.smoke_candidate(dist, archive, approved=True)
    assert result["ok"] and result["removed"]
    assert len(invoked) == 2
    assert "--no-system-registration" in invoked[0]
    assert "--stop-after-doctor" in invoked[0]
    assert "--no-launch" in invoked[0]
    assert "--uninstall" in invoked[1]


def test_candidate_verification_checks_required_executables(tmp_path):
    report = release.verify_candidate(tmp_path)
    assert not report["ok"]
    assert "SENTRA-Setup.exe" in report["missing"]
    assert report["candidate_only"]


def test_secret_redaction_from_process_output():
    log = release._safe("error api_key=supersecrettoken sk-exampletoken123456789")
    assert "supersecrettoken" not in log
    assert "sk-exampletoken123456789" not in log


def test_cli_doctor_persists_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        release, "run_workflow",
        lambda *a, **kw: {"mode": "doctor", "ok": True, "candidate_only": True},
    )
    output = tmp_path / "report.json"
    assert release.main(["doctor", "--report", str(output)]) == 0
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["ok"] is True
    assert json.loads(capsys.readouterr().out)["candidate_only"]
