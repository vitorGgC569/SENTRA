"""Standalone SENTRA Windows desktop executable entrypoint."""
from __future__ import annotations
import os
import sys
from pathlib import Path
from sentra_canvas.__main__ import main as canvas_main

def root_dir() -> Path:
    if getattr(sys,"frozen",False):
        from sentra_remote.product import ProductPaths
        return ProductPaths.default(Path(sys.executable).resolve().parent).install_dir
    executable = Path(sys.executable if getattr(sys,"frozen",False) else __file__).resolve()
    for directory in [executable.parent,*executable.parents]:
        if (directory/"sentra_cli").is_dir() and (directory/"sentra_remote").is_dir():
            return directory
    path=Path(os.environ.get("LOCALAPPDATA") or Path.home())/"SENTRA"
    path.mkdir(parents=True,exist_ok=True)
    return path

def main(argv=None):
    arguments=list(sys.argv[1:] if argv is None else argv)
    if any(arg == "--root" or arg.startswith("--root=") for arg in arguments):
        return canvas_main(arguments)
    root=root_dir()
    defaults=["--root",str(root)]
    if getattr(sys,"frozen",False) and not any(
        arg == "--state-dir" or arg.startswith("--state-dir=") for arg in arguments
    ):
        from sentra_remote.product import ProductPaths
        defaults.extend(["--state-dir",str(ProductPaths.default(root).state_dir/"canvas")])
    return canvas_main([*defaults,*arguments])


if __name__=="__main__":
    raise SystemExit(main())
