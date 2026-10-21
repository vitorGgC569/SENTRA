"""Build the pinned QuickJS guest in a separate source/work/artifact directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ("sentra_quickjs_guest.c", "sentra_guest_platform.c", "sentra_guest_platform.h",
          "ABI.md", "inspect_wasm.py", "build.sh")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_quickjs(destination: Path, sdk: Path, *, bash=None, root=ROOT):
    root, sdk = Path(root).resolve(), Path(sdk).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("QuickJS build candidate already exists")
    guest = root / "sentra_code_mode/guest"
    inputs = [*INPUTS, *(path.relative_to(guest).as_posix()
                        for path in sorted((guest / "licenses").rglob("*")) if path.is_file())]
    sources = {name: _sha(guest / name) for name in inputs}
    legal = json.loads((guest / "licenses/PROVENANCE.json").read_text())
    if (sdk / "VERSION").read_text().strip() != legal["wasi_sdk"]["version"]:
        raise RuntimeError("WASI SDK differs from the static-runtime legal/provenance pin")
    if bash is None:
        git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        bash = str(git_bash) if os.name == "nt" and git_bash.is_file() else shutil.which("bash")
    if not bash:
        raise RuntimeError("Bash required for the checked-in QuickJS build driver")
    clang = sdk / "bin" / ("clang.exe" if os.name == "nt" else "clang")
    if not clang.is_file() or not (sdk / "share/wasi-sysroot").is_dir():
        raise FileNotFoundError("complete WASI SDK required")
    destination.mkdir(parents=True, exist_ok=False)
    destination = destination.resolve()
    copied = destination / "guest-source"
    copied.mkdir()
    for name, digest in sources.items():
        data = (guest / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError("QuickJS source changed before copy")
        (copied / name).parent.mkdir(parents=True, exist_ok=True)
        (copied / name).write_bytes(data)
    artifact = destination / "artifact"
    # The driver runs from this owned build directory. A relative output avoids
    # MSYS walking restricted Windows profile ancestors for mkdir -p.
    env = dict(os.environ, WASI_SDK=sdk.as_posix(), OUT_DIR="artifact", PYTHONIOENCODING="utf-8")
    with (destination / "build.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(bash), str(copied / "build.sh")], cwd=destination, env=env,
            stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            result = process.wait(timeout=600)
        except subprocess.TimeoutExpired:
            from scripts.commander.build_windows import _terminate_process_tree
            _terminate_process_tree(process)
            raise
    if result:
        raise RuntimeError("QuickJS build failed; inspect " + str(destination / "build.log"))
    if any(_sha(guest / name) != digest for name, digest in sources.items()):
        raise RuntimeError("QuickJS source changed during build")
    proof = json.loads((artifact / "provenance.json").read_text())
    if proof["source_sha256"] != sources or _sha(artifact / proof["guest"]) != proof["wasm_sha256"]:
        raise RuntimeError("QuickJS artifact does not match copied sources")
    from sentra_code_mode.guest.inspect_wasm import inspect_abi
    inspect_abi((artifact / proof["guest"]).read_bytes())
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--sdk", required=True, type=Path)
    parser.add_argument("--bash")
    args = parser.parse_args()
    proof = build_quickjs(args.destination, args.sdk, bash=args.bash)
    print(json.dumps({"artifact": str(args.destination.resolve() / "artifact"),
                      "wasm_sha256": proof["wasm_sha256"], "validated": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
