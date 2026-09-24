"""Build a per-user Windows MSI for SENTRA Desktop using stdlib msilib."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import msilib
from msilib import CAB, Directory, Feature, add_data, add_tables, init_database, schema, sequence, text

from sentra_version import PRODUCT_VERSION

MANUFACTURER = "SENTRA"
UPGRADE_CODE = "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, "https://sentra.local/windows-desktop")).upper() + "}"


def _product_code(version: str) -> str:
    return "{" + str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"https://sentra.local/windows-desktop/{version}"
    )).upper() + "}"


def _component_id(relative: Path) -> str:
    raw = "cmp_" + "_".join(relative.parts or ("root",))
    return msilib.make_id(raw)


def _directory_id(relative: Path) -> str:
    raw = "dir_" + "_".join(relative.parts or ("root",))
    return msilib.make_id(raw)


def _add_tree(db, cab: CAB, feature: Feature, install: Directory, source: Path) -> dict[str, str]:
    file_ids: dict[str, str] = {}
    dirs: dict[Path, Directory] = {Path("."): install}
    directories = sorted(
        (p for p in source.rglob("*") if p.is_dir()),
        key=lambda p: (len(p.relative_to(source).parts), str(p).lower()),
    )
    for directory in directories:
        relative = directory.relative_to(source)
        parent_rel = relative.parent if relative.parent != Path("") else Path(".")
        parent = dirs[parent_rel]
        dirs[relative] = Directory(
            db, cab, parent, directory.name,
            _directory_id(relative), directory.name,
        )

    files_by_dir: dict[Path, list[Path]] = {}
    for file in source.rglob("*"):
        if file.is_file():
            relative = file.relative_to(source)
            if relative.as_posix() == "SENTRA-Setup.exe":
                continue
            if relative.name.startswith("tunnel-client-v") and relative.name.endswith("-windows-amd64.zip"):
                continue
            parent = relative.parent if relative.parent != Path("") else Path(".")
            files_by_dir.setdefault(parent, []).append(file)

    for relative, files in sorted(files_by_dir.items(), key=lambda item: str(item[0]).lower()):
        directory = dirs[relative]
        component = _component_id(relative)
        key_name = sorted(files, key=lambda p: p.name.lower())[0].name
        directory.start_component(component, feature, 0, keyfile=key_name)
        for file in sorted(files, key=lambda p: p.name.lower()):
            logical = directory.add_file(file.name)
            file_ids[file.relative_to(source).as_posix()] = logical
    return file_ids


def build_msi(source: Path, output: Path, version: str) -> Path:
    source = source.resolve()
    output = output.resolve()
    required = {
        "sentra-desktop.exe", "sentra-human.exe", "sentra-human-worker.exe",
        "sentra-mcp.exe", "sentra-browser-relay.exe",
        "sentra-agent.exe", "sentra-diagnostics.exe", "sentra-admin.exe",
        "sentra-update-helper.exe", "sentra-oma.exe", "sentra.exe",
        "tunnel-client.exe",
    }
    missing = sorted(name for name in required if not (source / name).is_file())
    if missing:
        raise FileNotFoundError("MSI staging is missing: " + ", ".join(missing))
    if not (source / "edge_extension" / "manifest.json").is_file():
        raise FileNotFoundError("MSI staging is missing edge_extension")
    web_models = source / "web-models" / "win-unpacked"
    if not (web_models / "Codex Web GPT.exe").is_file() or not (web_models / "resources" / "runtime" / "manifest.json").is_file():
        raise FileNotFoundError("MSI staging is missing Web Models payload")
    if not (source / "web-models" / "licenses" / "codex-chatgpt-web" / "LICENSE").is_file():
        raise FileNotFoundError("MSI staging is missing codex-chatgpt-web license notice")
    if not (source / "web-models" / "integration-build.json").is_file():
        raise FileNotFoundError("MSI staging is missing Web Models integration metadata")

    output.parent.mkdir(parents=True, exist_ok=True)
    db = init_database(
        str(output), schema,
        "SENTRA Desktop", _product_code(version), version, MANUFACTURER,
    )
    add_tables(db, sequence)
    add_tables(db, text)
    add_data(db, "Property", [
        ("UpgradeCode", UPGRADE_CODE),
        ("ALLUSERS", "2"),
        ("MSIINSTALLPERUSER", "1"),
        ("ARPNOMODIFY", "1"),
        ("ARPURLINFOABOUT", "https://github.com/vitorGgC569/SENTRA"),
        ("SecureCustomProperties", "SENTRA_OLDPRODUCTS"),
    ])
    # Detect any older SENTRA Desktop sharing the stable UpgradeCode. The
    # standard FindRelatedProducts + RemoveExistingProducts actions in the
    # execute sequence then make this a real major upgrade instead of a
    # side-by-side product registration. VersionMax is exclusive by default.
    add_data(db, "Upgrade", [
        (
            UPGRADE_CODE,
            None,
            version,
            None,
            1,
            None,
            "SENTRA_OLDPRODUCTS",
        ),
    ])

    cab = CAB("sentra.cab")
    target = Directory(db, cab, None, str(source), "TARGETDIR", "SourceDir")
    local = Directory(db, cab, target, ".", "LocalAppDataFolder", ".")
    vendor = Directory(db, cab, local, ".", "SENTRAHome", "SENTRA")
    install = Directory(db, cab, vendor, ".", "INSTALLDIR", "Commander")
    feature = Feature(
        db, "SENTRAFeature", "SENTRA Desktop",
        "Secure local MCP, Edge bridge, tunnel and desktop operations.",
        1, directory=install.logical,
    )
    feature.set_current()
    file_ids = _add_tree(db, cab, feature, install, source)

    desktop_id = file_ids["sentra-desktop.exe"]
    human_id = file_ids["sentra-human.exe"]
    root_component = _component_id(Path("."))
    add_data(db, "Registry", [
        (
            "SENTRA_Autostart",
            1,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            "SENTRA Desktop",
            f'"[#{desktop_id}]" --hidden',
            root_component,
        ),
    ])

    program_menu = Directory(db, cab, target, ".", "ProgramMenuFolder", ".")
    sentra_menu = Directory(db, cab, program_menu, ".", "SENTRAMenu", "SENTRA")
    add_data(db, "Shortcut", [
        (
            "SENTRA_App_Shortcut",
            sentra_menu.logical,
            "SENTRA",
            root_component,
            f"[#{human_id}]",
            None,
            "Open SENTRA",
            None,
            None,
            None,
            1,
            install.logical,
        ),
        (
            "SENTRA_Control_Center_Shortcut",
            sentra_menu.logical,
            "SENTRA Control Center",
            root_component,
            f"[#{desktop_id}]",
            None,
            "Open SENTRA Control Center",
            None,
            None,
            None,
            2,
            install.logical,
        ),
    ])
    add_data(db, "RemoveFile", [
        (
            "SENTRA_Menu_Remove",
            root_component,
            None,
            sentra_menu.logical,
            2,
        ),
    ])

    cab_temp = output.parent / ".msi-cab-temp"
    cab_temp.mkdir(parents=True, exist_ok=True)
    old_temp = os.environ.get("TEMP")
    old_tmp = os.environ.get("TMP")
    os.environ["TEMP"] = str(cab_temp)
    os.environ["TMP"] = str(cab_temp)
    try:
        cab.commit(db)
        db.Commit()
    finally:
        if old_temp is None:
            os.environ.pop("TEMP", None)
        else:
            os.environ["TEMP"] = old_temp
        if old_tmp is None:
            os.environ.pop("TMP", None)
        else:
            os.environ["TMP"] = old_tmp
        shutil.rmtree(cab_temp, ignore_errors=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--version", default=PRODUCT_VERSION)
    args = parser.parse_args()
    path = build_msi(Path(args.source), Path(args.output), args.version)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
