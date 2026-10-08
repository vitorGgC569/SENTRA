"""Reproduce the pinned MIT-licensed Canvas terminal assets from npm tarballs."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = (
    ("@xterm/xterm", "6.0.0",
     "TQwDdQGtwwDt+2cgKDLn0IRaSxYu1tSUjgKarSDkUM0ZNiSRXFpjxEsvc/Zgc5kq5omJ+V0a8/kIM2WD3sMOYg==",
     {"lib/xterm.js": "xterm.js", "css/xterm.css": "xterm.css", "LICENSE": "xterm-LICENSE"}),
    ("@xterm/addon-fit", "0.11.0",
     "jYcgT6xtVYhnhgxh3QgYDnnNMYTcf8ElbxxFzX0IZo+vabQqSPAjC3c1wJrKB5E19VwQei89QCiZZP86DCPF7g==",
     {"lib/addon-fit.js": "addon-fit.js", "LICENSE": "addon-fit-LICENSE"}),
)


def vendor(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, version, expected, files in PACKAGES:
        basename = name.split("/")[-1]
        url = f"https://registry.npmjs.org/{name}/-/{basename}-{version}.tgz"
        with urllib.request.urlopen(url, timeout=30) as response:
            archive = response.read(8 * 1024 * 1024 + 1)
        if len(archive) > 8 * 1024 * 1024:
            raise ValueError("terminal dependency archive exceeds the allowed size")
        if base64.b64encode(hashlib.sha512(archive).digest()).decode() != expected:
            raise ValueError(f"integrity mismatch for {name}@{version}")
        outputs = {}
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            # Read exact regular files. No archive paths are extracted to disk.
            for source, target in files.items():
                member = bundle.getmember("package/" + source)
                if not member.isfile() or member.size > 4 * 1024 * 1024:
                    raise ValueError("invalid terminal dependency member")
                with bundle.extractfile(member) as stream:
                    data = stream.read()
                (destination / target).write_bytes(data)
                outputs[target] = hashlib.sha256(data).hexdigest()
        manifest.append({"package": name, "version": version, "license": "MIT",
                         "source": url, "integrity": "sha512-" + expected, "files": outputs})
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def validate(destination: Path) -> None:
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, list) or len(manifest) != len(PACKAGES):
        raise ValueError("invalid terminal dependency manifest")
    for record, (name, version, integrity, files) in zip(manifest, PACKAGES):
        if (record.get("package") != name or record.get("version") != version
                or record.get("integrity") != "sha512-" + integrity
                or set(record.get("files", {})) != set(files.values())):
            raise ValueError("terminal dependencies do not match pinned versions")
        for filename, expected in record["files"].items():
            if hashlib.sha256((destination / filename).read_bytes()).hexdigest() != expected:
                raise ValueError("terminal dependency integrity mismatch: " + filename)


if __name__ == "__main__":
    vendor(ROOT / "sentra_canvas" / "static" / "vendor")
