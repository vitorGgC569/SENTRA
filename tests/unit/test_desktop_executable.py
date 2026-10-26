"""Exercise the actual Windows launcher and protect unrelated desktop files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from sentra_remote.windows_integration import install_desktop_executable


def test_desktop_executable_repairs_and_removes_only_owned_bytes(tmp_path):
    install, desktop = tmp_path / "installed", tmp_path / "Desktop"
    install.mkdir()
    source = install / "sentra-launcher.exe"
    source.write_bytes(b"first launcher")
    target = install_desktop_executable(install, desktop)
    assert target.name == "SENTRA.exe" and target.read_bytes() == source.read_bytes()
    source.write_bytes(b"second launcher")
    assert install_desktop_executable(install, desktop) == target
    assert target.read_bytes() == source.read_bytes()
    target.write_bytes(b"unrelated replacement")
    assert install_desktop_executable(install, desktop, remove=True) is None
    alternate = install_desktop_executable(install, desktop)
    assert alternate.name == "SENTRA (2).exe"
    assert alternate.read_bytes() == source.read_bytes()
    assert target.read_bytes() == b"unrelated replacement"
    assert install_desktop_executable(install, desktop, remove=True) == alternate
    assert not alternate.exists() and target.read_bytes() == b"unrelated replacement"


def test_interrupted_desktop_publish_can_be_retried(tmp_path, monkeypatch):
    install, desktop = tmp_path / "installed", tmp_path / "Desktop"
    install.mkdir()
    source = install / "sentra-launcher.exe"
    source.write_bytes(b"first launcher")
    target = install_desktop_executable(install, desktop)
    source.write_bytes(b"new launcher")
    replace = Path.replace
    def fail_publication(path, destination):
        if Path(destination) == target:
            raise PermissionError("file temporarily locked")
        return replace(path, destination)
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "replace", fail_publication)
        with pytest.raises(PermissionError):
            install_desktop_executable(install, desktop)
    assert target.read_bytes() == b"first launcher"
    install_desktop_executable(install, desktop)
    assert target.read_bytes() == b"new launcher"
    assert install_desktop_executable(install, desktop, remove=True) == target
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows native launcher")
def test_compiled_launcher_preserves_spaced_unicode_arguments_and_embeds_dot(tmp_path):
    import pefile
    from scripts.commander.build_desktop_launcher import build_desktop_launcher
    root = tmp_path / "Área de trabalho com espaços"
    root.mkdir()
    output = root / "started.json"
    child = root / "capture.py"
    child.write_text("import json, os, sys\nfrom pathlib import Path\n"
                     "Path(sys.argv[1]).write_text(json.dumps([os.getcwd(), sys.argv[2:]]))\n", encoding="utf-8")
    args = ["Dot azul", "acentuação", 'quote"inside']
    executable = build_desktop_launcher(root / "SENTRA.exe",
        development_command=[str(Path(sys.executable).with_name("pythonw.exe")), str(child), str(output), *args],
        development_directory=root)
    with pefile.PE(str(executable)) as pe:
        assert pe.OPTIONAL_HEADER.Subsystem == 2  # GUI: no terminal flashes.
        assert any(entry.id == 14 for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries)
        icons = next(entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries if entry.id == 3)
        assert len(icons.directory.entries) >= 7
    result = subprocess.run([str(executable)], timeout=15)
    assert result.returncode == 0
    deadline = time.monotonic() + 10
    while not output.is_file() and time.monotonic() < deadline:
        time.sleep(.05)
    assert json.loads(output.read_text()) == [str(root), args]
