"""Pinned-clone descriptors and plans; no network, installs or agent execution."""
import asyncio
from dataclasses import replace
import hashlib
import hmac
import json
from pathlib import Path

import pytest

from sentra_interop.acp_verified import ACPVerifiedResolver, ACPVerificationDenied, canonical
from sentra_interop.registry import ACPRegistryEntry, ACPVersionedCatalog
from sentra_interop.registry_install import platform_target, validate_agent_env
from sentra_interop.gate import InteropGate
from sentra_runtime.contracts import Capability, Machine, OperationRequest, PolicyDecision

ROOT = Path(__file__).resolve().parents[2]


def entry(kind="binary", spec=None):
    spec = spec or {"windows-x86_64":{"archive":"https://example.org/agent-1.2.3.zip",
                        "cmd":"./agent.exe","args":["--acp"],"sha256":"ab"*32}}
    return ACPRegistryEntry.from_mapping({"id":"agent","name":"Agent","version":"1.2.3",
                                          "distribution":{kind:spec}}, pinned_version="1.2.3")


def test_real_clone_manifests_produce_platform_and_uvx_pinned_plans():
    clone = ROOT / "third_party" / "acp-registry"
    if not clone.exists():
        pytest.skip("pinned registry clone missing; not an installation success")
    rows = [json.loads((clone / name / "agent.json").read_text(encoding="utf8"))
            for name in ("codex-acp", "antigravity-acp", "fast-agent")]
    catalog = ACPVersionedCatalog.from_index({"version":"1.0.0","agents":rows}, schema_version="1.0.0",
                                            pinned_versions={r["id"]:r["version"] for r in rows})
    binary = catalog.installation_plan("antigravity-acp", version="1.3.0", system="Windows", architecture="AMD64")
    assert binary.platform == "windows-x86_64"
    assert binary.executable_relative == "./agy_acp_server.exe"
    assert "ARCHIVE_CHECKSUM_MISSING" in binary.diagnostics
    assert binary.catalog_sha256 == catalog.snapshot_sha256
    assert not binary.launch_ready
    python = catalog.installation_plan("fast-agent", version=rows[2]["version"], system="windows", architecture="arm64")
    assert python.package == "fast-agent-acp==" + rows[2]["version"]
    assert python.argv[:3] == ("--from", python.package, "--")
    assert python.environment == (("FAST_AGENT_MODEL","codexplan"),)
    assert "ENVIRONMENT_REQUIRES_SEPARATE_ADMISSION" in python.diagnostics
    npm = catalog.installation_plan("codex-acp", version="2.1.1", system="windows", architecture="x64",
                                   available_dependencies=frozenset({"node","npx"}))
    assert npm.argv[:2] == ("--yes","--")
    assert not any(d.startswith("DEPENDENCY_MISSING") for d in npm.diagnostics)
    assert "WINDOWS_NPX_CMD_REQUIRES_APPROVED_NATIVE_LAUNCHER" in npm.diagnostics


def test_multiple_variants_require_explicit_kind_and_no_silent_platform_fallback():
    raw = {"id":"agent","name":"Agent","version":"1.2.3","distribution":{
        "binary":{"linux-x86_64":{"archive":"https://example.org/a","cmd":"agent"}},
        "npx":{"package":"@example/agent@1.2.3","args":["--stdio"]}}}
    selected = ACPRegistryEntry.from_mapping(raw, pinned_version="1.2.3")
    assert selected.distribution_kind == "multiple"
    with pytest.raises(ValueError, match="explicit"):
        selected.installation_plan(system="windows", architecture="amd64")
    with pytest.raises(ValueError, match="unavailable"):
        selected.installation_plan(system="windows", architecture="amd64", kind="binary")
    plan = selected.installation_plan(system="windows", architecture="amd64", kind="npx")
    assert plan.package == "@example/agent@1.2.3"
    assert "DEPENDENCY_MISSING:node" in plan.diagnostics
    assert plan.fingerprint == selected.installation_plan(system="windows", architecture="amd64", kind="npx").fingerprint
    assert plan.fingerprint != replace(plan, argv=(*plan.argv,"other")).fingerprint


@pytest.mark.parametrize("key", ["path","SystemRoot","NODE_OPTIONS","NPM_TOKEN","GITHUB_TOKEN",
                                 "UV_INDEX_URL","PYTHONPATH","AWS_SECRET_ACCESS_KEY","SENTRA_ROOT","CODEX_HOME"])
