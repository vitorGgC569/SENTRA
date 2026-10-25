"""Native Windows setup envelope around SENTRA's owned install transaction."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

INNO_VERSION = "7.1.0"
INNO_INSTALLER_SHA256 = "0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f"


def find_compiler() -> Path:
    candidates = [os.environ.get("SENTRA_ISCC"), shutil.which("ISCC.exe")]
    for root in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")):
        if root:
            candidates.append(str(Path(root) / "Inno Setup 7/ISCC.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise FileNotFoundError("Inno Setup 7.1.0 compiler is required; set SENTRA_ISCC to ISCC.exe")


def build_inno(bundle: Path, output: Path, version: str, *, compiler: Path | None = None) -> Path:
    compiler = compiler or find_compiler()
    import re
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Inno product version must be numeric semver")
    probe = subprocess.run([str(compiler), "/?"], capture_output=True, text=True, check=False)
    if "7.1.0" not in probe.stdout + probe.stderr:
        raise RuntimeError("Inno Setup compiler version mismatch: expected 7.1.0")
    script = Path(__file__).with_name("sentra_setup.iss")
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(compiler), "/Qp", f"/DBundleRoot={Path(bundle).resolve()}",
                    f"/DOutputRoot={output.resolve()}", f"/DProductVersion={version}", str(script)],
                   check=True, timeout=1800)
    setup = output / "SENTRA-Setup.exe"
    if not setup.is_file():
        raise RuntimeError("Inno Setup did not produce SENTRA-Setup.exe")
    (output / "setup-engine.json").write_text(json.dumps({"schema": 1,
        "engine": "inno-setup", "engine_version": INNO_VERSION,
        "application_layout": "onedir-v1", "product_version": version,
        "account_setup": "sentra-managed-chromium", "native_providers_redirected": False}, indent=2) + "\n")
    return setup
