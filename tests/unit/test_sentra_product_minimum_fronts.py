"""Product minimum for fronts that do not need a guest VM.

Each test starts from files or an empty directory and calls the shipped
function. Expected digests come from the function, not from a copied literal.
"""
import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from memory.store import MemoryStore
from sentra_canvas.native_refresh import (
    assert_distinct_maintenance, code_reload_identity, installed_update_identity,
)
from sentra_canvas.native_single_instance import dot_window_identity
from sentra_canvas.peer_work_wire import PeerWireDenied, PeerWorkWire, deliver_loopback
from sentra_canvas.shell_dot_vm import host_resources
from sentra_remote.optional_providers import provider_effect_preview, provider_remove
from sentra_remote.support_surface import license_state, write_support_bundle
from sentra_remote.visual_catalog import VisualModelCatalog


def _pair(tmp_path: Path):
    def identity():
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return SimpleNamespace(
            key=key, node_id="peer-" + hashlib.sha256(public).hexdigest(),
            public_key=base64.b64encode(public).decode())
    left, right = identity(), identity()
    mesh = "SENTRA-MESH-TEST-" + "u" * 36
    alice = PeerWorkWire(
        identity=left, mesh_key=mesh, workspace_id="qa-workspace",
        trust={right.node_id: right.public_key}, ledger=tmp_path / "alice.db")
    bob = PeerWorkWire(
        identity=right, mesh_key=mesh, workspace_id="qa-workspace",
        trust={left.node_id: left.public_key}, ledger=tmp_path / "bob.db")
    packet = alice.seal(
        kind="TASK_OFFER", target=bob.node, subject_id="work-item-1",
        reference_sha256=hashlib.sha256(b"only-a-pinned-reference").hexdigest())
    return alice, packet


def _frontend(root: Path, *, source_newer: bool) -> None:
    ui = root / "sentra_canvas" / "desktop_ui"
    (ui / "src").mkdir(parents=True)
    (ui / "package.json").write_text("{}", encoding="utf-8")
    bundle = root / "sentra_canvas" / "static" / "desktop-assets" / "desktop.js"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("bundle", encoding="utf-8")
    source = ui / "src" / "main.jsx"
    source.write_text("export const ready = true\n", encoding="utf-8")
    if source_newer:
        newer = bundle.stat().st_mtime_ns + 1_000_000
        os_utime(source, newer)


def os_utime(path: Path, ns: int) -> None:
    import os
    os.utime(path, ns=(int(ns), int(ns)))


def test_code_reload_installed_update_and_dot_window_stay_distinct(tmp_path: Path):
    _frontend(tmp_path, source_newer=True)
    code = code_reload_identity(tmp_path)
    marker = tmp_path / ".sentra-install.json"
    marker.write_text(json.dumps({"installation_id": "install-local-1", "schema": 1}), encoding="utf-8")
    installed = installed_update_identity(json.loads(marker.read_text(encoding="utf-8")))
    dot = dot_window_identity()
    assert_distinct_maintenance(code, installed, dot)
    assert code["frontend_stale"] is True
    assert code["installation_id"] is None
    assert installed["installation_id"] == "install-local-1"
    assert installed["frontend_stale"] is None
    assert dot["mutex"] not in json.dumps(code)
    with pytest.raises(ValueError, match="not a code reload"):
        installed_update_identity({**json.loads(marker.read_text(encoding="utf-8")),
                                   "frontend_source_time_ns": code["frontend_source_time_ns"]})


def test_provider_remove_previews_before_effect_and_replays(tmp_path: Path):
    calls = []

    def runner(action, payload):
        calls.append((action, payload["provider"]))
        return {"removed": True}

    with pytest.raises(PermissionError, match="current preview"):
        provider_remove("git", approved=True, runner=runner, journal=tmp_path / "journal.json")
    assert calls == []
    preview = provider_effect_preview("git", "remove")
    assert "user project files stay" in preview["effect"]
    with pytest.raises(PermissionError, match="explicit user approval"):
        provider_remove("git", approved=False, runner=runner,
                        preview_sha256=preview["preview_sha256"], journal=tmp_path / "journal.json")
    assert calls == []
    first = provider_remove("git", approved=True, runner=runner,
                            preview_sha256=preview["preview_sha256"], journal=tmp_path / "journal.json")
    second = provider_remove("git", approved=True, runner=runner,
                             preview_sha256=preview["preview_sha256"], journal=tmp_path / "journal.json")
    assert calls == [("remove", "git")]
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert second["removed"] is True


