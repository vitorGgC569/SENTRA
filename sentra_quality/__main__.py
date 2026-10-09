"""Offline SENTRA third-party source validation: python -m sentra_quality."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .source_gate import GateFailure, SourceGate
from .source_inventory import generate_source_inventory
from .grype_gate import VulnerabilityGateError, evaluate_grype_json
from .grype_scan import GrypeScanConfig, scan_sbom, scan_diff


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only third-party provenance check")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1] / "third_party")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--trusted-pins", type=Path,
                        default=Path(__file__).with_name("approved_sources.json"),
                        help="independently reviewed lockfile in tracked SENTRA source")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("verify-all", help="verify every pinned checkout")
    report = sub.add_parser("inventory", help="inventory checked-out sources and license evidence")
    report.add_argument("--require-license", action="store_true", help="fail if any project lacks root license evidence")
    grype = sub.add_parser("grype-check", help="evaluate an already-generated, pinned Grype JSON report (no scanner run)")
    grype.add_argument("--report", type=Path, required=True)
    grype.add_argument("--sha256", required=True, help="trusted digest of Grype report")
    grype.add_argument("--fail-at", default="high", choices=["critical", "high", "medium", "low"])
    scan=sub.add_parser("grype-scan",help="execute an explicitly pinned scanner against a digest-bound local SBOM")
    scan.add_argument("--executable",type=Path,required=True)
    scan.add_argument("--executable-sha256",required=True)
    scan.add_argument("--database-cache",type=Path,required=True)
    scan.add_argument("--sbom",type=Path,required=True)
    scan.add_argument("--sbom-sha256",required=True)
    scan.add_argument("--report",type=Path,required=True)
    scan.add_argument("--max-database-age-hours",type=int,default=120)
    scan.add_argument("--fail-at",default="high",choices=["critical","high","medium","low"])
    compare=sub.add_parser("grype-diff",help="compare recommendations from two SENTRA scan receipts")
    compare.add_argument("--previous",type=Path,required=True)
    compare.add_argument("--current",type=Path,required=True)
    selected = sub.add_parser("verify", help="verify one pinned checkout")
    selected.add_argument("name")
    attest = sub.add_parser("attest", help="calculate tracked file provenance evidence")
    attest.add_argument("name")
    attest.add_argument("path")
    args = parser.parse_args(argv)
    try:
        if args.action=="grype-diff":
            result=scan_diff(json.loads(args.previous.read_text(encoding="utf-8")),
                             json.loads(args.current.read_text(encoding="utf-8")))
            print(json.dumps(result,sort_keys=True));return 0
        if args.action=="grype-scan":
            target=args.report.resolve()
            receipt=target.with_name(target.name+".receipt.json")
            if target.exists() or receipt.exists():raise VulnerabilityGateError("scan output exists; choose a new report path")
            config=GrypeScanConfig(str(args.executable.resolve(strict=True)),args.executable_sha256,
                str(args.database_cache.resolve(strict=True)),args.max_database_age_hours)
            result=scan_sbom(config,args.sbom,expected_sbom_sha256=args.sbom_sha256,fail_at=args.fail_at)
            report_bytes=result.pop("report")
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open("xb") as stream:stream.write(report_bytes)
            with receipt.open("x",encoding="utf-8") as stream:json.dump(result,stream,sort_keys=True,ensure_ascii=False)
            print(json.dumps({"ok":result["decision"]["allowed"],"report_sha256":result["decision"]["report_sha256"],
                "sbom_sha256":result["sbom_sha256"],"receipt":str(receipt)},sort_keys=True))
            return 0 if result["decision"]["allowed"] else 3
        if args.action == "grype-check":
            outcome = evaluate_grype_json(args.report.read_bytes(), fail_at=args.fail_at,
                                          expected_sha256=args.sha256)
            print(json.dumps({"ok": outcome.allowed, "count": len(outcome.findings),
                              "report_sha256": outcome.report_sha256,
                              "digest_verified": outcome.report_digest_verified,
                              "reason": outcome.reason}, sort_keys=True))
            return 0 if outcome.allowed else 3
        gate = SourceGate(args.root, manifest=args.manifest,
                          trusted_pins=args.trusted_pins)
        if args.action == "inventory":
            result = {"ok": True, "inventory": generate_source_inventory(
                gate, require_license=args.require_license)}
        elif args.action == "verify-all":
            entries = gate.verify_all()
            result = {"ok": True, "count": len(entries),
                      "projects": [r.name for r in entries]}
        elif args.action == "verify":
            entry = gate.verify(args.name)
            result = {"ok": True, "name": entry.name, "revision": entry.revision,
                      "tracked_files": entry.tracked_files}
        else:
            result = {"ok": True, "attestation": gate.attest_file(args.name, args.path)}
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except (GateFailure, VulnerabilityGateError, OSError,ValueError,KeyError) as exc:
        # Never include source file contents, tokens or remote subprocess output.
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
