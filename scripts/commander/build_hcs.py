"""Build the real HCS helper from the approved hcsshim checkout, in isolation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dependency_notices(go: Path, helper: Path, env: dict, artifact: Path) -> None:
    raw = subprocess.check_output([str(go), "list", "-mod=readonly", "-deps", "-json", "."], cwd=helper, env=env, text=True, encoding="utf-8", timeout=120)
    decoder, modules = json.JSONDecoder(), {}
    while raw.strip():
        package, end = decoder.raw_decode(raw.lstrip())
        raw = raw.lstrip()[end:]
        module = package.get("Module") or {}
        if module and not module.get("Main"):
            modules[module["Path"]] = module
    records = []
    for name, module in sorted(modules.items()):
        source = Path(module["Dir"])
        target = artifact / "licenses" / hashlib.sha256(name.encode()).hexdigest()[:16]
        legal = [path for path in source.iterdir() if path.is_file()
                 and path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE"))]
        if not legal:
            raise RuntimeError("dependency license missing: " + name)
        target.mkdir(parents=True)
        for path in legal:
            if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("unsafe dependency legal file: " + name)
            shutil.copy2(path, target / path.name)
        records.append({"module": name, "version": module.get("Version"), "sum": module.get("Sum"),
                        "files": [(target / path.name).relative_to(artifact).as_posix() for path in legal]})
    (artifact / "dependency-notices.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    goroot = Path(subprocess.check_output([str(go), "env", "GOROOT"], env=env, text=True).strip())
    shutil.copy2(goroot / "LICENSE", artifact / "LICENSE-Go")


def build_hcs(destination: Path, go: Path, *, root: Path = ROOT) -> dict:
    root, destination, go = root.resolve(), destination.absolute(), go.resolve(strict=True)
    builder_sha256 = _sha(Path(__file__))
    if os.name != "nt":
        raise RuntimeError("HCS release build requires Windows")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("HCS candidate already exists")
    destination = destination.resolve()
    upstream = root / "third_party/hcsshim"
    approved = json.loads((root / "sentra_quality/approved_sources.json").read_text())
    pin = next(item for item in approved["repos"] if item["name"] == "hcsshim")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(upstream), *args], text=True).strip()

    if git("rev-parse", "HEAD") != pin["revision"] or git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("HCS source is dirty or differs from the approved revision")
    helper = root / "sentra_executors/hcs_bridge"
    sources = {path.name: _sha(path) for path in helper.iterdir() if path.suffix in {".go", ".mod", ".sum"}}
    module = (helper / "go.mod").read_text()
    required = next(line.split()[1] for line in module.splitlines() if line.startswith("go "))
    env = dict(os.environ, GOOS="windows", GOARCH="amd64", CGO_ENABLED="0", GOTOOLCHAIN="local",
               GOSUMDB="sum.golang.org", GOPRIVATE="", GONOSUMDB="", GONOPROXY="",
               GOPROXY="https://proxy.golang.org", GOFLAGS="", GOWORK="off")
    version = subprocess.check_output([str(go), "env", "GOVERSION"], env=env, text=True).strip()
    if version != "go" + required:
        raise RuntimeError("HCS requires exact Go " + required + "; found " + version)
    destination.mkdir(parents=True, exist_ok=False)
    work = destination / "build-source"
    staged_upstream = work / "third_party/hcsshim"
    staged_upstream.mkdir(parents=True)
    archive = destination / "hcsshim-source.tar"
    subprocess.run(["git", "-C", str(upstream), "archive", "--format=tar", "--output=" + str(archive), pin["revision"]], check=True)
    with tarfile.open(archive) as bundle:
        bundle.extractall(staged_upstream, filter="data")
    staged_helper = work / "sentra_executors/hcs_bridge"
    staged_helper.mkdir(parents=True)
    for name, digest in sources.items():
        data = (helper / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError("HCS helper source changed before copying")
        (staged_helper / name).write_bytes(data)
    artifact = destination / "artifact"
    artifact.mkdir()
    executable = artifact / "sentra-hcs-bridge.exe"
    with (destination / "build.log").open("w", encoding="utf-8") as log:
        for args in (["mod", "tidy"], ["mod", "verify"],
                     ["build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-ldflags=-buildid=", "-o", str(executable), "."]):
            log.write("go " + " ".join(args) + "\n")
            log.flush()
            subprocess.run([str(go), *args], cwd=staged_helper, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    if any(_sha(helper / name) != digest for name, digest in sources.items()):
        raise RuntimeError("HCS helper source changed during build")
    if git("rev-parse", "HEAD") != pin["revision"] or git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("HCS upstream source changed during build")
    if executable.read_bytes()[:2] != b"MZ":
        raise RuntimeError("HCS output is not a Windows executable")
    # This exercises the built protocol without invoking a native HCS action.
    smoke = subprocess.run([str(executable)], input="invalid-json\n", text=True, capture_output=True, timeout=10, check=True)
    if json.loads(smoke.stdout) != {"event": "result", "ok": False, "code": "hcs_request_invalid"}:
        raise RuntimeError("HCS executable protocol smoke failed")
    shutil.copy2(staged_upstream / "LICENSE", artifact / "LICENSE-hcsshim")
    shutil.copy2(root / "LICENSE", artifact / "LICENSE-SENTRA")
    _dependency_notices(go, staged_helper, env, artifact)
    for name in ("go.mod", "go.sum"):
        shutil.copy2(staged_helper / name, artifact / name)
    dependencies = subprocess.check_output([str(go), "version", "-m", str(executable)], env=env, text=True)
    (artifact / "build-info.txt").write_text(dependencies, encoding="utf-8")
    proof = {"schema_version": 1, "component": "hcs", "compiled": True, "validated": False,
             "executable": executable.name, "platform": "windows-amd64", "license": "MIT",
             "upstream": {**pin, "license": "MIT", "source_archive_sha256": _sha(archive)},
             "helper_sources": sources, "builder_sha256": builder_sha256,
             "toolchain": {"version": version, "sha256": _sha(go)},
             "protocol_smoke": "malformed request rejected; no HCS action invoked",
             "files": [{"path": path.relative_to(artifact).as_posix(), "sha256": _sha(path)}
                       for path in sorted(artifact.rglob("*")) if path.is_file()]}
    if _sha(Path(__file__)) != builder_sha256:
        raise RuntimeError("HCS builder changed during compilation")
    (artifact / "manifest.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--go", required=True, type=Path)
    args = parser.parse_args()
    proof = build_hcs(args.destination, args.go)
    print(json.dumps({"artifact": str(args.destination.resolve() / "artifact"), "compiled": proof["compiled"], "validated": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
