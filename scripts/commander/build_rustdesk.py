"""Build the SENTRA-instrumented RustDesk from a separately prepared checkout.

No stock executable is accepted as a substitute. Codegen, Rust library and
Flutter are separate verified phases, each with an output and source proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PATCHED = ("src/lib.rs", "src/core_main.rs", "src/client.rs", "src/client/io_loop.rs",
           "flutter/windows/runner/main.cpp", "libs/hbb_common/src/config.rs", "src/sentra_peer_gate.rs")
GENERATED = ("src/bridge_generated.rs", "src/bridge_generated.io.rs", "flutter/lib/generated_bridge.dart",
             "flutter/lib/generated_bridge.freezed.dart", "flutter/macos/Runner/bridge_generated.h")
SUBMODULE_INPUTS = {"libs/hbb_common/src/config.rs": ("libs/hbb_common", "src/config.rs")}
EXTRA_INPUTS = ("flutter/pubspec.lock",)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_tool_inputs() -> dict:
    from sentra_executors import remote_rustdesk_build
    from scripts.commander import build_windows
    emitter = Path(remote_rustdesk_build.__file__).resolve()
    return {"build_rustdesk.py": sha(Path(__file__).resolve()),
            "build_windows.py": sha(Path(build_windows.__file__).resolve()),
            "remote_rustdesk_build.py": sha(emitter),
            "remote_rustdesk_gate.rs": sha(emitter.with_name("remote_rustdesk_gate.rs")),
            "rustdesk_profile_native.rs": sha(ROOT / "tests/qa/rustdesk_profile_native.rs")}


def _git(source, *args, binary=False):
    return subprocess.check_output(["git", "-C", str(source), *args], text=not binary,
                                   **({} if binary else {"encoding": "utf-8"}))


def validate_native_sources(source: Path) -> dict:
    from sentra_executors.remote_rustdesk_build import native_peer_gate_patch
    pins = json.loads((ROOT / "sentra_quality/approved_sources.json").read_text())
    pin = next(item for item in pins["repos"] if item["name"] == "rustdesk")
    if _git(source, "rev-parse", "HEAD").strip() != pin["revision"]:
        raise RuntimeError("RustDesk source differs from the approved revision")
    submodules = _git(source, "submodule", "status", "--recursive")
    if not submodules.strip() or any(line[0] != " " for line in submodules.splitlines()):
        raise RuntimeError("RustDesk submodules are missing, conflicted or off their pinned commits")
    # Reconstruct the exact instrumented files from the immutable Git base.
    # An extra edit outside a diff hunk must not evade a reverse-apply check.
    with tempfile.TemporaryDirectory(prefix="sentra-rustdesk-patch-") as temporary:
        expected = Path(temporary)
        for name in PATCHED[:-1]:
            path = expected / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name in SUBMODULE_INPUTS:
                module, relative = SUBMODULE_INPUTS[name]
                module_root = source / module
                tree = _git(source, "ls-tree", "HEAD", module).split()
                if len(tree) < 3 or tree[:2] != ["160000", "commit"]:
                    raise RuntimeError("RustDesk submodule is not pinned in Git: " + module)
                if _git(module_root, "rev-parse", "HEAD").strip() != tree[2]:
                    raise RuntimeError("RustDesk submodule HEAD differs from its approved Gitlink: " + module)
                changes = _git(module_root, "status", "--porcelain", "--untracked-files=normal").splitlines()
                if any(line[3:] != relative for line in changes):
                    raise RuntimeError("unreviewed RustDesk submodule changes: " + module)
                path.write_bytes(_git(module_root, "show", "HEAD:" + relative, binary=True))
            else:
                path.write_bytes(_git(source, "show", "HEAD:" + name, binary=True))
        plan = native_peer_gate_patch(str(expected))
        patch = expected / "native.patch"
        patch.write_text(plan["patch"], encoding="utf-8", newline="\n")
        subprocess.run(["git", "-C", str(expected), "apply", str(patch)], check=True, capture_output=True)
        for name in PATCHED:
            path = source / name
            if path.is_symlink() or path.read_bytes().replace(b"\r\n", b"\n") != (expected / name).read_bytes().replace(b"\r\n", b"\n"):
                raise RuntimeError("RustDesk instrumentation differs from reviewed sources: " + name)
    return {"source_revision": pin["revision"], "upstream": pin["upstream"],
            "submodules": submodules.strip().splitlines(),
            "patch_sha256": hashlib.sha256(plan["patch"].encode()).hexdigest(),
            "native_sources": {name: sha(source / name) for name in PATCHED}}


def source_inputs(source: Path) -> dict:
    names = _git(source, "ls-files", "--recurse-submodules", "-z").split("\0")
    names.extend((*PATCHED, *GENERATED, *EXTRA_INPUTS))
    # build.rs generates this timestamp/version output; it is recorded as an
    # output rather than falsely represented as an immutable build input.
    ignored = {"src/version.rs"}
    result = {}
    if any(not (source / name).is_file() for name in EXTRA_INPUTS):
        raise RuntimeError("RustDesk Flutter dependency lock is missing")
    for name in sorted(set(names) - ignored - {""}):
        path = source / name
        if not path.is_file():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("linked or escaped RustDesk source: " + name)
        result[name] = sha(path)
    return result


def run_logged(command, *, cwd, env, log, timeout=3600):
    from scripts.commander.build_windows import _terminate_process_tree
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen([str(item) for item in command], cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        print(json.dumps({"step": log.stem, "pid": process.pid, "log": str(log)}), flush=True)
        try:
            code = process.wait(timeout=timeout)
        except BaseException:
            _terminate_process_tree(process)
            raise
    if code:
        raise RuntimeError(f"{log.stem} failed ({code}); inspect {log}")


def flutter_build_environment(project: Path, scratch: Path, env: dict) -> dict:
    """Select a short MSBuild directory using process-local Flutter config.

    Flutter 3.24.5 requires a relative build-dir, and reads configuration from
    APPDATA on Windows. Neither the user's config nor OS long-path policy is
    changed. The caller owns the fresh scratch directory and retains it for QA.
    """
    project, scratch = project.resolve(strict=True), scratch.resolve(strict=True)
    if scratch == project or scratch.is_relative_to(project) or project.is_relative_to(scratch):
        raise ValueError("Flutter scratch directory must be separate from its project")
    config = scratch / "config"
    config.mkdir()
    (config / ".flutter_settings").write_text(json.dumps({
        "build-dir": os.path.relpath(scratch / "b", project),
        "enable-windows-desktop": True}), encoding="utf-8")
    return dict(env, APPDATA=str(config))


def publish_flutter_bundle(source: Path, staged: Path) -> list[Path]:
    """Copy only this build's verified files, retaining any prior bundle."""
    source, staged = source.resolve(strict=True), staged.resolve(strict=True)
    names = [path.relative_to(staged) for path in sorted(staged.rglob("*")) if path.is_file()]
    if any((staged / name).is_symlink() or not (staged / name).resolve().is_relative_to(staged) for name in names):
        raise RuntimeError("linked/escaped Flutter build output")
    for name in ("rustdesk.exe", "librustdesk.dll", "flutter_windows.dll", "data/app.so", "data/icudtl.dat"):
        if Path(name) not in names or not (staged / name).stat().st_size:
            raise RuntimeError("Flutter bundle output missing/empty: " + name)
    if sha(staged / "librustdesk.dll") != sha(source / "target/release/librustdesk.dll"):
        raise RuntimeError("Flutter bundle does not contain the proven native library")
    bundle = source / "flutter/build/windows/x64/runner/Release"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    if not bundle.parent.resolve().is_relative_to(source):
        raise ValueError("Flutter bundle publication escaped the owned source")
    if bundle.exists():
        if bundle.is_symlink() or bundle.is_junction() or not bundle.resolve().is_relative_to(source):
            raise ValueError("Flutter bundle destination is linked/escaped")
        backup = bundle.with_name("Release-before-" + str(time.time_ns()))
        if not backup.resolve().is_relative_to(source):
            raise ValueError("Flutter previous-bundle archive escaped the owned source")
        bundle.rename(backup)
    bundle.mkdir()
    produced = []
    for name in names:
        target = bundle / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged / name, target)
        if sha(target) != sha(staged / name):
            raise RuntimeError("Flutter output changed during publication: " + str(name))
        produced.append(target)
    return produced


