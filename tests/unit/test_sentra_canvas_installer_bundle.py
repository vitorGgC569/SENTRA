"""Release gate: the user-facing shortcut and packaged Canvas must be React-based."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.commander.build_canvas import validate_desktop_bundle
from sentra_remote.desktop import SentraDesktop


def bundle(tmp_path):
    asset_dir = tmp_path / "desktop-assets"
    asset_dir.mkdir(parents=True)
    raw = {"desktop.js": b"console.log('SENTRA')",
           "desktop.css": b"body{background:#000}",
           "bootstrap.js": b"console.log('load')"}
    for key, value in raw.items():
        (asset_dir/key).write_bytes(value)
    (tmp_path/"desktop.html").write_text(
        '<script src="/desktop-assets/bootstrap.js"></script>',encoding="utf-8")
    manifest={"entry":"/desktop.html","script":"/desktop-assets/desktop.js",
              "styles":"/desktop-assets/desktop.css",
              "files":{k:hashlib.sha256(v).hexdigest() for k,v in raw.items()}}
    (asset_dir/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
    return tmp_path


def test_react_canvas_bundle_current_source_has_verified_hashes():
    ui=Path(__file__).resolve().parents[2]/"sentra_canvas"/"static"
    manifest=validate_desktop_bundle(ui)
    assert manifest["entry"]=="/desktop.html"
    assert len(manifest["files"])>=3


@pytest.mark.skipif(shutil.which("git") is None, reason="Git checkout integration")
def test_sealed_canvas_survives_a_windows_git_checkout(tmp_path):
    root = Path(__file__).resolve().parents[2]
    source = tmp_path / "source"
    source.mkdir()
    shutil.copy2(root / ".gitattributes", source / ".gitattributes")
    for name in ("desktop_ui", "static"):
        shutil.copytree(root / "sentra_canvas" / name, source / "sentra_canvas" / name,
                        ignore=shutil.ignore_patterns("node_modules", ".tmp", "__pycache__"))
    def git(*args):
        subprocess.run(["git", "-c", "core.autocrlf=true", "-c", "core.longpaths=true", *args],
                       cwd=source, check=True, capture_output=True)
    git("init", "--quiet")
    git("add", "--force", ".")
    checkout = tmp_path / "checkout"
    git("checkout-index", "--all", "--prefix=" + checkout.as_posix() + "/")
    assert validate_desktop_bundle(checkout / "sentra_canvas/static")["files"]


def test_builder_denies_missing_changed_or_tampered_bundle(tmp_path):
    ui=bundle(tmp_path)
    assert validate_desktop_bundle(ui)["entry"]=="/desktop.html"
    (ui/"desktop-assets"/"desktop.js").write_bytes(b"tampered")
    with pytest.raises(ValueError,match="stale or tampered"):
        validate_desktop_bundle(ui)
    (ui/"desktop-assets"/"desktop.js").unlink()
    with pytest.raises(ValueError,match="stale or tampered"):
        validate_desktop_bundle(ui)


def test_builder_denies_invalid_manifest_paths_or_unverified_bootstrap(tmp_path):
    ui=bundle(tmp_path)
    manifest_path=ui/"desktop-assets"/"manifest.json"
    manifest=json.loads(manifest_path.read_text())
    manifest["files"]["../secret"]="0"*64
    manifest_path.write_text(json.dumps(manifest),encoding="utf-8")
    with pytest.raises(ValueError,match="invalid React Canvas bundle"):
        validate_desktop_bundle(ui)
    manifest["files"].pop("../secret")
    manifest_path.write_text(json.dumps(manifest),encoding="utf-8")
    (ui/"desktop.html").write_text("<html>stale html</html>",encoding="utf-8")
    with pytest.raises(ValueError,match="pinned bootstrap"):
        validate_desktop_bundle(ui)


def test_quickstart_canvas_launcher_is_installed_owned_executable(tmp_path,monkeypatch):
    from sentra_remote import desktop
    assert hasattr(desktop, "SentraDesktop")
    app=object.__new__(desktop.SentraDesktop)
    app.paths=SimpleNamespace(install_dir=tmp_path)
    launched=Mock()
    monkeypatch.setattr(desktop.subprocess,"Popen",launched)
    from tkinter import messagebox
    alert=Mock()
    monkeypatch.setattr(messagebox,"showerror",alert)
    app.open_canvas()
    alert.assert_called_once()
    launched.assert_not_called()
    (tmp_path/"sentra-canvas.exe").write_bytes(b"synthetic-fixture")
    app.open_canvas()
    launched.assert_called_once()
    assert launched.call_args.args[0]==[str((tmp_path/"sentra-canvas.exe").resolve())]



@pytest.mark.parametrize("ready", (True, False))
def test_quickstart_hands_off_plugin_only_after_verified_tunnel(ready):
    """No plugin install is claimed; local readiness only opens user review."""
    from sentra_remote import desktop
    app=object.__new__(desktop.SentraDesktop)
    status={
        "mcp":{"ok":ready},"tunnel":{"configured":True,"ok":ready},
        "onboarding":{"stage":"ready" if ready else "need_tunnel"},
    }
    app.runtime=SimpleNamespace(connect_and_verify=lambda **kwargs:{
        "status":status,"chatgpt_onboarding":{"ready":ready,"detail":"health"},
    })
    app.root=SimpleNamespace(after=lambda delay,callback:callback())
    app.connect_button=Mock()
    app.quick_progress={}
    app.quick_status=Mock()
    app.quick_detail=Mock()
    app.refresh_async=Mock()
    app.finish_chatgpt_plugin_setup=Mock()
    app._connect_openai_services()
    assert app.finish_chatgpt_plugin_setup.call_count==(1 if ready else 0)


def test_installer_is_explicit_that_plugin_authorization_is_account_owned():
    from sentra_remote.onboarding import chatgpt_plugin_install_plan
    prepared=chatgpt_plugin_install_plan(
        {"mcp":{"ok":True},"tunnel":{"configured":True,"ok":True}},
        tunnel_id="tunnel_example",
    )
    assert prepared["ready_to_install"] is True
    assert prepared["requires_account_authorization"] is True
    assert prepared["tunnel_id"]=="tunnel_example"
    assert all("key" not in field.lower() or "api" not in field.lower()
               for field in prepared["steps"])



def test_msi_cannot_omit_first_install_plugin_guide(tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("Windows MSI validation")
    from scripts.commander.build_msi import build_msi
    from sentra_remote.installer import PRODUCTS
    staging=tmp_path/"dist"
    staging.mkdir()
    for name in (*PRODUCTS, "tunnel-client.exe"):
        (staging/name).write_bytes(b"fixture")
    media=staging/"docs"/"onboarding_media"
    media.mkdir(parents=True)
    (media/"SENTRA_SETUP_GUIDE.html").write_text("fixture",encoding="utf-8")
    with pytest.raises(FileNotFoundError,match="Canvas/ChatGPT app guide"):
        build_msi(staging,tmp_path/"no-guide.msi","1.0.0")


def test_first_install_guide_is_in_source_and_release_smoke_contract():
    root=Path(__file__).resolve().parents[2]
    guide=root/"docs"/"SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md"
    assert guide.is_file()
    text=guide.read_text(encoding="utf-8")
    assert "/model" in text and "ChatGPT" in text and "Canvas" in text
    workflow=(root/".github"/"workflows"/"release-commander.yml").read_text(encoding="utf-8")
    assert guide.name in workflow



def test_msi_primary_shortcut_points_to_canvas_not_legacy_human():
    import inspect
    from scripts.commander.build_msi import build_msi
    code=inspect.getsource(build_msi)
    assert 'canvas_id = file_ids["sentra-canvas.exe"]' in code
    shortcut=code[code.index('"SENTRA_App_Shortcut"'):]
    assert 'f"[#{canvas_id}]"' in shortcut.split('"SENTRA_Control_Center_Shortcut"')[0]
    assert 'human_id' not in shortcut.split('"SENTRA_Control_Center_Shortcut"')[0]


def test_release_staging_includes_first_install_guide_as_msi_document():
    import inspect
    from scripts.commander.release_assets import build_staging
    code=inspect.getsource(build_staging)
    assert '"SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md"' in code



def test_msi_adds_desktop_canvas_shortcut_with_user_scoped_install():
    from scripts.commander import build_msi
    import inspect
    code=inspect.getsource(build_msi.build_msi)
    assert '"SENTRA_Desktop_Shortcut"' in code
    assert '"DesktopFolder"' in code
    assert 'f"[#{canvas_id}]"' in code
    assert '"MSIINSTALLPERUSER", "1"' in code

def test_tunnel_license_payload_is_owned_and_cleaned_up(tmp_path, monkeypatch):
    """Tunnel archive license notices must not survive an owned uninstall."""
    import inspect
    from sentra_remote import installer, update_helper

    install_dir = tmp_path / "Commander"
    licenses = install_dir / "licenses" / "tunnel-client"
    licenses.mkdir(parents=True)
    for name in ("LICENSE", "NOTICE", "tunnel-client-v0.0.14-windows-amd64.spdx.json"):
        (licenses / name).write_text("fixture", encoding="utf-8")
    (install_dir / "tunnel-client.exe").write_bytes(b"fixture")
    owned = installer._owned_tree_files(licenses, "licenses/tunnel-client")
    assert len(owned) == 3
    assert all(item.startswith("licenses/tunnel-client/") for item in owned)
    marker = installer._write_install_marker(install_dir, ["tunnel-client.exe", *owned])
    saved = json.loads(marker.read_text(encoding="utf-8"))
    assert set(owned).issubset(set(saved["owned_files"]))
    # Ensure the actual installation path records the extracted notices.
    assert "tunnel_license_files" in inspect.getsource(installer._install_product)
    monkeypatch.setattr(update_helper, "_wait_pid", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "_stop_installed_processes", lambda *args: None)
    assert update_helper.cleanup_install(install_dir, parent_pid=0) == 0
    assert not install_dir.exists()

def test_update_relaunches_canvas_as_primary_application(tmp_path, monkeypatch):
    from sentra_remote import update_helper
    for name in ("sentra-canvas.exe", "sentra-desktop.exe", "sentra-human.exe"):
        (tmp_path / name).write_bytes(b"fixture")
    launched = Mock()
    monkeypatch.setattr(update_helper.subprocess, "Popen", launched)
    update_helper._start_desktop(tmp_path)
    launched.assert_called_once()
    assert launched.call_args.args[0] == [str(tmp_path / "sentra-canvas.exe")]


def test_windows_uninstall_registration_uses_canvas_icon():
    import inspect
    from sentra_remote import installer
    assert '"DisplayIcon": str(install_dir / "sentra-canvas.exe")' in inspect.getsource(
        installer._register_uninstall
    )
