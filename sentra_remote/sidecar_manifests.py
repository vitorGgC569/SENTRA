"""Sidecar release manifests received from Lume / Pulso / Selo (Vitra-owned).

Vitra composes the product release but does not own interop, workflows or
quality internals. Each owner publishes a signed manifest describing its
sidecar surface; Vitra validates structure + digests and folds them into
the release manifest for Codex to seal. Signature/signer verification is
REAL: a manifest without a verifiable producer signature reference is
rejected, never simulated or auto-trusted.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

SCHEMA = 1

KINDS = ("interop", "workflows", "quality")
KIND_OWNER = {"interop": "Lume", "workflows": "Pulso", "quality": "Selo"}


def validate_sidecar_manifest(kind: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Structural validation of one owner-published sidecar manifest."""
    if kind not in KINDS:
        raise ValueError("unknown sidecar kind")
    if not isinstance(manifest, dict):
        raise ValueError("sidecar manifest must be an object")
    name = str(manifest.get("name") or "").strip()
    version = str(manifest.get("version") or "").strip()
    schema_version = manifest.get("schema_version", manifest.get("mcp_schema_version", 0))
    digest = str(manifest.get("sha256") or manifest.get("digest") or "").lower()
    if not name or len(name) > 128:
        raise ValueError(f"{kind} sidecar manifest lacks a name")
    if not version or len(version) > 64:
        raise ValueError(f"{kind} sidecar manifest lacks a version")
    try:
        schema_int = int(schema_version)
    except (TypeError, ValueError):
        raise ValueError(f"{kind} sidecar manifest lacks a schema version") from None
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError(f"{kind} sidecar manifest lacks a sha256 digest")
    files = manifest.get("files", [])
    if not isinstance(files, list):
        raise ValueError(f"{kind} sidecar manifest files must be a list")
    for entry in files:
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
                or len(str(entry.get("sha256") or "")) != 64):
            raise ValueError(f"{kind} sidecar manifest has an invalid file entry")
    signer = manifest.get("signer") or manifest.get("producer_signature") or ""
    if not isinstance(signer, str) or not signer.strip():
        raise ValueError(
            f"{kind} sidecar manifest lacks a producer signature reference; "
            "signing cannot be simulated"
        )
    license_ref = str(manifest.get("license") or manifest.get("notice") or "").strip()
    if not license_ref:
        raise ValueError(f"{kind} sidecar manifest lacks a license/notice reference")
    return {
        "schema": SCHEMA,
        "kind": kind,
        "owner": KIND_OWNER[kind],
        "name": name,
        "version": version,
        "schema_version": schema_int,
        "sha256": digest,
        "files": len(files),
        "signer": signer.strip(),
        "license": license_ref,
    }


def verify_sidecar_signature(
    manifest: dict[str, Any],
    verify: Callable[[dict[str, Any]], bool] | None,
) -> None:
    """Real producer-signature check via a host-supplied verifier. No simulation."""
    if verify is None or not callable(verify):
        raise ValueError("sidecar signature verification requires a host verifier; refusing to simulate")
    if verify(manifest) is not True:
        raise ValueError("sidecar producer signature did not verify")


def collect_sidecar_manifests(
    manifests: dict[str, dict[str, Any]],
    verify: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Validate (and optionally really verify) all three owner manifests."""
    if not isinstance(manifests, dict):
        raise ValueError("sidecar manifests must be an object keyed by kind")
    collected: dict[str, Any] = {}
    for kind in KINDS:
        item = manifests.get(kind)
        if item is None:
            collected[kind] = {"state": "absent", "owner": KIND_OWNER[kind]}
            continue
        summary = validate_sidecar_manifest(kind, item)
        if verify is not None:
            verify_sidecar_signature(item, verify)
            summary["signature"] = "verified"
        else:
            summary["signature"] = "unverified-pending-host"
        collected[kind] = summary
    combined = hashlib.sha256(
        json.dumps(collected, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {"schema": SCHEMA, "sidecars": collected, "combined_sha256": combined}


def compose_release_sidecars(
    release_manifest: dict[str, Any], collected: dict[str, Any]
) -> dict[str, Any]:
    """Pure merge of validated sidecars into a release manifest copy for Codex."""
    if not isinstance(release_manifest, dict) or not isinstance(collected, dict):
        raise ValueError("release merge requires objects")
    merged = dict(release_manifest)
    merged["sidecars"] = collected.get("sidecars", {})
    merged["sidecars_combined_sha256"] = collected.get("combined_sha256", "")
    return merged
