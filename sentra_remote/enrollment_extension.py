"""Stage the two browser packages and register only our native host in HKCU."""
from __future__ import annotations

import hashlib
import json
import shutil
import os
import subprocess
import zipfile
from pathlib import Path

from .enrollment_bridge import CHROMIUM_ID, FIREFOX_ID, HOST_NAME, PROTOCOL

FIREFOX_SIGNED_NAME = "firefox-signed.xpi"
FIREFOX_SIGNED_SHA256 = "91d1961717b51066fd807efdf689e86779fc9db13bb6b855cee8587798440862"


def verified_firefox_package(path: Path) -> Path:
    """Accept only the exact Mozilla-approved private package, without rewriting it."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
        raise ValueError("firefox_signed_bridge_missing")
    if hashlib.sha256(path.read_bytes()).hexdigest() != FIREFOX_SIGNED_SHA256:
        raise ValueError("firefox_signed_bridge_checksum_mismatch")
    return path


def installed_firefox_package(install_dir: Path) -> Path:
    return verified_firefox_package(Path(install_dir) / "browser-enrollment" / FIREFOX_SIGNED_NAME)


def _stage_signed_firefox(source: Path, destination: Path) -> None:
    package = verified_firefox_package(source / FIREFOX_SIGNED_NAME)
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        expected = {"manifest.json", "background.js", "dom.js", "LICENSE",
                    "META-INF/cose.manifest", "META-INF/cose.sig", "META-INF/manifest.mf",
                    "META-INF/mozilla.sf", "META-INF/mozilla.rsa"}
        if len(names) != len(expected) or set(names) != expected:
            raise ValueError("firefox_signed_bridge_contents_invalid")
        # Mozilla reserializes manifest JSON when signing. Compare its complete
        # value, and require identical JavaScript except checkout line endings.
        manifest = json.loads((destination / "firefox/manifest.json").read_text(encoding="utf-8"))
        if json.loads(archive.read("manifest.json")) != manifest:
            raise ValueError("firefox_signed_bridge_source_mismatch")
        for name in ("background.js", "dom.js"):
            reviewed = (destination / "firefox" / name).read_text(encoding="utf-8")
            signed = archive.read(name).decode("utf-8").replace("\r\n", "\n")
            if reviewed != signed:
                raise ValueError("firefox_signed_bridge_source_mismatch")
    shutil.copyfile(package, destination / FIREFOX_SIGNED_NAME)


def _find_firefox() -> Path | None:
    """Locate the installed app through App Paths and standard install folders."""
    candidates = []
    if os.name == "nt":
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe",
                                        0, winreg.KEY_READ | view) as key:
                        value, kind = winreg.QueryValueEx(key, "")
                        if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                            candidates.append(Path(os.path.expandvars(value.strip('"'))))
                except OSError:
                    pass
    for key, suffix in (("ProgramFiles", "Mozilla Firefox/firefox.exe"),
                        ("ProgramFiles(x86)", "Mozilla Firefox/firefox.exe"),
                        ("LOCALAPPDATA", "Mozilla Firefox/firefox.exe"),
                        ("LOCALAPPDATA", "Programs/Mozilla Firefox/firefox.exe")):
        if os.environ.get(key): candidates.append(Path(os.environ[key]) / suffix)
    return next((path for path in candidates if path.name.lower() == "firefox.exe" and path.is_file()), None)


def open_firefox_bridge_installation(install_dir: Path, *, popen=None) -> dict:
    """Show the signed file and Add-ons page; the browser owns installation consent."""
    package = installed_firefox_package(install_dir)
    popen = subprocess.Popen if popen is None else popen
    firefox = _find_firefox()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if firefox is not None:
        popen([str(firefox), "about:addons"], creationflags=flags)
    explorer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe"
    popen([str(explorer), "/select,", str(package.resolve())], creationflags=flags)
    return {"package": str(package), "browser_opened": firefox is not None}

PUBLIC_KEY = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA4G+JjYpMebMDdGhdag5huBaCkKMmvMB3M1Ji2aZNfA6yInc6FSmHhMd/BjY9c3i+o+DgZ4+SQXIFM+BoXMhtCw2pVjL7AfePZausFhEEs0oAMCHNt4oK7pSw3CCtp2cxYHadbGlSLPsCPmsqBnnMn6idkkQrGrPc7ViWTsRWtVMK/EP4yQiJwXiCUlKbv2Z7aZP0JKKxcvl8Xy4+6fUIzrgcb0bz0AXaymuqsJaJQCzxYqZjTApw//9cXX0hoGvy09jQq/NaOlGLWzo/ztOUEW09gZ2hCvI1VCZ85kDDb2gu0usjd+FAJvU5Yhb+FJEmcfuJDkDFLR5CNHhWXMvLRwIDAQAB"
REGISTRY_ROOTS = (
    r"Software\Google\Chrome\NativeMessagingHosts",
    r"Software\Microsoft\Edge\NativeMessagingHosts",
    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
    r"Software\Vivaldi\NativeMessagingHosts",
    r"Software\Chromium\NativeMessagingHosts",
    r"Software\Opera Software\NativeMessagingHosts",
    r"Software\Mozilla\NativeMessagingHosts",
)


def stage_extensions(source: Path, destination: Path) -> None:
    import base64
    public_id = hashlib.sha256(base64.b64decode(PUBLIC_KEY)).hexdigest()[:32].translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))
    if public_id != CHROMIUM_ID:
        raise ValueError("enrollment_extension_id_mismatch")
    source, destination = Path(source), Path(destination)
    common = {"manifest_version": 3, "name": "SENTRA Setup DOM Bridge", "version": "0.1.2",
              "description": "Conecta o Setup SENTRA ao DOM da plataforma OpenAI no perfil atual, com sua autorização.",
              "permissions": ["nativeMessaging", "tabs", "scripting", "alarms"],
              "host_permissions": ["https://platform.openai.com/*"],
              "action": {"default_title": "Conectar ao Setup SENTRA"}}
    for family in ("chromium", "firefox"):
        target = destination / family
        target.mkdir(parents=True, exist_ok=True)
        manifest = dict(common)
        if family == "firefox":
            manifest.update(background={"scripts": ["background.js"]},
                            browser_specific_settings={"gecko": {"id": FIREFOX_ID, "strict_min_version": "128.0",
                                "data_collection_permissions": {"required": ["authenticationInfo", "websiteContent"]}}})
        else:
            manifest.update(background={"service_worker": "background.js"}, key=PUBLIC_KEY)
        (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for name in ("background.js", "dom.js"):
            candidate = source / name
            if candidate.is_symlink() or not candidate.is_file():
                raise FileNotFoundError("enrollment_extension_source_missing")
            if name == "dom.js":
                from .openai_browser_enrollment import _TUNNEL_DOM, _KEY_DOM
                text = candidate.read_text(encoding="utf-8")
                if text.count("/*__EXTRACTORS__*/") != 1:
                    raise ValueError("enrollment_extractors_marker_invalid")
                text = text.replace("/*__EXTRACTORS__*/", f"const extractTunnels = {_TUNNEL_DOM};\nconst extractKey = {_KEY_DOM};")
                (target / name).write_text(text, encoding="utf-8")
            else:
                shutil.copyfile(candidate, target / name)
    _stage_signed_firefox(source, destination)
    (destination / "distribution.json").write_text(json.dumps({
        "schema": 1, "chromium_id": CHROMIUM_ID, "firefox_id": FIREFOX_ID,
        "chrome_web_store_url": None, "edge_addons_url": None,
        "firefox_signed_xpi": FIREFOX_SIGNED_NAME, "firefox_signed_sha256": FIREFOX_SIGNED_SHA256,
        "firefox_channel": "unlisted", "firefox_signed_package_available": True,
        "browser_installation_consent_required": True,
        "production_distribution_ready": False,
        "reason": "The pinned Mozilla-approved Firefox XPI is included for private installation with browser consent. Chromium still needs a supported installation channel; no public listing is requested.",
    }, indent=2) + "\n", encoding="utf-8")


def register_native_host(install_dir: Path, state_dir: Path, *, registry=None):
    if registry is None:
        import winreg as registry
    root = Path(install_dir).resolve()
    executable = root / "sentra-browser-relay.exe"
    if not executable.is_file() or not (root / ".sentra-install.json").is_file():
        raise FileNotFoundError("enrollment_native_host_missing")
    target = root / "browser-enrollment"
    # Verify every existing registration before writing any key or manifest.
    for parent in REGISTRY_ROOTS:
        family = "firefox" if "Mozilla" in parent else "chromium"
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, parent + "\\" + HOST_NAME, 0, registry.KEY_READ) as key:
                existing, _ = registry.QueryValueEx(key, None)
        except FileNotFoundError:
            continue
        if Path(existing).resolve() != (target / f"native-{family}.json").resolve():
            raise RuntimeError("enrollment_native_host_owned_by_other_installation")
    target.mkdir(exist_ok=True)
    config = {"protocol": PROTOCOL, "state_dir": str(Path(state_dir).resolve())}
    (target / "native-config.json").write_text(json.dumps(config), encoding="utf-8")
    paths = {}
    for family in ("chromium", "firefox"):
        manifest = {"name": HOST_NAME, "description": "SENTRA authorized Setup DOM connection", "type": "stdio", "path": str(executable)}
        manifest.update({"allowed_extensions": [FIREFOX_ID]} if family == "firefox" else {"allowed_origins": [f"chrome-extension://{CHROMIUM_ID}/"]})
        path = target / f"native-{family}.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        paths[family] = str(path)
    for parent in REGISTRY_ROOTS:
        family = "firefox" if "Mozilla" in parent else "chromium"
        with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, parent + "\\" + HOST_NAME, 0, registry.KEY_SET_VALUE | registry.KEY_QUERY_VALUE) as key:
            # Refuse to hijack a host registered by another SENTRA installation.
            try:
                existing, _ = registry.QueryValueEx(key, None)
            except FileNotFoundError:
                existing = None
            if existing and Path(existing).resolve() != Path(paths[family]).resolve():
                raise RuntimeError("enrollment_native_host_owned_by_other_installation")
            registry.SetValueEx(key, "", 0, registry.REG_SZ, paths[family])
    return {"registered": True, "browsers": len(REGISTRY_ROOTS), "production_extension_distribution_ready": False}


def unregister_native_host(install_dir: Path, *, registry=None):
    if registry is None:
        import winreg as registry
    target = Path(install_dir).resolve() / "browser-enrollment"
    expected = {str((target / f"native-{family}.json").resolve()).casefold() for family in ("firefox", "chromium")}
    for parent in REGISTRY_ROOTS:
        name = parent + "\\" + HOST_NAME
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, name, 0, registry.KEY_READ) as key:
                value, _ = registry.QueryValueEx(key, None)
            if str(Path(value).resolve()).casefold() in expected:
                registry.DeleteKey(registry.HKEY_CURRENT_USER, name)
        except FileNotFoundError:
            pass
