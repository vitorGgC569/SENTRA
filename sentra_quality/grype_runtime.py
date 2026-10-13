"""Host-configured pinned Grype scan and digest-bound release composition.

No scanner/build/benchmark runs at import/configuration. Only admitted dispatch
may invoke the existing real scanner. Inputs are operator-configured paths.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from .grype_scan import GrypeScanConfig, scan_sbom, scan_diff
from .grype_gate import evaluate_grype_json
from .release_gate import check_database_freshness, fix_advice, ReleaseGateError
from .source_gate import SourceGate
from .audit_state import ProtectedAuditDeliveryStore
from .protected_state import digest


class GrypeRuntime:
    def __init__(self, state, config):
        self.state, self.config = state.scoped("selo.grype"), config
        self.artifacts = ProtectedAuditDeliveryStore(state)

    def dispatch(self, action, args, *, context):
        if action == "scan":
            if args: raise ValueError("scanner inputs come only from trusted host configuration")
            context.checkpoint()
            receipt = scan_sbom(GrypeScanConfig(**self.config["scan"]), Path(self.config["sbom"]),
                expected_sbom_sha256=self.config["expected_sbom_sha256"], fail_at=self.config.get("fail_at", "high"))
            context.checkpoint()
            raw = receipt.pop("report")
            reference = self.artifacts.proof_blob(raw)
            if reference["sha256"] != receipt["decision"]["report_sha256"]:
                raise ReleaseGateError("scanner report digest binding mismatch")
            receipt.update(report_artifact=reference, operation_id=context.receipt.operation_id,
                           configuration_sha256=digest(self.config))
            receipt_id = "scan-" + digest([context.receipt.operation_id, reference["sha256"]])[:40]
            self.state.put(receipt_id, receipt)
            return {"receipt_id": receipt_id, **receipt, "package_release_approved": False}
        if action == "diff":
            return scan_diff(self._receipt(args["previous_receipt_id"]), self._receipt(args["receipt_id"]))
        receipt = self._receipt(args["receipt_id"])
        if action == "report":
            return {"artifact": receipt["report_artifact"], "receipt_id": args["receipt_id"],
                    "report_sha256": receipt["decision"]["report_sha256"]}
        if action != "release_gate": raise ValueError("unknown Grype runtime action")
        context.checkpoint()
        sources = SourceGate(Path(self.config["third_party_root"]),
                             trusted_pins=Path(self.config["trusted_pins"])).verify_all()
        context.checkpoint()
        sbom = Path(self.config["sbom"])
        if not sbom.is_file() or sbom.stat().st_size > 32_000_000:
            raise ReleaseGateError("release SBOM unavailable/oversized")
        raw_sbom = sbom.read_bytes()
        expected = self.config["expected_sbom_sha256"]
        if hashlib.sha256(raw_sbom).hexdigest() != expected or receipt["sbom_sha256"] != expected:
            raise ReleaseGateError("source/SBOM/receipt binding mismatch")
        document = json.loads(raw_sbom)
        if not isinstance(document, dict) or not (document.get("bomFormat") == "CycloneDX" or document.get("spdxVersion")):
            raise ReleaseGateError("supported Syft SPDX/CycloneDX inventory required")
        report = self.artifacts.read_blob(receipt["report_artifact"])
        decision = evaluate_grype_json(report, fail_at=self.config.get("fail_at", "high"),
                                      expected_sha256=receipt["decision"]["report_sha256"], max_bytes=32_000_000)
        native = json.loads(report)
        if native.get("ignoredMatches"):
            raise ReleaseGateError("ignored vulnerabilities cannot pass release gate")
        freshness = check_database_freshness(receipt["database_built"],
            max_age_hours=self.config["scan"].get("max_database_age_hours", 120))
        if not decision.allowed or not freshness["fresh"]:
            raise ReleaseGateError("vulnerability threshold or database freshness rejected release")
        return {"allowed": True, "source_pins_verified": len(sources), "sbom_sha256": expected,
            "report_sha256": decision.report_sha256, "scanner_sha256": receipt["scanner_sha256"],
            "database": freshness, "recommendations": receipt["recommendations"],
            "scan_receipt_id": args["receipt_id"], "artifact": receipt["report_artifact"],
            "signed_release": False, "clean_install_verified": False}

    def _receipt(self, key):
        if not isinstance(key, str) or not key.startswith("scan-"):
            raise ValueError("scoped scan receipt required")
        row = self.state.get(key)
        if row is None: raise FileNotFoundError("scanner receipt unavailable")
        if row["value"]["configuration_sha256"] != digest(self.config):
            raise ReleaseGateError("scanner receipt does not match current pinned profile")
        return row["value"]
