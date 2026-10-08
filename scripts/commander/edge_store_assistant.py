"""Edge Add-ons assistant: reproducible package plus guarded REST API v1.1 updates.

An initial Partner Center publication MUST be completed by the account owner.
No upload or publish is permitted while the extension still embeds the local
installation proof or requests unnecessary global host access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "edge_extension"
BASE = "https://api.addons.microsoftedge.microsoft.com/v1"
ALLOWED_SUFFIXES = {".js", ".json", ".html", ".css", ".png", ".svg", ".jpg", ".webp"}


def store_preflight(source: Path = SOURCE) -> dict[str, Any]:
    blockers: list[str] = []
    try:
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("manifest_version") != 3:
            blockers.append("MV3 manifest is missing or invalid")
            manifest = {}
    except (OSError, ValueError):
        manifest = {}
        blockers.append("manifest.json is missing or invalid")

    if (source / "sentra-bootstrap.json").is_file():
        blockers.append(
            "install-local pairing proof is bundled: implement per-device store "
            "pairing without shared static proof before publication"
        )
    if "<all_urls>" in manifest.get("host_permissions", []):
        blockers.append(
            "manifest requests <all_urls>: narrow permissions or document and "
            "validate a genuinely required scope before store submission"
        )
    if "SENTRA" not in str(manifest.get("name", "")).upper():
        blockers.append("store extension identity has not been branded SENTRA")
    if not (source / "service-worker.js").is_file():
        blockers.append("service-worker.js missing")
    return {
        "ready_for_store": not blockers,
        "blockers": blockers,
        "version": str(manifest.get("version", "")),
        "stage": "existing-product-update-only",
    }


def _packaged_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink is not permitted in Edge release payload")
        if (
            path.is_file()
            and path.suffix.lower() in ALLOWED_SUFFIXES
            and path.name != "sentra-bootstrap.json"
        ):
            files.append(path)
    return files


def validate_store_archive(source: Path, archive: Path) -> None:
    """Reject stale/tampered ZIPs, pairing proofs and unreviewed archive members."""
    if not archive.is_file():
        raise FileNotFoundError("Edge package must be created first")
    expected = {
        path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _packaged_files(source)
    }
    try:
        with zipfile.ZipFile(archive) as zip_file:
            actual = zip_file.namelist()
            if len(actual) != len(set(actual)):
                raise ValueError("duplicate file names in Edge package")
            if set(actual) != set(expected):
                raise ValueError("Edge package differs from current reviewed sources")
            for name in actual:
                info = zip_file.getinfo(name)
                if info.file_size > 20 * 1024 * 1024:
                    raise ValueError("oversized file in Edge package")
                if hashlib.sha256(zip_file.read(name)).hexdigest() != expected[name]:
                    raise ValueError("Edge package differs from current reviewed sources")
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid Edge package") from exc
    if (source / "sentra-bootstrap.json").is_file():
        raise ValueError("install-local pairing proof must never be uploaded to Edge Add-ons")


def package(source: Path, target: Path) -> dict[str, Any]:
    status = store_preflight(source)
    if not (source / "manifest.json").is_file():
        raise FileNotFoundError("manifest.json is missing")
    candidates = _packaged_files(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in candidates:
            relative = path.relative_to(source).as_posix()
            if relative.startswith("../") or relative.startswith("/"):
                raise ValueError("invalid Edge package path")
            info = zipfile.ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return {
        **status, "candidate_only": True,
        "package": str(target), "sha256": digest,
        "files": [path.relative_to(source).as_posix() for path in candidates],
    }


def _config() -> tuple[str, dict[str, str]]:
    key = os.environ.get("SENTRA_EDGE_API_KEY", "").strip()
    client_id = os.environ.get("SENTRA_EDGE_CLIENT_ID", "").strip()
    product_id = os.environ.get("SENTRA_EDGE_PRODUCT_ID", "").strip()
    if not (key and client_id and product_id):
        raise PermissionError(
            "SENTRA_EDGE_API_KEY, SENTRA_EDGE_CLIENT_ID and "
            "SENTRA_EDGE_PRODUCT_ID must be configured privately"
        )
    try:
        uuid.UUID(product_id)
    except ValueError as exc:
        raise ValueError("invalid Edge Add-ons product ID") from exc
    return product_id, {
        "Authorization": "ApiKey " + key, "X-ClientID": client_id,
    }


def _request(path: str, *, method: str = "GET", payload: bytes | None = None,
             content_type: str | None = None) -> dict[str, Any]:
    product_id, headers = _config()
    if content_type:
        headers["Content-Type"] = content_type
    url = BASE + "/products/" + product_id + path
    request = urllib.request.Request(
        url, data=payload, method=method, headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read(1024 * 1024)
            try:
                parsed = json.loads(body) if body else {}
            except (ValueError, UnicodeDecodeError):
                parsed = {}
            return {
                "http_status": response.status,
                "operation_id": str(response.headers.get("Location") or "").rstrip("/").split("/")[-1],
                "result": parsed if isinstance(parsed, dict) else {},
            }
    except urllib.error.HTTPError as exc:
        # Never print headers or query parameters that may include credentials.
        return {"http_status": exc.code, "ok": False, "reason": "edge_api_http_error"}


def operation_status(operation_id: str, *, kind: str = "package") -> dict[str, Any]:
    if not operation_id or not all(c.isalnum() or c == "-" for c in operation_id):
        raise ValueError("invalid Edge operation ID")
    if kind not in {"package", "publish"}:
        raise ValueError("invalid Edge operation kind")
    tail = (
        "/submissions/draft/package/operations/" if kind == "package"
        else "/submissions/operations/"
    ) + operation_id
    response = _request(tail)
    state = response.get("result", {}).get("status")
    return {
        "http_status": response["http_status"],
        "state": state,
        "ok": response["http_status"] == 200 and state == "Succeeded",
        "error_code": response.get("result", {}).get("errorCode"),
    }


def upload(source: Path, archive: Path, *, approved: bool) -> dict[str, Any]:
    if not approved:
        raise PermissionError("store upload requires --approve-upload")
    report = store_preflight(source)
    if not report["ready_for_store"]:
        return {"ok": False, "blockers": report["blockers"]}
    validate_store_archive(source, archive)
    response = _request(
        "/submissions/draft/package", method="POST",
        payload=archive.read_bytes(), content_type="application/zip",
    )
    return {"ok": response["http_status"] == 202,
            "operation_id": response.get("operation_id"),
            "http_status": response["http_status"]}


def publish(source: Path, *, uploaded_operation: str, approved: bool) -> dict[str, Any]:
    if not approved:
        raise PermissionError("publishing an Edge update requires --approve-publish")
    report = store_preflight(source)
    if not report["ready_for_store"]:
        return {"ok": False, "blockers": report["blockers"]}
    confirmed = operation_status(uploaded_operation)
    if not confirmed["ok"]:
        return {"ok": False, "reason": "package_upload_not_confirmed", "upload": confirmed}
    response = _request(
        "/submissions", method="POST",
        payload=b"SENTRA update: verified local package, tests and pairing review.",
        content_type="text/plain",
    )
    return {"ok": response["http_status"] == 202,
            "operation_id": response.get("operation_id"),
            "http_status": response["http_status"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("doctor", "package", "upload", "publish", "status"))
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--archive", type=Path, default=ROOT / ".tmp" / "release-assistant" / "sentra-edge.zip")
    parser.add_argument("--approve-upload", action="store_true")
    parser.add_argument("--approve-publish", action="store_true")
    parser.add_argument("--upload-operation-id", default="")
    parser.add_argument("--operation-id", default="")
    parser.add_argument("--kind", choices=("package", "publish"), default="package")
    args = parser.parse_args(argv)
    try:
        if args.action == "doctor":
            result = store_preflight(args.source)
            ok = result["ready_for_store"]
        elif args.action == "package":
            result = package(args.source, args.archive)
            ok = True  # A package can be built for QA while store upload is blocked.
        elif args.action == "upload":
            result = upload(args.source, args.archive, approved=args.approve_upload)
            ok = result["ok"]
        elif args.action == "publish":
            result = publish(
                args.source, uploaded_operation=args.upload_operation_id,
                approved=args.approve_publish,
            )
            ok = result["ok"]
        else:
            result = operation_status(args.operation_id, kind=args.kind)
            ok = result["ok"]
    except (PermissionError, OSError, ValueError) as exc:
        result = {"ok": False, "reason": type(exc).__name__, "detail": str(exc)}
        ok = False
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
