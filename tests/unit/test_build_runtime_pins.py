"""Build dependencies must remain byte-identical across clean Windows checkouts."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.commander.runtime_dependencies import require_wasmtime_pin

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != "nt", reason="Windows SDK selection")
def test_checked_in_wasmtime_pin_matches_installed_locked_wheel(monkeypatch):
    monkeypatch.delenv("SENTRA_BUILD_RUNTIME_PINS_FILE", raising=False)
    record = require_wasmtime_pin()
    assert record["version"] == "49.0.0"
    assert record["files"] and record["license_files"]
    assert record["validated"] is False  # Dependency integrity alone is not runtime QA.


@pytest.mark.skipif(os.name != "nt", reason="Windows SDK selection")
@pytest.mark.parametrize("change", ["native", "license", "version"])
def test_changed_sdk_selection_is_rejected_before_packaging(tmp_path, monkeypatch, change):
    value = json.loads((ROOT / "scripts/commander/wasmtime-win-amd64.json").read_text())
    spec = value["wasmtime"]
    if change == "version":
        spec["version"] = "0.0.1"
    else:
        key = "files" if change == "native" else "license_files"
        spec[key][next(iter(spec[key]))] = "0" * 64
    selected = tmp_path / "pins.json"
    selected.write_text(json.dumps(value))
    monkeypatch.setenv("SENTRA_BUILD_RUNTIME_PINS_FILE", str(selected))
    with pytest.raises((PermissionError, RuntimeError)):
        require_wasmtime_pin()


def test_guest_legal_bytes_match_the_immutable_upstream_pins():
    root = ROOT / "sentra_code_mode/guest/licenses"
    record = json.loads((root / "PROVENANCE.json").read_text())
    for entry in record["files"]:
        raw = (root / entry["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"], entry["path"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == entry["git_blob"]


@pytest.mark.skipif(shutil.which("git") is None, reason="Git checkout integration")
def test_guest_legal_pins_and_bash_driver_survive_windows_checkout(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    shutil.copy2(ROOT / ".gitattributes", source / ".gitattributes")
    shutil.copytree(ROOT / "sentra_code_mode/guest", source / "sentra_code_mode/guest",
                    ignore=shutil.ignore_patterns("__pycache__", "build-tmp", "dist"))
    def git(*args):
        subprocess.run(["git", "-c", "core.autocrlf=true", "-c", "core.longpaths=true", *args],
                       cwd=source, check=True, capture_output=True)
    git("init", "--quiet")
    git("add", "--force", ".")
    checkout = tmp_path / "checkout"
    git("checkout-index", "--all", "--prefix=" + checkout.as_posix() + "/")
    guest = checkout / "sentra_code_mode/guest"
    assert b"\r\n" not in (guest / "build.sh").read_bytes()
    record = json.loads((guest / "licenses/PROVENANCE.json").read_text())
    for entry in record["files"]:
        assert hashlib.sha256((guest / "licenses" / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
