"""Build reproducible Windows SENTRA Commander executables with PyInstaller."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXCLUDES = (
    "torch",
    "torchvision",
    "torchaudio",
    "scipy",
    "pandas",
    "numba",
    "sklearn",
    "matplotlib",
    "numpy",
    "pygame",
)


def _common(name: str, entry: Path, dist: Path, work: Path, spec: Path) -> list[str]:
    args = [
        "--noconfirm",
        "--clean",
        "--onefile",
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


def _run_pyinstaller(args: list[str]) -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", *args], cwd=ROOT, check=True)


def build(dist: Path, work: Path, spec: Path) -> None:
    for path in (dist, work, spec):
        path.mkdir(parents=True, exist_ok=True)

    agent = _common(
        "sentra-agent",
        ROOT / "scripts" / "commander" / "agent_entry.py",
        dist, work, spec,
    )
    # Playwright ships a Node driver and package data that are required for browser tools.
    agent[0:0] = [
        "--collect-all", "playwright",
        "--hidden-import", "pyarrow.parquet",
    ]
    _run_pyinstaller(agent)

    tray = _common(
        "sentra-tray",
        ROOT / "scripts" / "commander" / "tray_entry.py",
        dist, work, spec,
    )
    tray[0:0] = ["--noconsole"]
    _run_pyinstaller(tray)

    diagnostics = _common(
        "sentra-diagnostics",
        ROOT / "scripts" / "commander" / "diagnostics_entry.py",
        dist, work, spec,
    )
    _run_pyinstaller(diagnostics)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default=str(ROOT / "dist"))
    parser.add_argument("--work", default=str(ROOT / "build" / "commander"))
    parser.add_argument("--spec", default=str(ROOT / "build" / "commander-spec"))
    parser.add_argument("--clean-output", action="store_true")
    args = parser.parse_args()
    dist, work, spec = map(lambda value: Path(value).resolve(), (args.dist, args.work, args.spec))
    if args.clean_output:
        for path in (dist, work, spec):
            shutil.rmtree(path, ignore_errors=True)
    build(dist, work, spec)
    for name in ("sentra-agent.exe", "sentra-tray.exe", "sentra-diagnostics.exe"):
        target = dist / name
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"missing release executable: {target}")
        print(f"{name}: {target.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