def run_native_profile_probe(source: Path, output: Path, env: dict, vcpkg: Path) -> tuple[list[Path], dict]:
    """Exercise the exact release dependency selected by the real Cargo graph.

    Cargo's unit-test harness would rebuild the graph with panic=unwind. This
    probe instead links the same panic=abort rlib used by the release DLL.
    """
    cargo_log = output / "profile-cargo.log"
    run_logged(["cargo", "build", "--locked", "--features", "flutter,hwcodec", "--lib", "--release",
                "--message-format=json-render-diagnostics"], cwd=source, env=env, log=cargo_log)
    candidates = set()
    for line in cargo_log.read_text(encoding="utf-8").splitlines():
        try:
            message = json.loads(line)
        except (ValueError, TypeError):
            continue
        if (message.get("reason") == "compiler-artifact" and message.get("target", {}).get("name") == "hbb_common"
                and "lib" in message.get("target", {}).get("kind", [])
                and message.get("profile", {}).get("opt_level") == "3"
                and message.get("profile", {}).get("test") is False
                and "webrtc" in message.get("features", [])):
            # The approved root's normal dependency enables webrtc; its
            # build.rs separately uses a non-optimized host-only variant.
            candidates.update(Path(name).resolve(strict=True) for name in message.get("filenames", []) if name.endswith(".rlib"))
    if len(candidates) != 1:
        raise RuntimeError("actual release hbb_common library is missing or ambiguous")
    library = candidates.pop()
    if not library.is_relative_to(source / "target/release/deps"):
        raise RuntimeError("release hbb_common library escaped the owned build")
    library_before = sha(library)
    probe_source = ROOT / "tests/qa/rustdesk_profile_native.rs"
    executable = source / "target/release/sentra-profile-probe.exe"
    native_dirs = {path.parent for path in (source / "target/release/build").rglob("*.lib")}
    native_dirs.add(vcpkg / "installed/x64-windows-static/lib")
    cargo_home = Path(env.get("CARGO_HOME", str(Path.home() / ".cargo")))
    native_dirs.update(path for path in (cargo_home / "registry/src").glob("*/windows_x86_64_msvc-*/lib"))
    native_dirs.update(path for path in (cargo_home / "vendor").glob("windows_x86_64_msvc-*/lib"))
    command = ["rustc", "--edition=2021", "-C", "panic=abort", "--crate-name", "sentra_profile_probe",
               str(probe_source), "--extern", "hbb_common=" + str(library),
               "-L", "dependency=" + str(source / "target/release/deps"), "-o", str(executable)]
    for directory in sorted(native_dirs):
        command.extend(("-L", "native=" + str(directory)))
    run_logged(command, cwd=source, env=env, log=output / "profile-compile.log")
    profiles = output / ("profile-runs-" + str(time.time_ns()))
    profiles.mkdir()
    runs = []
    # This changes only this disposable builder process and its test children,
    # suppressing Windows' crash dialog for the intentional panic=abort case.
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetErrorMode.argtypes, kernel.SetErrorMode.restype = [ctypes.c_uint], ctypes.c_uint
    previous_error_mode = kernel.SetErrorMode(0x8003)
    try:
        for label, scope, negative in (("a", "a" * 64, False), ("b", "b" * 64, False), ("escape", "e" * 64, True)):
            profile = profiles / label; profile.mkdir()
            command = [str(executable), str(profile), scope] + (["escape"] if negative else [])
            result = subprocess.run(command, cwd=source, env=env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            record = {"scope": scope, "profile": str(profile), "returncode": result.returncode,
                      "stdout": result.stdout, "stderr": result.stderr, "negative": negative}
            runs.append(record)
            (profiles / (label + ".json")).write_text(json.dumps(record, indent=2), encoding="utf-8")
            if negative:
                if (result.returncode in (0, 99)
                        or "SENTRA config path must stay relative to its owned profile" not in result.stderr
                        or (profiles / "escaped-profile.txt").exists()):
                    raise RuntimeError("native profile traversal was not refused by the actual guard")
            elif result.returncode or result.stdout.strip() != "profile-config-log-ipc-isolated":
                raise RuntimeError("actual native profile probe failed: " + label)
    finally:
        kernel.SetErrorMode(previous_error_mode)
    if sha(library) != library_before:
        raise RuntimeError("release hbb_common library changed during its profile probe")
    return [executable], {"library": library.relative_to(source).as_posix(), "library_sha256": library_before,
                           "probe_source_sha256": sha(probe_source), "runs": runs}


def _build_phase_locked(args) -> dict:
    if os.name != "nt":
        raise RuntimeError("Windows RustDesk build host required")
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("build proofs must be outside the RustDesk checkout")
    output.mkdir(parents=True, exist_ok=True)
    tooling_before = build_tool_inputs()
    native = validate_native_sources(source)
    toolchain = args.toolchains.resolve(strict=True)
    flutter = toolchain / "flutter3.24.5/flutter"
    codegen = toolchain / "rustdesk-codegen/bin"
    vcpkg = toolchain / "vcpkg-9e593bb"
    libclang = toolchain / "libclang15.0.6.1/libclang-15.0.6.1.data/platlib/clang/native"
    env = dict(os.environ, RUSTUP_TOOLCHAIN="1.75.0", CARGO_BUILD_JOBS="2", CMAKE_BUILD_PARALLEL_LEVEL="2",
        CARGO_NET_GIT_FETCH_WITH_CLI="true", VCPKG_ROOT=str(vcpkg), VCPKG_TARGET_TRIPLET="x64-windows-static",
        VCPKG_INSTALLED_ROOT=str(vcpkg / "installed"), LIBCLANG_PATH=str(libclang),
        FLUTTER_SKIP_UPDATE_CHECK="true", CI="true", FLUTTER_SUPPRESS_ANALYTICS="true", DART_SUPPRESS_ANALYTICS="true")
    env["PATH"] = os.pathsep.join((str(codegen), str(flutter / "bin"), env["PATH"]))
    rust = subprocess.check_output(["rustc", "--version"], env=env, text=True).strip()
    if not rust.startswith("rustc 1.75.0 "):
        raise RuntimeError("RustDesk requires the selected Rust 1.75.0 toolchain")
    flutter_info = json.loads(subprocess.check_output([str(flutter / "bin/flutter.bat"), "--version", "--machine"], env=env, text=True))
    if flutter_info["frameworkRevision"] != "dec2ee5c1f98f8e84a7d5380c05eb8a3d0a81668":
        raise RuntimeError("Flutter differs from the pinned 3.24.5 archive")
    if _git(vcpkg, "rev-parse", "HEAD").strip() != "9e593bb18ea69cc5095e012465dcd675a822ed0d":
        raise RuntimeError("vcpkg differs from the pinned RustDesk baseline")
    before = source_inputs(source)
    if args.phase == "codegen":
        # The pinned generator accepts only info/debug and panics on inherited
        # RUST_LOG=warn. This changes the build child, never the user's settings.
        env["RUST_LOG"] = "info"
        command = [codegen / "flutter_rust_bridge_codegen.exe", "--rust-input", "./src/flutter_ffi.rs",
            "--dart-output", "./flutter/lib/generated_bridge.dart", "--c-output", "./flutter/macos/Runner/bridge_generated.h",
            "--llvm-path", str(libclang / "libclang.dll"), "--skip-add-mod-to-lib"]
        run_logged(command, cwd=source, env=env, log=output / "codegen.log")
        produced = [source / name for name in GENERATED]
        after = source_inputs(source)
        allowed = set(GENERATED)
        if {key: value for key, value in before.items() if key not in allowed} != {key: value for key, value in after.items() if key not in allowed}:
            raise RuntimeError("RustDesk sources changed during bridge generation")
    else:
        if any(not (source / name).is_file() for name in GENERATED):
            raise RuntimeError("generated bridge is missing; run codegen first")
        previous = json.loads((output / "codegen-proof.json").read_text())
        if any(sha(source / name) != previous["outputs"].get(name) for name in GENERATED):
            raise RuntimeError("generated bridge no longer matches its build proof")
        if args.phase == "native":
            run_logged(["cargo", "build", "--locked", "--features", "flutter,hwcodec", "--lib", "--release"],
                       cwd=source, env=env, log=output / "native.log")
            # `--lib` for the root package does not produce this separate
            # workspace cdylib, although the upstream Windows bundle needs it.
            run_logged(["cargo", "build", "--locked", "--package", "dylib_virtual_display", "--lib", "--release"],
                       cwd=source, env=env, log=output / "native-virtual-display.log")
            produced = [source / "target/release/librustdesk.dll", source / "target/release/deps/dylib_virtual_display.dll",
                        source / "src/version.rs"]
        else:
            proof = json.loads((output / "native-proof.json").read_text())
            if proof["inputs"] != before:
                raise RuntimeError("RustDesk native library proof is stale")
            for name, digest in proof["outputs"].items():
                if sha(source / name) != digest:
                    raise RuntimeError("RustDesk native library differs from its proof")
            if args.phase == "profile-test":
                produced, profile_results = run_native_profile_probe(source, output, env, vcpkg)
                if any(sha(source / name) != digest for name, digest in proof["outputs"].items()):
                    raise RuntimeError("native release outputs changed during the profile probe; rebuild their proof")
            else:
                from scripts.commander.flutter_plugin_links import prepare_flutter_plugin_links
                pub_cache = Path(env["PUB_CACHE"]) if env.get("PUB_CACHE") else Path(env["LOCALAPPDATA"]) / "Pub/Cache"
                prepare_flutter_plugin_links(source / "flutter", pub_cache)
                scratch = Path(tempfile.mkdtemp(prefix="srd-"))
                flutter_env = flutter_build_environment(source / "flutter", scratch, env)
                print(json.dumps({"flutter_scratch": str(scratch), "user_flutter_config_changed": False}), flush=True)
                run_logged([flutter / "bin/flutter.bat", "build", "windows", "--release", "--no-pub"],
                           cwd=source / "flutter", env=flutter_env, log=output / "flutter.log")
                bundle = scratch / "b/windows/x64/runner/Release"
                shutil.copy2(source / "target/release/deps/dylib_virtual_display.dll", bundle)
                produced = publish_flutter_bundle(source, bundle)
        after = source_inputs(source)
        if after != before:
            raise RuntimeError("RustDesk sources changed during native/Flutter compilation")
    for path in produced:
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("RustDesk phase output missing/empty/linked: " + str(path))
    if build_tool_inputs() != tooling_before:
        raise RuntimeError("RustDesk builder/emitter changed during compilation; proof was not published")
    result = {"schema_version": 1, "phase": args.phase, **native, "inputs": after,
              "tooling_inputs": tooling_before,
              "input_snapshot_sha256": {"before": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
                                        "after": hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest()},
              "outputs": {path.relative_to(source).as_posix(): sha(path) for path in produced},
              "toolchain": {"rust": rust, "flutter": flutter_info}, "finished_at_epoch": time.time(),
              "runtime_verified": False, "source": str(source)}
    if args.phase == "profile-test":
        result["profile_results"] = profile_results
        result["verification"] = {"native_profile_isolation": True, "peer_connectivity": False,
                                  "desktop_control": False, "installed": False}
    (output / (args.phase + "-proof.json")).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def build_phase(args) -> dict:
    from scripts.commander.build_windows import _BuildLock
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("build proofs must be outside the RustDesk checkout")
    # Same OS-backed lock as other payload builds. A second invocation cannot
    # overwrite logs, codegen outputs or a proof while this source is compiling.
    with _BuildLock(source.parent / (source.name + ".sentra-build.lock"), description="RustDesk source build"), \
            _BuildLock(output / "rustdesk-build.lock", description="RustDesk output build"):
        return _build_phase_locked(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--toolchains", required=True, type=Path)
    parser.add_argument("--phase", choices=("codegen", "native", "profile-test", "flutter"), required=True)
    args = parser.parse_args()
    result = build_phase(args)
    print(json.dumps({"phase": args.phase, "outputs": len(result["outputs"]), "runtime_verified": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
