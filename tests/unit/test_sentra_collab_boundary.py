"""Contract smoke tests for the isolated, opt-in SENTRA collaboration module."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COLLAB = ROOT / "sentra_collab"


def test_collab_is_not_auto_loaded_in_existing_canvas():
    # The coordinator must opt in after validating auth and persistence.
    native = (ROOT / "sentra_canvas" / "static" / "native.html").read_text(
        encoding="utf-8"
    )
    assert "sentra-collab.js" not in native
    assert "createCollabServer" not in native


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js optional")
def test_collab_javascript_syntax():
    for file in (
        COLLAB / "policy.mjs",
        COLLAB / "server.mjs",
        COLLAB / "precommit.mjs",
        COLLAB / "reference_host.mjs",
        COLLAB / "sqlite_host.mjs",
        COLLAB / "physical_cables.mjs",
        COLLAB / "graph_a11y.mjs",
        COLLAB / "verified_snapshot.mjs",
        COLLAB / "local_admission.mjs",
        COLLAB / "test" / "graph_a11y_phase3.test.mjs",
        COLLAB / "test" / "verified_snapshot_phase3.test.mjs",
        COLLAB / "test" / "quota_health_phase3.test.mjs",
        COLLAB / "test" / "physical_cables.test.mjs",
        COLLAB / "test" / "recovery_phase2.test.mjs",
        COLLAB / "test" / "workspace_lifecycle.test.mjs",
        COLLAB / "test" / "sqlite_worker.mjs",
        COLLAB / "test" / "sqlite_e2e.test.mjs",
        COLLAB / "awareness_guard.mjs",
        ROOT / "sentra_canvas" / "static" / "sentra-collab.js",
    ):
        run = subprocess.run(
            ["node", "--check", str(file)], cwd=ROOT,
            capture_output=True, text=True, timeout=20, check=False,
        )
        assert run.returncode == 0, f"{file.name}: {run.stderr}"


@pytest.mark.skipif(
    shutil.which("npm") is None
    or not (COLLAB / "node_modules" / "@hocuspocus" / "server").exists(),
    reason="optional Hocuspocus dependencies not installed",
)
def test_collab_real_websocket_e2e():
    run = subprocess.run(
        [shutil.which("npm"), "test", "--prefix", str(COLLAB)], cwd=ROOT,
        capture_output=True, text=True, timeout=40, check=False,
    )
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
    match = re.search(r"\bpass\s+(\d+)", run.stdout)
    assert match is not None and int(match.group(1)) >= 54, run.stdout[-3000:]
    assert "fail 0" in run.stdout

def test_reference_host_remains_fixture_only():
    server = (COLLAB / "server.mjs").read_text(encoding="utf-8")
    fixture = (COLLAB / "reference_host.mjs").read_text(encoding="utf-8")
    native = (ROOT / "sentra_canvas" / "static" / "native.html").read_text(
        encoding="utf-8"
    )
    assert "reference_host" not in server.lower()
    assert "reference_host" not in native.lower()
    assert "server.listen(" not in fixture
    assert "createCollabServer(" not in fixture
    assert "ReferenceHost" in fixture


def test_sqlite_host_is_opt_in_and_awareness_frames_are_guarded():
    sqlite = (COLLAB / "sqlite_host.mjs").read_text(encoding="utf-8")
    server = (COLLAB / "server.mjs").read_text(encoding="utf-8")
    guard = (COLLAB / "awareness_guard.mjs").read_text(encoding="utf-8")
    native_html = (ROOT / "sentra_canvas" / "static" / "native.html").read_text(
        encoding="utf-8"
    )
    native_js = (ROOT / "sentra_canvas" / "static" / "native.js").read_text(
        encoding="utf-8"
    )
    assert "BEGIN IMMEDIATE" in sqlite
    assert "synchronous=FULL" in sqlite
    assert "CREATE TABLE IF NOT EXISTS nonces" in sqlite
    assert "readAwarenessFrame(update,documentName)" in server
    assert "count!==1" in guard
    assert "sqlite_host" not in server
    for native in (native_html, native_js):
        assert "sqlite_host" not in native
        assert "SentraCollab" not in native

def test_phase2_physics_recovery_lifecycle_remain_opt_in():
    native_html = (ROOT / "sentra_canvas" / "static" / "native.html").read_text(
        encoding="utf-8"
    )
    native_js = (ROOT / "sentra_canvas" / "static" / "native.js").read_text(
        encoding="utf-8"
    )
    cables = (COLLAB / "physical_cables.mjs").read_text(encoding="utf-8")
    precommit = (COLLAB / "precommit.mjs").read_text(encoding="utf-8")
    lifecycle = (
        ROOT / "sentra_canvas" / "static" / "sentra-collab.js"
    ).read_text(encoding="utf-8")
    sqlite = (COLLAB / "sqlite_host.mjs").read_text(encoding="utf-8")
    assert "authoritativeCables(readGraph)" in cables
    assert "reducedMotion" in cables
    assert "commitTimeoutMs" in precommit
    assert "quarantined" in precommit
    assert "reconcileCommit" in sqlite
    assert "createWorkspaceSession" in lifecycle
    assert "switchWorkspace" in lifecycle
    for native in (native_html, native_js):
        assert "physical_cables" not in native
        assert "createWorkspaceSession" not in native
        assert "SentraCollab" not in native

def test_phase3_graph_snapshot_quota_remain_optional_and_display_only():
    native_html = (ROOT / "sentra_canvas" / "static" / "native.html").read_text(
        encoding="utf-8"
    )
    native_js = (ROOT / "sentra_canvas" / "static" / "native.js").read_text(
        encoding="utf-8"
    )
    server = (COLLAB / "server.mjs").read_text(encoding="utf-8")
    graph = (COLLAB / "graph_a11y.mjs").read_text(encoding="utf-8")
    snapshot = (COLLAB / "verified_snapshot.mjs").read_text(encoding="utf-8")
    admission = (COLLAB / "local_admission.mjs").read_text(encoding="utf-8")
    assert "projectAccessibleGraph(readGraph)" in graph
    assert "reducedMotion" in graph
    assert "restoreAllowed:false" in snapshot
    assert "trustedSha256" in snapshot
    assert "MAX_ENVELOPE_BYTES" in snapshot
    assert "LocalAdmission" in server
    assert "localHealth:" in server
    assert "framesRejected" in admission
    for native in (native_html, native_js):
        assert "mountGraphAccessibility" not in native
        assert "verified_snapshot" not in native
        assert "localHealth" not in native
        assert "SentraCollab" not in native