def test_reserved_environment_rejected_case_insensitive(key):
    with pytest.raises(ValueError, match="reserved"):
        validate_agent_env({key:"must-not-enter-launch"})


@pytest.mark.parametrize("env", [{"MODEL":"a","model":"b"}, {" BAD":"a"}, {"OK":"a\0b"}, {"OK":1}])
def test_malformed_duplicate_environment_rejected(env):
    with pytest.raises(ValueError):
        validate_agent_env(env)


@pytest.mark.parametrize("cmd", ["../agent.exe","C:\\agent.exe","/bin/agent","agent.exe; whoami",
                                 "agent.exe | other","run.cmd","run.ps1","$HOME/agent"])
def test_binary_command_cannot_be_shell_or_escape(cmd):
    with pytest.raises(ValueError):
        entry(spec={"windows-x86_64":{"archive":"https://example.org/a.zip","cmd":cmd}})


@pytest.mark.parametrize("url", ["file:///agent.zip","http://example.org/a.zip","https://user:pass@example.org/a.zip"])
def test_registry_archive_must_be_https_without_credentials(url):
    with pytest.raises(ValueError):
        entry(spec={"windows-x86_64":{"archive":url,"cmd":"agent.exe"}})


@pytest.mark.parametrize("kind,package", [("npx","agent@latest"),("npx","https://example.org/a"),
    ("uvx","agent>=1.2.3"),("uvx","agent==1.2.4"),("npx","--help@1.2.3")])
def test_unpinned_packages_and_option_injection_rejected(kind, package):
    with pytest.raises(ValueError, match="unpinned"):
        entry(kind, {"package":package})


@pytest.mark.parametrize("spelling", ["agent==1.2.3", "agent@1.2.3"])
def test_uvx_python_requirement_normalizes_independently_of_npm(spelling):
    selected = entry("uvx", {"package":spelling})
    assert selected.distribution_name == "agent==1.2.3"
    assert selected.installation_plan(system="linux", architecture="aarch64").argv == (
        "--from","agent==1.2.3","--","agent")


def test_platform_not_supported_not_guessed():
    assert platform_target("darwin","arm64") == "darwin-aarch64"
    with pytest.raises(ValueError):
        platform_target("windows", "x86")


def test_installed_plan_requires_signed_matching_executable_and_policy(tmp_path):
    async def case():
        executable = tmp_path / "agent.exe"
        executable.write_bytes(b"non-executable test artifact; only hashing is tested")
        plan = entry().installation_plan(system="windows", architecture="amd64")
        manifest = {"schema":1,"publisher":"approved","sequence":1,"agents":[{
            "provider":"agent","version":"1.2.3","executable":str(executable),"cwd":str(tmp_path),
            "argv":["--acp"],"sha256":hashlib.sha256(executable.read_bytes()).hexdigest()}]}
        key = b"k" * 32
        signature = hmac.new(key, canonical(manifest), hashlib.sha256).hexdigest()
        arguments = {"provider":"agent","version":"1.2.3","publisher":"approved","sequence":1,
            "manifest_sha256":hashlib.sha256(canonical(manifest)).hexdigest(),
            "executable_sha256":manifest["agents"][0]["sha256"],"plan_sha256":plan.fingerprint,
            "installed_directory":str(tmp_path)}
        op = OperationRequest("resolve", "tester", "machine", "acp:resolve", "work", "key", arguments)
        gate = InteropGate(Machine("machine","agent","tester",(Capability("acp:resolve","resolve"),)),
                           lambda _:PolicyDecision(True,"test grant"))
        resolver = ACPVerifiedResolver(install_root=str(tmp_path), ledger_file=str(tmp_path/"trust.sqlite"),
            publisher_keys={"approved":key}, revoked_publishers=frozenset(), gate=gate)
        verified = await resolver.resolve(manifest, signature, provider="agent", version="1.2.3", request=op,
                                          installation_plan=plan, installed_directory=str(tmp_path))
        assert verified.executable == str(executable)
        with pytest.raises(ACPVerificationDenied, match="does not match"):
            await resolver.resolve(manifest, signature, provider="agent", version="1.2.3", request=op,
                                   installation_plan=replace(plan, argv=("--unsafe",)), installed_directory=str(tmp_path))
        assert executable.read_bytes().startswith(b"non-executable")
    asyncio.run(case())
