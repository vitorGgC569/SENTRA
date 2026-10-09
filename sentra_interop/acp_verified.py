"""Offline ACP executable resolver with externally provisioned HMAC trust root.

HMAC authenticates manifests only when trust keys are pre-provisioned through a
separate trusted channel. It is NOT a distributed signature/PKI. No downloads,
PATH lookup, dynamic launch, npx/uvx, or permission grants from catalog data.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sentra_runtime.contracts import OperationRequest
from .gate import InteropGate
from .registry import AGENT_ID, VERSION
from .registry_install import ACPInstallationPlan

HEX64 = re.compile(r"^[0-9a-f]{64}$")
PUBLISHER = re.compile(r"^[a-z][a-z0-9.-]{1,127}$")
MAX_MANIFEST = 65536
MAX_EXECUTABLE = 100 * 1024 * 1024


class ACPVerificationDenied(ValueError):
    pass


def canonical(data: Mapping[str, Any]) -> bytes:
    try:
        blob = json.dumps(data, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ACPVerificationDenied("invalid signed ACP manifest") from exc
    if len(blob)>MAX_MANIFEST:
        raise ACPVerificationDenied("manifest exceeds size limit")
    return blob


def _semver(value: str) -> tuple[int, int, int]:
    if not isinstance(value,str) or not VERSION.fullmatch(value):
        raise ACPVerificationDenied("ACP version must be pinned stable semver")
    return tuple(int(x) for x in value.split("."))


def _check_path(value: str, root: Path, *, is_file: bool) -> Path:
    if not isinstance(value,str) or not value or "\0" in value:
        raise ACPVerificationDenied("untrusted ACP path")
    raw=Path(value)
    if not raw.is_absolute() or ".." in raw.parts:
        raise ACPVerificationDenied("relative/path-traversal ACP entrypoint")
    try:
        if raw.is_symlink():
            raise ACPVerificationDenied("ACP symlink executable forbidden")
        resolved=raw.resolve(strict=True)
    except OSError as exc:
        raise ACPVerificationDenied("ACP path unavailable") from exc
    if not resolved.is_relative_to(root):
        raise ACPVerificationDenied("ACP entrypoint outside approved install root")
    if is_file and not resolved.is_file():
        raise ACPVerificationDenied("ACP executable not a regular file")
    if not is_file and not resolved.is_dir():
        raise ACPVerificationDenied("ACP cwd not a directory")
    return resolved


@dataclass(frozen=True, slots=True)
class VerifiedACPEntrypoint:
    provider: str
    publisher: str
    version: str
    executable: str
    cwd: str
    argv: tuple[str, ...]
    sha256: str
    manifest_sha256: str
    sequence: int


class ACPVerifiedResolver:
    """Manifest pin, external HMAC trust, path/file hash and persisted rollback guard."""

    def __init__(self, *, install_root: str, ledger_file: str,
                 publisher_keys: Mapping[str, bytes], revoked_publishers: frozenset[str],
                 gate: InteropGate) -> None:
        root=Path(install_root).resolve(strict=True)
        ledger=Path(ledger_file).resolve()
        if (not root.is_dir() or not ledger.is_relative_to(root)
            or ledger == root or not publisher_keys
            or not isinstance(revoked_publishers,frozenset)
            or any(not PUBLISHER.fullmatch(p) or not isinstance(k,bytes) or len(k)<32
                   for p,k in publisher_keys.items())):
            raise ACPVerificationDenied("invalid independently approved trust root")
        self.root,self.ledger,self.publisher_keys = root,ledger,dict(publisher_keys)
        self.revoked_publishers,self.gate = revoked_publishers,gate
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS accepted_catalogs(
                provider TEXT PRIMARY KEY, publisher TEXT NOT NULL,
                sequence INTEGER NOT NULL, version TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL)""")

    @contextmanager
    def _db(self):
        db=sqlite3.connect(self.ledger,timeout=10)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _verify(self, manifest: Mapping[str, Any], signature_hex: str,
                provider: str, version: str) -> VerifiedACPEntrypoint:
        if not isinstance(manifest,Mapping) or set(manifest)!={"schema","publisher","sequence","agents"}:
            raise ACPVerificationDenied("unknown signed ACP catalog schema")
        if manifest["schema"] != 1 or type(manifest["sequence"]) is not int or manifest["sequence"]<1:
            raise ACPVerificationDenied("unsupported ACP catalog version")
        pub=manifest["publisher"]
        if (not isinstance(pub,str) or pub not in self.publisher_keys
            or pub in self.revoked_publishers):
            raise ACPVerificationDenied("untrusted/revoked ACP publisher")
        blob=canonical(manifest)
        if not isinstance(signature_hex,str) or not HEX64.fullmatch(signature_hex):
            raise ACPVerificationDenied("invalid publisher authenticator")
        expected=hmac.new(self.publisher_keys[pub],blob,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature_hex,expected):
            raise ACPVerificationDenied("ACP manifest authenticity failed")
        if not isinstance(manifest["agents"],list) or len(manifest["agents"])>256:
            raise ACPVerificationDenied("invalid ACP agent catalog")
        chosen=None
        seen=set()
        for record in manifest["agents"]:
            if not isinstance(record,Mapping) or set(record)!={
                "provider","version","executable","cwd","argv","sha256"}:
                raise ACPVerificationDenied("unknown ACP entrypoint metadata")
            ident=record["provider"]
            if not isinstance(ident,str) or not AGENT_ID.fullmatch(ident) or ident in seen:
                raise ACPVerificationDenied("duplicate or unsafe ACP provider")
            seen.add(ident)
            _semver(record["version"])
            if ident == provider:
                chosen=record
        if chosen is None or chosen["version"]!=version:
            raise ACPVerificationDenied("provider/version not pinned")
        if (not isinstance(chosen["sha256"],str)
            or not HEX64.fullmatch(chosen["sha256"])):
            raise ACPVerificationDenied("invalid executable digest")
        executable=_check_path(chosen["executable"],self.root,is_file=True)
        cwd=_check_path(chosen["cwd"],self.root,is_file=False)
        argv=chosen["argv"]
        if (not isinstance(argv,list) or len(argv)>64 or
            any(not isinstance(arg,str) or len(arg)>2048 or "\0" in arg
                for arg in argv)):
            raise ACPVerificationDenied("invalid pinned ACP argv")
        if executable.stat().st_size>MAX_EXECUTABLE:
            raise ACPVerificationDenied("executable too large for hash verification")
        digest=hashlib.sha256()
        with executable.open("rb") as inp:
            for chunk in iter(lambda:inp.read(1<<20),b""):
                digest.update(chunk)
        if not hmac.compare_digest(digest.hexdigest(),chosen["sha256"]):
            raise ACPVerificationDenied("ACP executable digest mismatch")
        return VerifiedACPEntrypoint(provider,pub,version,str(executable),str(cwd),
                                      tuple(argv),chosen["sha256"],
                                      hashlib.sha256(blob).hexdigest(),manifest["sequence"])

    async def resolve(self, manifest: Mapping[str, Any], signature_hex: str, *,
                      provider: str, version: str, request: OperationRequest,
                      installation_plan: ACPInstallationPlan | None = None,
                      installed_directory: str | None = None
                      ) -> VerifiedACPEntrypoint:
        verified=self._verify(manifest,signature_hex,provider,version)
        expected_arguments = {"provider":provider,"version":version,
                              "publisher":verified.publisher,"sequence":verified.sequence,
                              "manifest_sha256":verified.manifest_sha256,
                              "executable_sha256":verified.sha256}
        if installation_plan is not None:
            plan = installation_plan
            if (not isinstance(plan, ACPInstallationPlan) or plan.agent_id != provider
                or plan.version != version or plan.channel != "stable"
                or plan.distribution_kind != "binary" or plan.environment
                or not isinstance(installed_directory, str)):
                raise ACPVerificationDenied("installed plan requires an independently verified binary with no environment")
            directory = _check_path(installed_directory, self.root, is_file=False)
            executable = _check_path(str(directory / plan.executable_relative), self.root, is_file=True)
            if str(executable) != verified.executable or tuple(plan.argv) != verified.argv:
                raise ACPVerificationDenied("installed plan does not match signed executable/argv")
            expected_arguments.update({"plan_sha256": plan.fingerprint,
                                       "installed_directory": str(directory)})
        elif installed_directory is not None:
            raise ACPVerificationDenied("installed directory requires an installation plan")
        if (request.capability_id!="acp:resolve" or
            request.arguments!=expected_arguments):
            raise ACPVerificationDenied("ACP resolution OperationRequest mismatch")
        # SENTRA policy is the single authorization source. No launch in resolver.
        if not (await self.gate.decision(request)).allowed:
            raise ACPVerificationDenied("SENTRA ACP resolution grant denied")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT publisher,sequence,version,manifest_sha256 "
                           "FROM accepted_catalogs WHERE provider=?", (provider,)).fetchone()
            if old:
                prior_pub, prior_sequence, prior_version, prior_hash=old
                if (verified.sequence<prior_sequence or
                    _semver(verified.version)<_semver(prior_version) or
                    (verified.sequence==prior_sequence and
                     (prior_hash!=verified.manifest_sha256 or prior_pub!=verified.publisher))):
                    raise ACPVerificationDenied("ACP rollback or inconsistent manifest")
            if not (await self.gate.decision(request)).allowed:
                raise ACPVerificationDenied("SENTRA ACP resolution grant revoked")
            if old is None or verified.sequence>old[1]:
                db.execute("INSERT INTO accepted_catalogs VALUES (?,?,?,?,?) "
                           "ON CONFLICT(provider) DO UPDATE SET publisher=excluded.publisher,"
                           "sequence=excluded.sequence,version=excluded.version,"
                           "manifest_sha256=excluded.manifest_sha256",
                           (provider,verified.publisher,verified.sequence,
                            verified.version,verified.manifest_sha256))
        return verified
