import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentra_remote import gui_runtime as gui
from scripts.commander import build_windows as build


def test_missing_bundled_tcl_resources_fails_without_opening_window(tmp_path, monkeypatch):
    monkeypatch.setattr(gui.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui.sys, "_MEIPASS", str(tmp_path), raising=False)
    report = tmp_path / "gui-check.json"
    result = gui.check_gui_runtime(report)
    assert result["ok"] is False
    assert result["tk_window_created"] is False
    assert result["error_type"] == "RuntimeError"
    assert result["starts_product_services"] is False
    assert json.loads(report.read_text()) == result


def test_frozen_gui_uses_its_own_resources_instead_of_external_environment(tmp_path, monkeypatch):
    for folder, name in (("_tcl_data", "init.tcl"), ("_tk_data", "tk.tcl")):
        path = tmp_path / folder / name
        path.parent.mkdir()
        path.write_text("resource")
    monkeypatch.setattr(gui.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("TCL_LIBRARY", "unrelated")
    monkeypatch.setenv("TK_LIBRARY", "unrelated")
    gui.prepare_gui_runtime()
    assert gui.os.environ["TCL_LIBRARY"] == gui._native_path(tmp_path / "_tcl_data")
    assert gui.os.environ["TK_LIBRARY"] == gui._native_path(tmp_path / "_tk_data")


@pytest.mark.parametrize("returncode,frozen,widgets", [(2, True, True), (0, False, True), (0, True, False)])
def test_builder_rejects_failed_or_nonfrozen_window_evidence(tmp_path, monkeypatch, returncode, frozen, widgets):
    monkeypatch.setattr(build, "LOCAL_BUILD_ROOT", tmp_path)
    def start(command, **kwargs):
        report = Path(command[-1])
        report.write_text(json.dumps(dict(ok=True, frozen=frozen, tk_window_created=True,
                                         ttk_widgets_created=widgets, window_destroyed=True)))
        return SimpleNamespace(wait=lambda timeout: returncode)
    monkeypatch.setattr(build.subprocess, "Popen", start)
    with pytest.raises(RuntimeError, match="Tcl/Tk window check failed"):
        build._verify_frozen_gui(tmp_path / "sentra-desktop.exe")
