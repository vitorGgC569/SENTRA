"""Pinned QuickJS configuration from operator env or frozen build selection.

Owner: Pacto. The audited ``quickjs.wasm`` + CycloneDX SBOM are distributed by
the release pipeline (Vitra owns manifests/distribution); this module only
describes WHERE the host expects them and fails explicitly when they are
absent or unpinned. Frozen builds can carry approved installed-artifact hashes;
they never trust a workspace/sibling manifest as their own trust anchor.
No download, no fetch, no default bytes: an unconfigured
engine reports UNAVAILABLE with remediation, never silent deny.

Expected host configuration (operator-set, never chat/model-supplied):

  SENTRA_QUICKJS_WASM_PATH      pinned local .wasm file (<=32MiB, no symlink)
  SENTRA_QUICKJS_SBOM_PATH      pinned local CycloneDX SBOM (<=1MiB, no symlink)
  SENTRA_QUICKJS_WASM_SHA256    64 hex chars
  SENTRA_QUICKJS_SBOM_SHA256    64 hex chars
"""
from __future__ import annotations

import os
from typing import Any

from . import CodeModeUnavailable, QuickJSArtifact, ResourceLimits

_ENV = ("SENTRA_QUICKJS_WASM_PATH", "SENTRA_QUICKJS_SBOM_PATH",
        "SENTRA_QUICKJS_WASM_SHA256", "SENTRA_QUICKJS_SBOM_SHA256")


def describe_configuration() -> dict[str, Any]:
    """Report which artifact slots are configured (presence only, no bytes)."""
    values = {key: os.environ.get(key, "") for key in _ENV}
    configured = {key: bool(value) for key, value in values.items()}
    return {"configured": configured,
            "fully_configured": all(configured.values()),
            "remediation": "set SENTRA_QUICKJS_WASM_PATH/SBOM_PATH + *_SHA256 "
                           "to the audited release pins; see Vitra release manifests"}


def load_artifact_from_env() -> QuickJSArtifact:
    """Build the pinned artifact or raise explicit UNAVAILABLE."""
    status = describe_configuration()
    if not status["fully_configured"]:
        missing = sorted(key for key, present in status["configured"].items()
                         if not present)
        raise CodeModeUnavailable(
            "QuickJS artifact unconfigured (missing %s); %s"
            % (", ".join(missing), status["remediation"]))
    return QuickJSArtifact(
        wasm_path=os.environ["SENTRA_QUICKJS_WASM_PATH"],
        sbom_path=os.environ["SENTRA_QUICKJS_SBOM_PATH"],
        wasm_sha256=os.environ["SENTRA_QUICKJS_WASM_SHA256"].strip().lower(),
        sbom_sha256=os.environ["SENTRA_QUICKJS_SBOM_SHA256"].strip().lower())


def load_artifact() -> QuickJSArtifact:
    """Explicit operator pins take precedence; otherwise use frozen build pins.

    A partial operator configuration is an error, never permission to choose a
    different engine/artifact. Source checkouts remain explicit configuration.
    Installed pins do not enable Code Mode or create tool/operation grants.
    """
    if any(os.environ.get(key) for key in _ENV):
        return load_artifact_from_env()
    from sentra_remote.runtime_payload import load_installed_component
    try:
        component = load_installed_component('quickjs')
        component.file('manifest', maximum=1024 * 1024)
        wasm = component.file('wasm', maximum=32 * 1024 * 1024)
        sbom = component.file('sbom', maximum=1024 * 1024)
        return QuickJSArtifact(str(wasm), str(sbom), component.files[component.entrypoints['wasm']],
                               component.files[component.entrypoints['sbom']])
    except (OSError, ValueError, RuntimeError) as error:
        raise CodeModeUnavailable('Pinned installed QuickJS unavailable: ' + type(error).__name__) from error


def build_admission(*, limits: ResourceLimits | None = None):
    """Admission bound to env pins when present, else explicitly unconfigured."""
    from . import QuickJSWasmAdmission
    try:
        artifact = load_artifact()
    except CodeModeUnavailable:
        return QuickJSWasmAdmission(limits=limits, artifact=None)
    return QuickJSWasmAdmission(limits=limits, artifact=artifact)
