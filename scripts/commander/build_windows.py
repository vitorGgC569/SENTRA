"""Build Windows SENTRA Desktop executables and self-contained setup."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.commander.extension_identity import stamp_extension_identity

DEFAULT_EXCLUDES = (
    "torch", "torchvision", "torchaudio", "scipy", "pandas", "numba",
    "sklearn", "matplotlib", "numpy", "pygame",
)


def _common(name: str, entry: Path, dist: Path, work: Path, spec: Path) -> list[str]:
    args = [
        "--noconfirm", "--clean", "--onefile",
        "--name", name,
        "--distpath", str(dist),
        "--workpath", str(work / name),
        "--specpath", str(spec),
        "--paths", str(ROOT),
    ]
    for module in DEFAULT_EXCLUDES:
        args += ["--exclude-module", module]
    args.append(str(entry))
    return args


def _run(args: list[str]) -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", *args], cwd=ROOT, check=True)

def _build(
    name: str,
    entry_name: str,
    dist: Path,
    work: Path,
    spec: Path,
    *,
    windowed: bool = False,
    mcp_payload: bool = False,
    extra: list[str] | None = None,
) -> None:
    args = _common(name, ROOT / "scripts" / "commander" / entry_name, dist, work, spec)
    prefix: list[str] = []
    if windowed:
        prefix.append("--noconsole")
    if mcp_payload:
        prefix += ["--collect-all", "playwright", "--hidden-import", "pyarrow.parquet"]
    if extra:
        prefix += extra
    args[0:0] = prefix
    _run(args)


PAYLOAD_NAMES = (
    "sentra-agent.exe", "sentra-mcp.exe", "sentra-browser-relay.exe",
    "sentra-desktop.exe", "sentra-human.exe", "sentra-human-worker.exe",
    "sentra-diagnostics.exe", "sentra-admin.exe",
    "sentra-update-helper.exe", "sentra-oma.exe", "sentra.exe",
)


def build_payload(dist: Path, work: Path, spec: Path) -> None:
    for path in (dist, work, spec):
        path.mkdir(parents=True, exist_ok=True)

    _build("sentra-agent", "agent_entry.py", dist, work, spec, mcp_payload=True)
    _build("sentra-mcp", "mcp_entry.py", dist, work, spec, mcp_payload=True)
    _build("sentra-browser-relay", "browser_relay_entry.py", dist, work, spec)
    _build("sentra-desktop", "desktop_entry.py", dist, work, spec, windowed=True, mcp_payload=True)
    _build(
        "sentra-human", "human_entry.py", dist, work, spec, windowed=True,
        extra=[
            "--collect-all", "webview",
            "--add-data", f"{ROOT / 'sentra_remote' / 'human_ui'}{os.pathsep}human_ui",
        ],
    )
    _build("sentra-human-worker", "human_worker_entry.py", dist, work, spec, mcp_payload=True)
    _build("sentra-diagnostics", "diagnostics_entry.py", dist, work, spec)
    _build("sentra-admin", "admin_entry.py", dist, work, spec)
    _build("sentra-update-helper", "update_helper_entry.py", dist, work, spec)
    _build(
        "sentra-oma", "oma_entry.py", dist, work, spec, mcp_payload=True,
        extra=["--add-data", f"{ROOT / 'config.yaml'}{os.pathsep}."],
    )
    _build("sentra", "sentra_entry.py", dist, work, spec, mcp_payload=True)

def build_human(dist: Path, work: Path, spec: Path) -> None:
    for path in (dist, work, spec):
        path.mkdir(parents=True, exist_ok=True)
    _build(
        "sentra-human", "human_entry.py", dist, work, spec, windowed=True,
        extra=[
            "--collect-all", "webview",
            "--add-data", f"{ROOT / 'sentra_remote' / 'human_ui'}{os.pathsep}human_ui",
        ],
    )
    _build("sentra-human-worker", "human_worker_entry.py", dist, work, spec, mcp_payload=True)


def build_installer(dist: Path, work: Path, spec: Path) -> None:
    stamp_extension_identity(ROOT / "edge_extension")
    missing = [name for name in PAYLOAD_NAMES if not (dist / name).is_file()]
    if missing:
        raise RuntimeError("installer payload missing: " + ", ".join(missing))
    web_models = dist / "web-models" / "win-unpacked"
    if not (web_models / "Codex Web GPT.exe").is_file() or not (web_models / "resources" / "runtime" / "manifest.json").is_file():
        raise RuntimeError("packaged Electron Web Models payload is missing")
    build_state_path = dist / "web-models" / "integration-build.json"
    if not build_state_path.is_file():
        raise RuntimeError("Web Models integration build metadata is missing")
    build_state = json.loads(build_state_path.read_text(encoding="utf-8-sig"))
    patch = ROOT / "integrations" / "codex_chatgpt_web" / "sentra-upstream.patch"
    patch_hash = hashlib.sha256(patch.read_bytes()).hexdigest()
    if str(build_state.get("patch_sha256") or "").lower() != patch_hash:
        raise RuntimeError("Web Models payload was built from a stale SENTRA upstream patch")
    installer_extra: list[str] = []
    for name in PAYLOAD_NAMES:
        installer_extra += ["--add-data", f"{dist / name}{os.pathsep}payload"]
    installer_extra += [
        "--add-data", f"{ROOT / 'edge_extension'}{os.pathsep}edge_extension",
        "--add-data", f"{dist / 'web-models'}{os.pathsep}payload/web-models",
    ]
    _build(
        "SENTRA-Setup",
        "installer_entry.py",
        dist, work, spec,
        windowed=True,
        extra=installer_extra,
    )


def build(dist: Path, work: Path, spec: Path) -> None:
    build_payload(dist, work, spec)
    build_installer(dist, work, spec)


EXPECTED = (
    "sentra-agent.exe", "sentra-mcp.exe", "sentra-browser-relay.exe",
    "sentra-desktop.exe", "sentra-human.exe", "sentra-human-worker.exe",
    "sentra-diagnostics.exe", "sentra-admin.exe",
    "sentra-update-helper.exe", "sentra-oma.exe", "sentra.exe",
    "SENTRA-Setup.exe",
)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default=str(ROOT / "dist"))
    parser.add_argument("--work", default=str(ROOT / "build" / "commander"))
    parser.add_argument("--spec", default=str(ROOT / "build" / "commander-spec"))
    parser.add_argument("--clean-output", action="store_true")
    parser.add_argument("--phase", choices=("all", "payload", "human", "installer"), default="all")
    args = parser.parse_args()
    dist = Path(args.dist).resolve()
    work = Path(args.work).resolve()
    spec = Path(args.spec).resolve()
    if args.clean_output:
        for path in (dist, work, spec):
            shutil.rmtree(path, ignore_errors=True)
    if args.phase == "all":
        build(dist, work, spec)
        expected = EXPECTED
    elif args.phase == "payload":
        build_payload(dist, work, spec)
        expected = PAYLOAD_NAMES
    elif args.phase == "human":
        build_human(dist, work, spec)
        expected = ("sentra-human.exe", "sentra-human-worker.exe")
    else:
        build_installer(dist, work, spec)
        expected = ("SENTRA-Setup.exe",)
    for name in expected:
        target = dist / name
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"missing release executable: {target}")
        print(f"{name}: {target.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
