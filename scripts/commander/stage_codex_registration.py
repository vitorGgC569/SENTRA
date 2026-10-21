"""Stage the unmodified official CLI for offline local plugin registration.

Preparation supplies the pinned original archive; packaging never downloads.
Only the plugin-management executable is needed. Model execution, voice and
Windows sandbox helper resources are outside this component's purpose.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from sentra_remote.codex_registration_runtime import (
    ARCHIVE_MEMBER, ARCHIVE_SHA256, FILES, file_sha256, provenance,
    validate_registration_runtime,
)


def stage_registration_runtime(archive: Path, destination: Path) -> Path:
    archive, destination = Path(archive), Path(destination)
    if archive.is_symlink() or not archive.is_file() or file_sha256(archive) != ARCHIVE_SHA256:
        raise ValueError("Official Codex archive checksum mismatch")
    if destination.exists():
        return validate_registration_runtime(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix="codex-registration-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive) as package:
            members = [item for item in package.infolist() if item.filename == ARCHIVE_MEMBER]
            if (len(members) != 1 or not 1 <= members[0].file_size <= 400 * 1024 * 1024
                    or members[0].is_dir()):
                raise ValueError("Official Codex archive executable is missing or ambiguous")
            with package.open(members[0]) as source, (pending / "codex.exe").open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        legal = ROOT / "sentra_remote/provider_notices/codex-registration"
        for name in FILES.keys() - {"codex.exe"}:
            shutil.copy2(legal / name, pending / name)
        (pending / "provenance.json").write_text(json.dumps(provenance(), indent=2) + "\n", encoding="utf-8")
        validate_registration_runtime(pending)
        pending.rename(destination)
    finally:
        # This uniquely created directory is wholly owned by this invocation.
        if pending.exists():
            if pending.is_symlink() or pending.is_junction() or not pending.resolve().is_relative_to(destination.parent.resolve()):
                raise ValueError("Codex registration staging cleanup escaped its owned parent")
            shutil.rmtree(pending)
    return validate_registration_runtime(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    executable = stage_registration_runtime(args.archive, args.destination)
    print(json.dumps({"executable": str(executable), "verified": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
