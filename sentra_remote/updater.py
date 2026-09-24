"""Verified SENTRA Commander release updater."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


def _https_or_loopback(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return url
    raise ValueError("update URLs must use HTTPS unless loopback")


def fetch_manifest(url: str) -> dict[str, Any]:
    _https_or_loopback(url)
    with urllib.request.urlopen(url, timeout=15) as response:
        data = json.loads(response.read(1024 * 1024))
    required = {"version", "url", "sha256"}
    if not isinstance(data, dict) or not required <= data.keys():
        raise ValueError("invalid update manifest")
    _https_or_loopback(str(data["url"]))
    digest = str(data["sha256"]).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("invalid update sha256")
    return data


def download_verified(manifest: dict[str, Any], destination: Path) -> Path:
    url = _https_or_loopback(str(manifest["url"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            handle.write(chunk)
    if digest.hexdigest() != str(manifest["sha256"]).lower():
        destination.unlink(missing_ok=True)
        raise ValueError("update package sha256 mismatch")
    return destination


def _safe_extract(zip_path: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (root / member.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError("unsafe path in update archive")
        archive.extractall(root)


def verify_authenticode(executable: Path, thumbprint: str) -> None:
    expected = thumbprint.replace(" ", "").upper()
    command = (
        "$s=Get-AuthenticodeSignature -LiteralPath " + repr(str(executable)) + ";"
        "$o=[ordered]@{Status=$s.Status.ToString();Thumbprint=$s.SignerCertificate.Thumbprint};"
        "$o|ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout.strip())
    if data.get("Status") != "Valid":
        raise ValueError("update executable Authenticode signature is not valid")
    actual = str(data.get("Thumbprint") or "").replace(" ", "").upper()
    if expected and actual != expected:
        raise ValueError("update signer thumbprint mismatch")


def _version_key(value: str) -> tuple[tuple[int, int, int], int, str]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?", value.strip())
    if not match:
        raise ValueError("update version must be semantic X.Y.Z")
    core = tuple(int(match.group(i)) for i in (1, 2, 3))
    prerelease = match.group(4) or ""
    return core, 1 if not prerelease else 0, prerelease


def is_newer_version(candidate: str, current: str) -> bool:
    return _version_key(candidate) > _version_key(current)


def prepare_update(
    manifest_url: str,
    work_dir: Path | None = None,
    *,
    require_signature: bool = False,
) -> dict[str, Any]:
    manifest = fetch_manifest(manifest_url)
    work = Path(work_dir or tempfile.mkdtemp(prefix="sentra-update-"))
    archive = download_verified(manifest, work / "sentra-commander.zip")
    extract = work / "package"
    extract.mkdir(parents=True, exist_ok=True)
    _safe_extract(archive, extract)
    thumbprint = str(manifest.get("signer_thumbprint") or "")
    if require_signature and not thumbprint:
        raise ValueError("automatic update requires an Authenticode signer thumbprint")
    if thumbprint:
        executables = list(extract.rglob("*.exe"))
        if not executables:
            raise ValueError("signed update contains no executable")
        for executable in executables:
            verify_authenticode(executable, thumbprint)
    setup = extract / "SENTRA-Setup.exe"
    legacy = extract / "install.ps1"
    installer = setup if setup.is_file() else legacy
    if not installer.is_file():
        raise ValueError("update package is missing SENTRA-Setup.exe/install.ps1")
    return {
        "version": manifest["version"],
        "package_root": str(extract),
        "installer": str(installer),
        "installer_kind": "exe" if installer.suffix.lower() == ".exe" else "powershell",
    }


def apply_prepared_update(
    prepared: dict[str, Any],
    install_dir: Path,
    *,
    manifest_url: str = "",
    auto_update: bool = False,
    allow_unsigned_updates: bool = False,
) -> subprocess.Popen[str]:
    installer = Path(str(prepared["installer"]))
    if not installer.is_file():
        raise FileNotFoundError("prepared update installer missing")
    install_dir = Path(install_dir).expanduser().resolve()

    if str(prepared.get("installer_kind") or "") != "exe":
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(installer),
            "-InstallDir", str(install_dir),
            "-Upgrade",
            "-WaitPid", str(os.getpid()),
        ]
        if manifest_url:
            command += ["-UpdateManifestUrl", manifest_url]
        if auto_update:
            command.append("-AutoUpdate")
        if allow_unsigned_updates:
            command.append("-AllowUnsignedUpdates")
        return subprocess.Popen(command, cwd=installer.parent, text=True)

    package_root = Path(str(prepared.get("package_root") or installer.parent))
    helper = package_root / "sentra-update-helper.exe"
    if not helper.is_file():
        raise FileNotFoundError("update package is missing sentra-update-helper.exe")
    return subprocess.Popen(
        [
            str(helper), "apply",
            "--installer", str(installer),
            "--install-dir", str(install_dir),
            "--parent-pid", str(os.getpid()),
            "--version", str(prepared.get("version") or ""),
            "--manifest-url", manifest_url,
        ],
        cwd=helper.parent,
        text=True,
    )

def _ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _update_state_path() -> Path:
    return Path.home() / ".sentra" / "update-state.json"

def rollback_previous_update(install_dir: Path) -> subprocess.Popen[str]:
    install_dir = Path(install_dir).expanduser().resolve()
    installed_helper = install_dir / "sentra-update-helper.exe"
    if not installed_helper.is_file():
        raise FileNotFoundError("installed update helper is missing")
    temp_root = Path(tempfile.mkdtemp(prefix="sentra-rollback-helper-"))
    helper = temp_root / "sentra-update-helper.exe"
    shutil.copy2(installed_helper, helper)
    return subprocess.Popen(
        [
            str(helper), "rollback",
            "--install-dir", str(install_dir),
            "--parent-pid", str(os.getpid()),
        ],
        cwd=temp_root,
        text=True,
    )
