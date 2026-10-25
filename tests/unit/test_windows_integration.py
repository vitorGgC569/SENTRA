import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sentra_remote.windows_integration import shortcuts

pytestmark=pytest.mark.skipif(os.name!="nt",reason="actual Windows Shell Link APIs")


def _read_shortcut(path):
    import pythoncom
    from win32com.shell import shell
    def read():
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        try:
            link=pythoncom.CoCreateInstance(shell.CLSID_ShellLink,None,pythoncom.CLSCTX_INPROC_SERVER,shell.IID_IShellLink)
            link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(path),0)
            return link.GetPath(shell.SLGP_RAWPATH)[0],link.GetIconLocation(),link.GetWorkingDirectory()
        finally:
            link=None
            pythoncom.CoUninitialize()
    with ThreadPoolExecutor(max_workers=1) as worker:
        return worker.submit(read).result()


def test_actual_shortcuts_are_idempotent_and_only_remove_owned_targets(tmp_path,monkeypatch):
    def no_external_shell(*args,**kwargs):
        raise AssertionError("Shortcut registration must not start PowerShell or another shell")
    monkeypatch.setattr(subprocess,"run",no_external_shell)
    programs=tmp_path/"programas";desktop=tmp_path/"Área de trabalho"
    desktop.mkdir()
    install=tmp_path/"installation ' one";other=tmp_path/"installation two"
    for folder in (install,other):
        folder.mkdir()
        for name in ("sentra-human.exe","sentra-canvas.exe"):(folder/name).write_bytes(b"owned fixture; never executed")
    kwargs={"programs_dir":programs,"desktop_dir":desktop}
    initial=shortcuts(install,**kwargs)
    assert len(initial["paths"])==3 and all(Path(path).is_file() for path in initial["paths"])
    for path,name in ((programs/"SENTRA/SENTRA Desktop.lnk","sentra-human.exe"),
                      (programs/"SENTRA/SENTRA Canvas.lnk","sentra-canvas.exe"),
                      (desktop/"SENTRA.lnk","sentra-canvas.exe")):
        target,icon,directory=_read_shortcut(path)
        assert Path(target)==install/name
        assert icon==(str(install/name),0)
        assert Path(directory)==install
    assert shortcuts(install,**kwargs)["paths"]==initial["paths"]
    assert shortcuts(other,remove=True,**kwargs)["paths"]==[]
    assert all(Path(path).is_file() for path in initial["paths"])
    shortcuts(other,**kwargs)
    assert shortcuts(install,remove=True,**kwargs)["paths"]==[]
    assert len(shortcuts(other,remove=True,**kwargs)["paths"])==3
    assert not any(Path(path).exists() for path in initial["paths"])


def test_shortcuts_support_a_caller_with_multithreaded_com(tmp_path):
    import pythoncom
    from win32com.shell import shell
    install=tmp_path/"installed";install.mkdir()
    for name in ("sentra-human.exe","sentra-canvas.exe"):
        (install/name).write_bytes(b"owned fixture; never executed")
    def caller():
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        try:
            result=shortcuts(install,programs_dir=tmp_path/"programs",desktop_dir=tmp_path/"desktop")
            # The caller must retain its initialized COM apartment afterwards.
            value=pythoncom.CoCreateInstance(shell.CLSID_ShellLink,None,pythoncom.CLSCTX_INPROC_SERVER,shell.IID_IShellLink)
            assert value is not None
            value=None
            return result
        finally:
            pythoncom.CoUninitialize()
    with ThreadPoolExecutor(max_workers=1) as worker:
        assert len(worker.submit(caller).result()["paths"])==3


def test_desktop_executable_migrates_only_the_owned_legacy_link(tmp_path):
    install=tmp_path/"installed";other=tmp_path/"other"
    for folder in (install,other):
        folder.mkdir()
        for name in ("sentra-human.exe","sentra-canvas.exe","sentra-launcher.exe"):
            (folder/name).write_bytes(b"owned fixture; never executed")
    desktop=tmp_path/"desktop";programs=tmp_path/"programs"
    kwargs=dict(programs_dir=programs,desktop_dir=desktop)
    shortcuts(install,**kwargs)
    result=shortcuts(install,desktop_executable=True,**kwargs)
    assert not (desktop/"SENTRA.lnk").exists()
    assert (desktop/"SENTRA.exe").read_bytes()==(install/"sentra-launcher.exe").read_bytes()
    assert len(result["paths"])==3
    shortcuts(other,programs_dir=tmp_path/"other-programs",desktop_dir=desktop)
    shortcuts(install,desktop_executable=True,**kwargs)
    assert Path(_read_shortcut(desktop/"SENTRA.lnk")[0])==other/"sentra-canvas.exe"
    shortcuts(install,remove=True,desktop_executable=True,**kwargs)
    assert not (desktop/"SENTRA.exe").exists()
    assert (desktop/"SENTRA.lnk").is_file()


