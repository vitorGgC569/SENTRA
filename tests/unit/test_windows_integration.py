import os
from pathlib import Path

import pytest

from sentra_remote.windows_integration import shortcuts

pytestmark=pytest.mark.skipif(os.name!="nt",reason="actual Windows WScript shortcuts")


def test_actual_shortcuts_are_idempotent_and_only_remove_owned_targets(tmp_path):
    programs=tmp_path/"programas";desktop=tmp_path/"Área de trabalho"
    desktop.mkdir()
    install=tmp_path/"installation ' one";other=tmp_path/"installation two"
    for folder in (install,other):
        folder.mkdir()
        for name in ("sentra-human.exe","sentra-canvas.exe"):(folder/name).write_bytes(b"owned fixture; never executed")
    kwargs={"programs_dir":programs,"desktop_dir":desktop}
    initial=shortcuts(install,**kwargs)
    assert len(initial["paths"])==3 and all(Path(path).is_file() for path in initial["paths"])
    assert shortcuts(install,**kwargs)["paths"]==initial["paths"]
    assert shortcuts(other,remove=True,**kwargs)["paths"]==[]
    assert all(Path(path).is_file() for path in initial["paths"])
    shortcuts(other,**kwargs)
    assert shortcuts(install,remove=True,**kwargs)["paths"]==[]
    assert len(shortcuts(other,remove=True,**kwargs)["paths"])==3
    assert not any(Path(path).exists() for path in initial["paths"])
