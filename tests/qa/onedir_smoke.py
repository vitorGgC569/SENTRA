"""Build and run one real onedir component without touching the installed app."""
from pathlib import Path
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.commander.build_windows import _build

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise FileExistsError("choose a new isolated probe directory")
    root.mkdir(parents=True)
    dist = root / "dist"
    _build("sentra-bundle-probe", "bundle_probe_entry.py", dist, root / "work", root / "spec",
           extra=["--collect-all", "playwright"])
    probe = subprocess.run([str(dist / "sentra-bundle-probe.exe")], capture_output=True,
                           text=True, timeout=45, cwd=root)
    if probe.returncode:
        raise RuntimeError("frozen onedir probe failed: " + probe.stderr[-1000:])
    result = json.loads(probe.stdout)
    assert all(result[name] is True for name in ("frozen", "support_is_installed_sibling", "driver_available", "driver_runs"))
    assert result["support_directory"] == "_runtime_sentra-bundle-probe"
    (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))

if __name__ == "__main__":
    main()