def test_packaged_dependency_probe_uses_only_its_disposable_folders(tmp_path,monkeypatch):
    import json
    from win32com.shell import shell
    from sentra_remote.windows_integration import check_shortcuts_runtime
    def no_profile_lookup(*args):
        raise AssertionError("Fixture probe must not inspect the user's shortcut folders")
    monkeypatch.setattr(shell,"SHGetFolderPath",no_profile_lookup)
    report=tmp_path/"native-runtime.json"
    value=check_shortcuts_runtime(report)
    assert value["ok"] and value["created"] and value["idempotent"] and value["removed"]
    assert value["starts_product_services"] is False and value["accesses_browser_or_account"] is False
    assert value["changes_user_shortcut_folders"] is False
    assert json.loads(report.read_text())==value


def test_corrupt_legacy_link_and_unowned_desktop_exe_do_not_block_install(tmp_path):
    install=tmp_path/"app";install.mkdir();desktop=tmp_path/"desktop";desktop.mkdir()
    for name in ("sentra-human.exe","sentra-canvas.exe","sentra-launcher.exe"):
        (install/name).write_bytes(b"fixture; never execute")
    (desktop/"SENTRA.lnk").write_bytes(b"broken legacy shortcut")
    (desktop/"SENTRA.exe").write_bytes(b"previous unowned launcher")
    options=dict(programs_dir=tmp_path/"programs",desktop_dir=desktop,desktop_executable=True)
    result=shortcuts(install,**options)
    assert (desktop/"SENTRA.lnk").read_bytes()==b"broken legacy shortcut"
    assert (desktop/"SENTRA.exe").read_bytes()==b"previous unowned launcher"
    assert (desktop/"SENTRA (2).exe").read_bytes()==b"fixture; never execute"
    assert "unreadable_legacy_shortcut_preserved" in result["warnings"]
    assert shortcuts(install,**options)["paths"]==result["paths"]
    shortcuts(install,remove=True,**options)
    assert not (desktop/"SENTRA (2).exe").exists()
    assert (desktop/"SENTRA.exe").read_bytes()==b"previous unowned launcher"


def test_corrupt_launcher_receipt_is_preserved_and_repair_is_idempotent(tmp_path):
    from sentra_remote.windows_integration import install_desktop_executable
    app=tmp_path/"app";app.mkdir();desktop=tmp_path/"desktop";desktop.mkdir()
    (app/"sentra-launcher.exe").write_bytes(b"new")
    (app/"desktop-launcher.json").write_bytes(b"{broken")
    (desktop/"SENTRA.exe").write_bytes(b"old")
    target=install_desktop_executable(app,desktop)
    assert target.name=="SENTRA (2).exe"
    assert next(app.glob("desktop-launcher.previous-*.json")).read_bytes()==b"{broken"
    assert install_desktop_executable(app,desktop)==target


def test_unknown_desktop_file_appearing_during_publish_is_not_overwritten(tmp_path,monkeypatch):
    from sentra_remote import windows_integration as integration
    app=tmp_path/"app";app.mkdir();desktop=tmp_path/"desktop";desktop.mkdir()
    (app/"sentra-launcher.exe").write_bytes(b"new")
    copy=integration.shutil.copy2
    def race(source,target):
        result=copy(source,target)
        (desktop/"SENTRA.exe").write_bytes(b"concurrent unrelated file")
        return result
    monkeypatch.setattr(integration.shutil,"copy2",race)
    with pytest.raises(FileExistsError):integration.install_desktop_executable(app,desktop)
    assert (desktop/"SENTRA.exe").read_bytes()==b"concurrent unrelated file"


def test_desktop_native_shortcut_probe_does_not_start_the_application(tmp_path,monkeypatch):
    from sentra_remote import desktop
    def no_application(*args,**kwargs):
        raise AssertionError("Diagnostic must not open the main application")
    monkeypatch.setattr(desktop,"SentraDesktop",no_application)
    assert desktop.main(["--shortcuts-check","--shortcuts-check-report",str(tmp_path/"probe.json")])==0
