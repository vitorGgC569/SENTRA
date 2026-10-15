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
    diag = sub.add_parser("selo-diagnostics", help="redacted Selo diagnostics snapshot (no secrets)")
    diag.add_argument("--state-root", type=Path, required=True)
    diag.add_argument("--owner", required=True)
    tstats = sub.add_parser("selo-telemetry-stats", help="Selo OTel/Langfuse queue stats")
    tstats.add_argument("--state-root", type=Path, required=True)
    tstats.add_argument("--owner", required=True)
    release = sub.add_parser("selo-release-verify", help="verify source+SBOM+Grype receipt for release")
    release.add_argument("--sbom", type=Path, required=True)
    release.add_argument("--sbom-sha256", required=True)
    release.add_argument("--receipt", type=Path, required=True)
    release.add_argument("--fail-at", default="high", choices=["critical", "high", "medium", "low"])
    release.add_argument("--database-built", default=None,
                         help="Grype DB build timestamp (ISO-8601); also read from receipt")
    release.add_argument("--max-db-age-hours", type=int, default=120)
    release.add_argument("--previous-receipt", type=Path, default=None)
    learn = sub.add_parser("selo-learning-propose", help="propose a reviewed learning suggestion (activates nothing)")
    learn.add_argument("--state-root", type=Path, required=True)
    learn.add_argument("--owner", required=True)
    learn.add_argument("--workspace", required=True)
    learn.add_argument("--origin", type=Path, required=True, help="JSON file: operation_id/work_item_id/run_id/intent_sha256?")
    learn.add_argument("--scope", type=Path, required=True, help="JSON file: non-empty scope object")
    learn.add_argument("--result", type=Path, required=True, help="JSON file: state SUCCEEDED/FAILED + evidence_digest?")
    learn.add_argument("--transcript", type=Path, required=True, help="original transcript text file (stored redacted)")
    learn.add_argument("--ttl", type=int, default=None)
    lreview = sub.add_parser("selo-learning-review", help="approve/reject a learning suggestion")
    lreview.add_argument("--state-root", type=Path, required=True)
    lreview.add_argument("--owner", required=True)
    lreview.add_argument("suggestion_id")
    lreview.add_argument("--verdict", required=True, choices=["APPROVED", "REJECTED"])
    lreview.add_argument("--reviewer", required=True)
    lreview.add_argument("--reason", default="")
    lskill = sub.add_parser("selo-learning-skill", help="review bundle for Pacto SkillPack import (activates nothing)")
    lskill.add_argument("--state-root", type=Path, required=True)
    lskill.add_argument("--owner", required=True)
    lskill.add_argument("suggestion_id")
    lcmp = sub.add_parser("selo-eval-compare", help="compare two dataset runs over the same dataset version")
    lcmp.add_argument("--state-root", type=Path, required=True)
    lcmp.add_argument("--owner", required=True)
    lcmp.add_argument("--run-a", required=True)
    lcmp.add_argument("--run-b", required=True)
    pipe = sub.add_parser("selo-pipeline-stats", help="OTel pipeline stats with loss accounting")
    pipe.add_argument("--state-root", type=Path, required=True)
    pipe.add_argument("--owner", required=True)
    sub.add_parser("local-use", help="print the open local-use policy; it never blocks local use")
    sub.add_parser("support-bundle", help="print a redacted support bundle with no secrets")
    sub.add_parser("production-contract", help="print the Flint audit contract; it admits no effect")
    diagnose = sub.add_parser("diagnose-installer", help="report license and docs missing from an installer script")
    diagnose.add_argument("--installer", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "local-use":
            from .local_use_policy import LocalUsePolicy
            print(json.dumps(LocalUsePolicy().to_dict(), sort_keys=True, ensure_ascii=False))
            return 0
        if args.action == "support-bundle":
            from .local_use_policy import support_bundle
            print(json.dumps(support_bundle(), sort_keys=True, ensure_ascii=False))
            return 0
        if args.action == "production-contract":
            from .production_audit import production_contract
            print(json.dumps(production_contract(), sort_keys=True, ensure_ascii=False))
            return 0
        if args.action == "diagnose-installer":
            from sentra_version import PRODUCT_VERSION
            from .distribution_diagnosis import diagnose_installer
            print(json.dumps(
                diagnose_installer(args.installer, product_version=PRODUCT_VERSION),
                sort_keys=True, ensure_ascii=False,
            ))
            return 0
        if args.action == "selo-diagnostics":
            from .diagnostics import DiagnosticsReport
            print(json.dumps(DiagnosticsReport(args.state_root).build(args.owner),
                             sort_keys=True, ensure_ascii=False))
            return 0
        if args.action == "selo-telemetry-stats":
            from .otel_langfuse import SeloTelemetryExporter
            print(json.dumps(SeloTelemetryExporter(args.state_root).stats(args.owner),
                             sort_keys=True))
            return 0
        if args.action == "selo-release-verify":
            from .release_gate import ReleaseGateError, verify_release
            outcome = verify_release(
                third_party_root=args.root, trusted_pins=args.trusted_pins,
                sbom=args.sbom, expected_sbom_sha256=args.sbom_sha256,
                scan_receipt=args.receipt, fail_at=args.fail_at,
                database_built=args.database_built,
                max_database_age_hours=args.max_db_age_hours,
                previous_receipt=args.previous_receipt)
            print(json.dumps({"ok": outcome["approved"], **outcome}, sort_keys=True,
                             ensure_ascii=False))
            return 0 if outcome["approved"] else 3
        if args.action == "selo-learning-propose":
            from .learning_review import ReviewedLearningStore
            store = ReviewedLearningStore(args.state_root)
            outcome = store.propose(
                args.owner, workspace_id=args.workspace,
                origin=json.loads(args.origin.read_text(encoding="utf-8")),
                scope=json.loads(args.scope.read_text(encoding="utf-8")),
                result=json.loads(args.result.read_text(encoding="utf-8")),
                transcript=args.transcript.read_text(encoding="utf-8"),
                ttl_s=args.ttl)
            print(json.dumps({"ok": True, **outcome}, sort_keys=True))
            return 0
        if args.action == "selo-learning-review":
            from .learning_review import ReviewedLearningStore
            item = ReviewedLearningStore(args.state_root).review(
                args.owner, args.suggestion_id, verdict=args.verdict,
                reviewer=args.reviewer, reason=args.reason)
            print(json.dumps({"ok": True, "suggestion_id": item["suggestion_id"],
                              "status": item["status"],
                              "revision": item["revision"]}, sort_keys=True))
            return 0
        if args.action == "selo-learning-skill":
            from .learning_review import ReviewedLearningStore
            bundle = ReviewedLearningStore(args.state_root).review_bundle(
                args.owner, args.suggestion_id)
            print(json.dumps({"ok": True, **bundle}, sort_keys=True,
                             ensure_ascii=False))
            return 0
        if args.action == "selo-eval-compare":
            from .langfuse_eval import LangfuseEvalStore
            result = LangfuseEvalStore(args.state_root).compare_runs(
                args.owner, run_a=args.run_a, run_b=args.run_b)
            print(json.dumps({"ok": True, **result}, sort_keys=True,
                             ensure_ascii=False))
            return 0
        if args.action == "selo-pipeline-stats":
            from .otel_langfuse import OTelPipeline
            print(json.dumps({"ok": True,
                              **OTelPipeline(args.state_root).stats(args.owner)},
                             sort_keys=True))
            return 0
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
        try:
            from .release_gate import ReleaseGateError
            if isinstance(exc, ReleaseGateError):
                print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
                return 2
        except ImportError:
            pass
        # Never include source file contents, tokens or remote subprocess output.
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
