"""Build a per-user MSI with bounded external CABs and a bound media inventory.

Distribute the MSI, every sibling CAB, and its .media.json together. The
database alone is not a self-contained installer. This module does not sign or
qualify a release; publication retains the separate signing and VM QA gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import msilib
from msilib import CAB, Directory, Feature, FCICreate, add_data, add_stream, add_tables, init_database, schema, sequence, text

from sentra_version import PRODUCT_VERSION
from scripts.commander.msi_media import msi_distribution_files

MANUFACTURER = "SENTRA"
UPGRADE_CODE = "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, "https://sentra.local/windows-desktop")).upper() + "}"

# CPython's FCI wrapper limits each compressed CAB to INT_MAX bytes. Bound the
# uncompressed input instead, leaving ample room for incompressible data and
# CAB headers. Legal/source archives remain ordinary required payload files.
MAX_CABINET_INPUT_BYTES = 1024 ** 3


def _cabinet_partitions(files, limit: int):
    if type(limit) is not int or not 1 <= limit <= MAX_CABINET_INPUT_BYTES:
        raise ValueError("CAB input bound must be between 1 byte and 1 GiB")
    groups, current, total = [], [], 0
    for filename, logical in files:
        size = Path(filename).stat().st_size
        if size > limit:
            raise ValueError("individual MSI file exceeds bounded CAB input: " + filename)
        if current and total + size > limit:
            groups.append(current)
            current, total = [], 0
        current.append((filename, logical))
        total += size
    if current:
        groups.append(current)
    return groups


class _PartitionedCAB(CAB):
    """Keep global File sequencing for independent embedded or external media."""

    def __init__(self, name: str, temporary_root: Path, *, input_limit: int | None = None,
                 external_root: Path | None = None):
        super().__init__(name)
        self.temporary_root = Path(temporary_root)
        self.input_limit = MAX_CABINET_INPUT_BYTES if input_limit is None else input_limit
        self.external_root = Path(external_root) if external_root is not None else None
        self.media: list[dict] = []

    def gen_id(self, file):
        # Cabinet lookup on Windows must not collide only by letter case.
        # msilib.CAB's default set is case-sensitive (LICENSE vs license).
        stem = msilib.make_id(file)
        number = 0
        while True:
            suffix = "" if number == 0 else f".{number}"
            logical = stem[:72 - len(suffix)] + suffix
            folded = logical.casefold()
            if folded not in self.filenames:
                self.filenames.add(folded)
                return logical
            number += 1

    @staticmethod
    def _sources_with_valid_cabinet_dates(files, folder: Path):
        """Normalize only invalid DOS dates on private copies, never sources."""
        normalized = []
        for index, (filename, logical) in enumerate(files):
            # CAB DOS timestamps can only represent 1980 through 2107. Some
            # reproducible vendor license files intentionally carry epoch 0;
            # FCI then writes date=0, which Installer rejects with error2357.
            year = time.localtime(Path(filename).stat().st_mtime).tm_year
            if not 1980 <= year <= 2107:
                folder.mkdir(parents=True, exist_ok=True)
                copied = folder / str(index)
                shutil.copyfile(filename, copied)
                os.utime(copied, (946684800, 946684800))  # 2000-01-01 UTC
                filename = str(copied)
            normalized.append((filename, logical))
        return normalized

    def commit(self, db):
        partitions = _cabinet_partitions(self.files, self.input_limit)
        if not partitions or self.index != len(self.files):
            raise ValueError("MSI CAB file sequence is empty or inconsistent")
        self.temporary_root.mkdir(parents=True, exist_ok=True)
        last_sequence = 0
        media = []
        with tempfile.TemporaryDirectory(prefix="cab-", dir=self.temporary_root) as temporary:
            for disk, files in enumerate(partitions, 1):
                stream_name = f"{Path(self.name).stem}-{disk:04d}.cab"
                cabinet = Path(temporary) / stream_name
                normalized = self._sources_with_valid_cabinet_dates(
                    files, Path(temporary) / f"normalized-{disk}")
                FCICreate(str(cabinet), normalized)
                with cabinet.open("rb") as stream:
                    header = stream.read(36)
                size = cabinet.stat().st_size
                if (len(header) != 36 or header[:4] != b"MSCF" or size >= 2147483647
                        or struct.unpack_from("<I", header, 8)[0] != size
                        or struct.unpack_from("<H", header, 28)[0] != len(files)):
                    raise ValueError("MSI cabinet size/header is invalid")
                last_sequence += len(files)
                with cabinet.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                media.append({"name": stream_name, "bytes": size, "sha256": digest,
                              "last_sequence": last_sequence})
            # Finish every CAB before referencing or publishing any of them.
            # External CABs keep the Installer database small; embedding the
            # complete 2.9 GB payload failed Windows Installer's cache step.
            for disk, item in enumerate(media, 1):
                cabinet = Path(temporary) / item["name"]
                external = self.external_root is not None
                add_data(db, "Media", [(disk, item["last_sequence"], None,
                                       ("" if external else "#") + item["name"], None, None)])
                if not external:
                    add_stream(db, item["name"], str(cabinet))
            db.Commit()
            if self.external_root is not None:
                self.external_root.mkdir(parents=True, exist_ok=True)
                for item in media:
                    os.replace(Path(temporary) / item["name"], self.external_root / item["name"])
            self.media = media


def _product_code(version: str) -> str:
    return "{" + str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"https://sentra.local/windows-desktop/{version}"
    )).upper() + "}"


MSI_IDENTIFIER_MAX = 72


def _stable_msi_id(prefix: str, relative: Path) -> str:
    normalized = "root" if relative == Path(".") else relative.as_posix().casefold()
    leaf = "root" if relative == Path(".") else (relative.name or "root")
    safe_leaf = msilib.make_id(leaf)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    suffix = "_" + digest
    label_budget = MSI_IDENTIFIER_MAX - len(prefix) - len(suffix)
    if label_budget < 1:
        raise ValueError("MSI identifier prefix is too long")
    return msilib.make_id(prefix + safe_leaf[:label_budget] + suffix)


def _component_id(relative: Path) -> str:
    return _stable_msi_id("cmp_", relative)


def _directory_id(relative: Path) -> str:
    return _stable_msi_id("dir_", relative)


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
        "sentra-update-helper.exe", "sentra-oma.exe", "sentra-cli.exe", "sentra-canvas.exe", "sentra.exe",
        "tunnel-client.exe",
    }
    missing = sorted(name for name in required if not (source / name).is_file())
    if missing:
        raise FileNotFoundError("MSI staging is missing: " + ", ".join(missing))
    if not (source / "docs" / "onboarding_media" / "SENTRA_SETUP_GUIDE.html").is_file():
        raise FileNotFoundError("MSI staging missing visual setup guide")
    if not (source / "docs" / "SENTRA_PRIMEIRA_INSTALACAO_CANVAS_PLUGIN_2026-10-09.md").is_file():
        raise FileNotFoundError("MSI staging missing first-install Canvas/ChatGPT app guide")
    if not (source / "docs" / "onboarding_media" / "mcp-create-tunnel.mp4").is_file():
        raise FileNotFoundError("MSI staging missing first-run tutorial video")
    if not (source / "docs" / "onboarding_media" / "mcp-connect-connector.mp4").is_file():
        raise FileNotFoundError("MSI staging missing connector tutorial video")
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
    # msilib caches directory identifiers process-wide. A second build must
    # still have the standard TARGETDIR/INSTALLDIR names, not suffixed copies.
    msilib._directories.clear()
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

    # Distribute this database together with its versioned CAB files. Media
    # names omit '#' so Windows Installer resolves them beside the MSI.
    cab = _PartitionedCAB(output.stem + ".cab", output.parent / ".msi-cab-temp",
                          external_root=output.parent)
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
    canvas_id = file_ids["sentra-canvas.exe"]
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

    add_data(db, "Environment", [
        (
            "SENTRA_User_Path",
            "=-Path",
            "[~];[INSTALLDIR]",
            root_component,
        ),
    ])

    add_data(db, "Registry", [
        (
            "SENTRA_Protocol_Name",
            1,
            r"Software\Classes\sentra",
            None,
            "URL:SENTRA Protocol",
            root_component,
        ),
        (
            "SENTRA_Protocol_Flag",
            1,
            r"Software\Classes\sentra",
            "URL Protocol",
            "",
            root_component,
        ),
        (
            "SENTRA_Protocol_Command",
            1,
            r"Software\Classes\sentra\shell\open\command",
            None,
            f'"[#{desktop_id}]" --open-url "%1"',
            root_component,
        ),
    ])

    program_menu = Directory(db, cab, target, ".", "ProgramMenuFolder", ".")
    sentra_menu = Directory(db, cab, program_menu, ".", "SENTRAMenu", "SENTRA")
    desktop_folder = Directory(db, cab, target, ".", "DesktopFolder", ".")
    add_data(db, "Shortcut", [
        (
            "SENTRA_App_Shortcut",
            sentra_menu.logical,
            "SENTRA",
            root_component,
            f"[#{canvas_id}]",
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
        (
            "SENTRA_Desktop_Shortcut",
            desktop_folder.logical,
            "SENTRA",
            root_component,
            f"[#{canvas_id}]",
            None,
            "Open SENTRA Canvas",
            None,
            None,
            None,
            3,
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
    # MsiCloseHandle finalizes the storage header. Hashing while a Directory
    # still owns the open database records a digest that changes on return.
    del target, local, vendor, install, program_menu, sentra_menu, desktop_folder, db
    # A bound inventory makes copying only the MSI detectable by packaging and
    # publication consumers. Hashes are integrity evidence, not signatures.
    with output.open("rb") as stream:
        database_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {"schema": 1, "msi": output.name, "sha256": database_digest,
                "media": cab.media}
    output.with_suffix(".media.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
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