def test_visual_model_is_unavailable_until_installed_and_remove_is_previewed(tmp_path: Path):
    catalog = VisualModelCatalog(tmp_path)
    assert catalog.health("screen-reader")["state"] == "unavailable"
    payload = b"visual-weights-v1"
    ready = catalog.install("screen-reader", payload)
    assert ready["state"] == "ready"
    assert ready["bytes"] == len(payload)
    assert ready["grants_execution"] is False
    preview = catalog.remove_preview("screen-reader")
    with pytest.raises(PermissionError, match="current preview"):
        catalog.remove("screen-reader", preview_sha256="0" * 64)
    assert catalog.health("screen-reader")["state"] == "ready"
    removed = catalog.remove("screen-reader", preview_sha256=preview["preview_sha256"])
    assert removed["removed"] is True
    again = catalog.remove("screen-reader", preview_sha256=catalog.remove_preview("screen-reader")["preview_sha256"])
    assert again["replayed"] is True
    assert catalog.health("screen-reader")["state"] == "unavailable"


def test_support_bundle_omits_credentials_and_license_does_not_grant(tmp_path: Path):
    source = tmp_path / "notes"
    source.mkdir()
    (source / "readme.txt").write_text("open the Dot from Home", encoding="utf-8")
    (source / "auth.json").write_text('{"token":"secret"}', encoding="utf-8")
    (source / "session.log").write_text("api_key=hidden\nstill a log", encoding="utf-8")
    bundle = tmp_path / "support.zip"
    report = write_support_bundle(source, bundle)
    assert report["contains_credentials"] is False
    assert report["included"] == ["readme.txt"]
    assert "auth.json" in report["omitted"]
    assert "session.log" in report["omitted"]
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert names == ["readme.txt"]
        assert b"secret" not in archive.read("readme.txt")
    assert license_state(tmp_path / "missing-license.json")["state"] == "unlicensed"
    license_path = tmp_path / "license.json"
    license_path.write_text(json.dumps({"schema": 1, "state": "active", "holder": "local"}), encoding="utf-8")
    state = license_state(license_path)
    assert state["state"] == "active"
    assert state["grants_execution"] is False


def test_dot_memory_survives_a_new_store_and_vm_cap_is_half_the_host(tmp_path: Path):
    first = MemoryStore(tmp_path)
    saved = first.put("owner", namespace="dot.plan", key="current",
                      body={"fact": "use the guest", "hypothesis": "debian is installed"})
    second = MemoryStore(tmp_path)
    loaded = second.get("owner", namespace="dot.plan", key="current")
    assert loaded["body"]["fact"] == "use the guest"
    assert loaded["body_sha256"] == saved["body_sha256"]
    assert loaded["authorizes_effects"] is False
    host = host_resources()
    assert host["max_cpus"] <= host["logical_cpus"]
    assert host["max_memory_mb"] * 2 <= host["physical_memory_mb"]
    assert host["resource_fraction"] <= 0.5


def test_peer_delivery_failure_does_not_resend_and_vpn_is_not_permission(tmp_path: Path):
    alice, packet = _pair(tmp_path)
    with pytest.raises(PeerWireDenied, match="reconcile before resending"):
        deliver_loopback(alice, ("127.0.0.1", 1), packet)
    with pytest.raises(PeerWireDenied, match="reconcile before resending"):
        deliver_loopback(alice, ("127.0.0.1", 1), packet)
    with pytest.raises(PeerWireDenied, match="must not be started without mTLS"):
        deliver_loopback(alice, ("26.168.99.36", 37037), packet)
