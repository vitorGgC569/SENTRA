"""ACP distribution descriptors and explicit, non-executing installation plans.

Derived from the pinned acp-registry agent.schema.json and registry_utils.py.
Registry archive hashes are integrity hints, not independent publisher trust.
No subprocesses, downloads, PATH lookup, shell interpolation or env inheritance.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping
from urllib.parse import urlsplit

TARGETS = frozenset(f"{system}-{arch}" for system in ("windows", "linux", "darwin")
                    for arch in ("aarch64", "x86_64"))
RESERVED_NAMES = frozenset({
    "CI", "COMSPEC", "HOME", "PATH", "PATHEXT", "PYTHONHOME", "PYTHONPATH", "SYSTEMROOT",
    "TEMP", "TMP", "TMPDIR", "WINDIR", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES",
    "REQUESTS_CA_BUNDLE", "SSL_CERT_DIR", "SSL_CERT_FILE", "CODEX_HOME", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA", "ALLUSERSPROFILE", "PROGRAMDATA", "VIRTUAL_ENV"})
RESERVED_PREFIXES = ("ACTIONS_", "AWS_", "AZURE_", "DYLD_", "GCLOUD_", "GITHUB_", "GOOGLE_",
                     "LD_", "NODE_", "NPM_", "PIP_", "PYTHON_", "RUNNER_", "SSH_", "UV_", "XDG_",
                     "SENTRA_", "CODEX_")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
NPM_NAME = r"(?:@[a-z0-9._-]+/)?[a-z0-9][a-z0-9._-]*"
PYPI_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"


def is_reserved_agent_env_name(name: str) -> bool:
    normalized = name.strip().upper()
    return normalized in RESERVED_NAMES or normalized.startswith(RESERVED_PREFIXES)


def validate_agent_env(raw: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, Mapping) or len(raw) > 64:
        raise ValueError("invalid registry environment")
    normalized = set()
    result = []
    for key, value in raw.items():
        if (not isinstance(key, str) or not ENV_NAME.fullmatch(key) or key.upper() in normalized
            or not isinstance(value, str) or len(value) > 4096 or "\0" in value):
            raise ValueError("invalid or duplicate registry environment key")
        if is_reserved_agent_env_name(key):
            raise ValueError("reserved registry environment variable: " + key)
        normalized.add(key.upper())
        result.append((key, value))
    return tuple(sorted(result))


def _args(value: Any) -> tuple[str, ...]:
    if (not isinstance(value, list) or len(value) > 64 or
        any(not isinstance(arg, str) or len(arg) > 2048 or "\0" in arg for arg in value)):
        raise ValueError("invalid registry argv")
    return tuple(value)


def _command(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or any(c in value for c in "\0\r\n"):
        raise ValueError("invalid binary command")
    # This is a relative executable path, never a shell command. Spaces within
    # a filename are allowed; metacharacters and path escapes are not.
    win, posix = PureWindowsPath(value), PurePosixPath(value.replace("\\", "/"))
    if (win.drive or win.is_absolute() or posix.is_absolute() or ".." in posix.parts
        or any(c in value for c in "|;&<>`$\"'") or value.lower().endswith((".cmd", ".bat", ".ps1", ".sh"))):
        raise ValueError("binary command must be a contained executable path")
    return value


def platform_target(system: str, architecture: str) -> str:
    system = {"win32": "windows", "windows": "windows", "linux": "linux",
              "darwin": "darwin", "macos": "darwin"}.get(system.lower(), "")
    arch = {"amd64": "x86_64", "x64": "x86_64", "x86_64": "x86_64",
            "arm64": "aarch64", "aarch64": "aarch64"}.get(architecture.lower(), "")
    target = f"{system}-{arch}"
    if target not in TARGETS:
        raise ValueError("unsupported ACP platform")
    return target


@dataclass(frozen=True, slots=True)
class ACPBinaryTarget:
    platform: str
    archive: str
    command: str
    args: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    sha256: str | None


@dataclass(frozen=True, slots=True)
class ACPDistribution:
    kind: str
    package: str | None = None
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    targets: tuple[ACPBinaryTarget, ...] = ()

    @classmethod
    def parse(cls, kind: str, raw: Any, *, version: str) -> "ACPDistribution":
        if not isinstance(raw, Mapping):
            raise ValueError("invalid distribution descriptor")
        if kind == "binary":
            if not raw or set(raw) - TARGETS:
                raise ValueError("invalid binary platforms")
            targets = []
            for platform, target in sorted(raw.items()):
                if (not isinstance(target, Mapping) or set(target) - {"archive", "sha256", "cmd", "args", "env"}
                    or not {"archive", "cmd"} <= set(target)):
                    raise ValueError("invalid binary target")
                archive = target["archive"]
                if not isinstance(archive, str) or len(archive) > 4096 or any(c.isspace() for c in archive):
                    raise ValueError("invalid registry archive URL")
                url = urlsplit(archive)
                if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
                    raise ValueError("registry archive requires HTTPS without credentials")
                checksum = target.get("sha256")
                if checksum is not None and (not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", checksum)):
                    raise ValueError("invalid registry archive checksum")
                targets.append(ACPBinaryTarget(platform, archive, _command(target["cmd"]),
                    _args(target.get("args", [])), validate_agent_env(target.get("env", {})),
                    checksum.lower() if checksum else None))
            return cls(kind, targets=tuple(targets))
        if kind not in {"npx", "uvx"} or set(raw) - {"package", "args", "env"}:
            raise ValueError("unknown distribution descriptor")
        package = raw.get("package")
        pattern = (NPM_NAME + "@" + re.escape(version) if kind == "npx"
                   else PYPI_NAME + r"(?:==|@)" + re.escape(version))
        if not isinstance(package, str) or len(package) > 256 or not re.fullmatch(pattern, package):
            raise ValueError("unpinned registry executable")
        if kind == "uvx":
            # PyPI uses ==, unlike npm's @. Accept the registry helper's legacy
            # @ spelling, but emit the actual uv-compatible pinned requirement.
            package = re.sub(r"@" + re.escape(version) + "$", "==" + version, package)
        return cls(kind, package, _args(raw.get("args", [])), validate_agent_env(raw.get("env", {})))


@dataclass(frozen=True, slots=True)
class ACPPlanStep:
    action: str
    subject: str


@dataclass(frozen=True, slots=True)
class ACPInstallationPlan:
    agent_id: str
    version: str
    channel: str
    platform: str
    distribution_kind: str
    package: str | None
    archive: str | None
    archive_sha256: str | None
    executable_relative: str | None
    runner: str | None
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    dependencies: tuple[str, ...]
    diagnostics: tuple[str, ...]
    steps: tuple[ACPPlanStep, ...]
    catalog_sha256: str | None = None
    requires_launch_authorization: bool = True

    @property
    def launch_ready(self) -> bool:
        # Descriptor plans never constitute verification/admission, even if
        # dependencies are reported present by the caller.
        return False

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def build_installation_plan(entry, *, system: str, architecture: str,
                            kind: str | None = None, available_dependencies: frozenset[str] = frozenset(),
                            catalog_sha256: str | None = None) -> ACPInstallationPlan:
    platform = platform_target(system, architecture)
    variants = entry.distributions
    if not variants:
        raise ValueError("registry entry lacks validated descriptors")
    candidates = [d for d in variants if kind is None or d.kind == kind]
    if len(candidates) != 1:
        raise ValueError("explicit distribution selection required")
    selected = candidates[0]
    diagnostics = ["LAUNCH_AUTHORIZATION_REQUIRED", "ARTIFACT_TRUST_REQUIRED"]
    steps = []
    package = selected.package
    archive = checksum = relative = runner = None
    env = selected.env
    if selected.kind == "binary":
        target = next((t for t in selected.targets if t.platform == platform), None)
        if target is None:
            raise ValueError("binary distribution unavailable on requested platform")
        archive, checksum, relative, env = target.archive, target.sha256, target.command, target.env
        argv, deps = target.args, ()
        steps.append(ACPPlanStep("download_to_staging", archive))
        if checksum:
            steps.append(ACPPlanStep("verify_archive_sha256", checksum))
        else:
            diagnostics.append("ARCHIVE_CHECKSUM_MISSING")
        steps.extend((ACPPlanStep("extract_contained_paths", platform),
                      ACPPlanStep("verify_executable_independently", relative)))
    elif selected.kind == "npx":
        runner, deps = "npx", ("node", "npx")
        argv = ("--yes", "--", package, *selected.args)
        steps.append(ACPPlanStep("provision_pinned_npm_package", package))
        diagnostics.append("PACKAGE_CONTENT_NOT_VERIFIED")
    else:
        runner, deps = "uvx", ("uvx",)
        command = package.split("==", 1)[0]
        argv = ("--from", package, "--", command, *selected.args)
        steps.append(ACPPlanStep("provision_pinned_python_package", package))
        diagnostics.append("PACKAGE_CONTENT_NOT_VERIFIED")
    for dep in deps:
        if dep not in available_dependencies:
            diagnostics.append("DEPENDENCY_MISSING:" + dep)
    if platform.startswith("windows") and runner == "npx":
        diagnostics.append("WINDOWS_NPX_CMD_REQUIRES_APPROVED_NATIVE_LAUNCHER")
    if env:
        diagnostics.append("ENVIRONMENT_REQUIRES_SEPARATE_ADMISSION")
    steps.extend((ACPPlanStep("resolve_absolute_entrypoint", runner or relative),
                  ACPPlanStep("authorize_launch_request", entry.agent_id)))
    return ACPInstallationPlan(entry.agent_id, entry.version, entry.channel, platform, selected.kind,
        package, archive, checksum, relative, runner, tuple(argv), env, deps, tuple(diagnostics),
        tuple(steps), catalog_sha256)
