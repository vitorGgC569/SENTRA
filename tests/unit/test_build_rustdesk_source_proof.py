"""Local Git fixtures test source-proof rejection; no native build is claimed."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts.commander import build_rustdesk
from scripts.commander.build_windows import _BuildLock
from sentra_executors.remote_rustdesk_build import native_peer_gate_patch


def _git(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=SENTRA Unit Fixture",
        "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
        "-c", "protocol.file.allow=always", "-c", "core.hooksPath=" + str(root.parent / "empty-hooks"),
        "-C", str(root), *args], text=True, encoding="utf-8", stderr=subprocess.PIPE)


@pytest.fixture
def source_fixture(tmp_path, monkeypatch):
    # Deliberately minimal anchor fixture, not executable upstream RustDesk.
    files = {
        "src/lib.rs": "pub mod core_main;\n",
        "src/core_main.rs": ('pub fn core_main() -> Option<Vec<String>> {\n'
                             '    crate::load_custom_client();\n    if _is_flutter_invoke_new_connection {\n'),
        "flutter/windows/runner/main.cpp": "  if (hwnd != NULL) {\n",
        "src/client.rs": ('        let rs_pk = get_rs_pk(if key.is_empty() {\n'
            '        let sign_pk = match sign_pk {\n'
            '        match timeout(READ_TIMEOUT, conn.next()).await? {\n        Ok(option_pk)\n    }\n'),
        "src/client/io_loop.rs": ('                loop {\n                    tokio::select! {\n'
            '    async fn handle_msg_from_ui(&mut self, data: Data, peer: &mut Stream) -> bool {\n'
            '                            self.handle_local_clipboard_msg(&mut peer, _msg).await;\n'
            '        if let Ok(msg_in) = Message::parse_from_bytes(&data) {\n'
            '                        let peer_version = pi.version.clone();\n'
            '                        _ = status_timer.tick() => {\n'
            '                    handler.on_rgba(display, data);\n'),
    }
    module = tmp_path / "module-origin"; module.mkdir(); _git(module, "init", "-q")
    config = module / "src/config.rs"; config.parent.mkdir()
    config.write_text('pub const LINK_DOCS_HOME: &str = "fixture";\n'
        '    pub fn path<P: AsRef<Path>>(p: P) -> PathBuf {\n'
        '    pub fn log_path() -> PathBuf {\n'
        '    pub fn ipc_path(postfix: &str) -> String {\n', encoding="utf-8")
    _git(module, "add", "."); _git(module, "commit", "-qm", "Uncompiled module anchor fixture")
    source = tmp_path / "source"; source.mkdir(); _git(source, "init", "-q")
    for name, content in files.items():
        path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
    (source / ".gitignore").write_text("flutter/pubspec.lock\n", encoding="utf-8")
    _git(source, "add", "."); _git(source, "commit", "-qm", "Uncompiled root anchor fixture")
    _git(source, "submodule", "add", "-q", str(module), "libs/hbb_common")
    _git(source, "commit", "-qam", "Pin local fixture submodule")
    pins = tmp_path / "pins" / "sentra_quality"; pins.mkdir(parents=True)
    (pins / "approved_sources.json").write_text(json.dumps({"repos": [{"name": "rustdesk",
        "revision": _git(source, "rev-parse", "HEAD").strip(), "upstream": "local-unit-fixture"}]}), encoding="utf-8")
    monkeypatch.setattr(build_rustdesk, "ROOT", pins.parent)
    plan = native_peer_gate_patch(str(source))
    patch = tmp_path / "native.patch"; patch.write_text(plan["patch"], encoding="utf-8", newline="\n")
    _git(source, "apply", str(patch))
    (source / "flutter/pubspec.lock").write_text("fixture lock v1\n", encoding="utf-8")
    return source


def test_submodule_file_is_reconstructed_from_its_own_pinned_git_commit(source_fixture):
    source = source_fixture
    before = _git(source / "libs/hbb_common", "rev-parse", "HEAD")
    verified = build_rustdesk.validate_native_sources(source)
    assert len(verified["native_sources"]) == 7
    assert "libs/hbb_common/src/config.rs" in verified["native_sources"]
    assert _git(source / "libs/hbb_common", "rev-parse", "HEAD") == before
    assert _git(source / "libs/hbb_common", "status", "--short").strip() == "M src/config.rs"


def test_unreviewed_extra_hunk_in_profile_source_is_rejected(source_fixture):
    path = source_fixture / "libs/hbb_common/src/config.rs"
    path.write_text(path.read_text(encoding="utf-8") + "// foreign unreviewed edit\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="instrumentation differs"):
        build_rustdesk.validate_native_sources(source_fixture)


def test_unreviewed_submodule_file_is_rejected(source_fixture):
    (source_fixture / "libs/hbb_common/unreviewed.txt").write_text("foreign", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreviewed.*submodule"):
        build_rustdesk.validate_native_sources(source_fixture)


def test_flutter_lock_is_hashed_even_when_ignored_by_upstream_git(source_fixture):
    before = build_rustdesk.source_inputs(source_fixture)
    lock = source_fixture / "flutter/pubspec.lock"
    assert "flutter/pubspec.lock" in before
    lock.write_text("fixture lock v2\n", encoding="utf-8")
    assert build_rustdesk.source_inputs(source_fixture)["flutter/pubspec.lock"] != before["flutter/pubspec.lock"]
    lock.unlink()
    with pytest.raises(RuntimeError, match="dependency lock is missing"):
        build_rustdesk.source_inputs(source_fixture)


def test_source_lock_excludes_same_checkout_with_a_different_output(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    output = tmp_path / "output"
    args = SimpleNamespace(source=source, output=output)
    with _BuildLock(source.parent / (source.name + ".sentra-build.lock"), "RustDesk source build"):
        with pytest.raises(RuntimeError, match="already running"):
            build_rustdesk.build_phase(args)
    assert not output.exists()


def test_output_inside_source_is_rejected_before_writing_any_lock(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    output = source / "bad-output"
    with pytest.raises(ValueError, match="outside"):
        build_rustdesk.build_phase(SimpleNamespace(source=source, output=output))
    assert not output.exists()


def test_flutter_short_directory_configuration_is_process_local(tmp_path):
    project = tmp_path / "project"; project.mkdir()
    scratch = tmp_path / "scratch"; scratch.mkdir()
    original = {"APPDATA": "existing-user-config", "PATH": "unchanged"}
    isolated = build_rustdesk.flutter_build_environment(project, scratch, original)
    assert original["APPDATA"] == "existing-user-config"
    assert isolated["PATH"] == original["PATH"]
    config = Path(isolated["APPDATA"]) / ".flutter_settings"
    settings = json.loads(config.read_text(encoding="utf-8"))
    assert not Path(settings["build-dir"]).is_absolute()
    assert (project / settings["build-dir"]).resolve() == scratch / "b"
    with pytest.raises(ValueError, match="separate"):
        build_rustdesk.flutter_build_environment(project, project, original)


def test_flutter_publication_preserves_previous_bundle_and_verifies_native_dll(tmp_path):
    source = tmp_path / "source"; source.mkdir()
    staged = tmp_path / "staged"; staged.mkdir()
    native = source / "target/release/librustdesk.dll"
    native.parent.mkdir(parents=True); native.write_bytes(b"unit-native-fixture")
    for name in ("rustdesk.exe", "librustdesk.dll", "flutter_windows.dll", "data/app.so", "data/icudtl.dat"):
        path = staged / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(native.read_bytes() if name == "librustdesk.dll" else b"unit-output-fixture")
    bundle = source / "flutter/build/windows/x64/runner/Release"
    bundle.mkdir(parents=True); (bundle / "stale.txt").write_text("keep previous evidence")
    produced = build_rustdesk.publish_flutter_bundle(source, staged)
    assert len(produced) == 5
    assert not (bundle / "stale.txt").exists()
    assert len(list(bundle.parent.glob("Release-before-*/stale.txt"))) == 1
    (staged / "librustdesk.dll").write_bytes(b"other-native-fixture")
    with pytest.raises(RuntimeError, match="proven native library"):
        build_rustdesk.publish_flutter_bundle(source, staged)
    assert (bundle / "librustdesk.dll").read_bytes() == native.read_bytes()
