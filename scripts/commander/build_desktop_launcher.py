"""Compile a small Windows GUI launcher with the real Dot ICO and no console."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def build_desktop_launcher(destination, *, development_command=None, development_directory=None):
    destination = Path(destination).resolve()
    compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.is_file():
        raise FileNotFoundError("Windows .NET Framework C# compiler required on the build machine")
    source = (ROOT / "scripts/commander/desktop_launcher.cs").read_text(encoding="utf-8")
    command = list(development_command or [])
    values = {"DEV_EXECUTABLE": command[0] if command else "",
              "DEV_ARGUMENTS": subprocess.list2cmdline(command[1:]) if command else "",
              "DEV_DIRECTORY": str(Path(development_directory).resolve()) if development_directory else ""}
    if command and (not Path(command[0]).is_absolute() or not Path(command[0]).is_file() or not development_directory):
        raise ValueError("development launcher requires an explicit executable and checkout")
    for key, value in values.items():
        source = source.replace('/*' + key + '*/ ""', json.dumps(value, ensure_ascii=True))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sentra-launcher-build-") as temporary:
        staged = Path(temporary)
        (staged / "launcher.cs").write_text(source, encoding="utf-8-sig")
        output = staged / "SENTRA.exe"
        result = subprocess.run([str(compiler), "/nologo", "/target:winexe", "/optimize+",
                    "/reference:System.Windows.Forms.dll", "/win32icon:" + str(ROOT / "sentra_canvas/assets/SENTRA-DOT.ico"),
                    "/out:" + str(output), str(staged / "launcher.cs")],
                    capture_output=True, text=True, timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError("desktop launcher compilation failed: " + result.stdout[-2000:])
        pending = destination.with_suffix(".pending")
        pending.write_bytes(output.read_bytes())
        pending.replace(destination)
    return destination
