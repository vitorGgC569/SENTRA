"""Selo: benchmark quality gate (deterministic aggregation + provenance).

Wraps DatasetEvaluationSuite reports with cost attribution, policy context
and source/Grype provenance. Never invents scores: verdicts come only from
independent verifier evidence in each report. Aggregation is read-only math
over actually-scored independent evaluations.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class BenchmarkSeloGate:
    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        self.root = Path(state_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock

    def acceptance_from_artifacts(self, *, control, owner, manifest_artifact_id,
                                  expected_manifest_sha256, report_artifact_id):
        """Final-stage gate over retained receipts, not caller-reported scores.

        This consumes an AcceptanceRunner report and an operator-pinned manifest.
        It never launches a fixture, agent, evaluator, scanner or build helper.
        The manifest binds cases, environment/reset/mode and verifier capability.
        """
        from sentra_runtime.central_authority import CentralDurableIntentAuthority
        manifest_info = control.durable.artifact_info(manifest_artifact_id, owner)
        report_info = control.durable.artifact_info(report_artifact_id, owner)
        if manifest_info["sha256"] != expected_manifest_sha256 or report_info["run_id"] != manifest_info["run_id"]:
            raise PermissionError("benchmark manifest/report authority binding mismatch")
        def document(artifact_id):
            info = control.durable.artifact_info(artifact_id, owner)
            raw = control.durable.read_artifact(artifact_id, max_bytes=2_000_000)
            if info["metadata"].get("os_protected") is True:
                from sentra_remote.secrets import unprotect_secret
                raw = unprotect_secret(raw.decode()).encode()
            if len(raw) > 2_000_000: raise ValueError("benchmark artifact decoded bound exceeded")
            return json.loads(raw)
        manifest, report = document(manifest_artifact_id), document(report_artifact_id)
        if manifest.get("schema") != "sentra.selo.benchmark-acceptance/v1" or report.get("run_id") != report_info["run_id"]:
            raise ValueError("versioned benchmark acceptance manifest required")
        expected = {item["case_id"]: item for item in manifest["cases"]}
        if not 1 <= len(expected) <= 100 or len(expected) != len(manifest["cases"]):
            raise ValueError("unique bounded acceptance cases required")
        cases = report["cases"]
        if len(cases) != len(expected) or {c["case_id"] for c in cases} != set(expected):
            raise PermissionError("missing/extra benchmark acceptance cases")
        authority = CentralDurableIntentAuthority(control.durable)
        accepted = []
        for case in cases:
            pin = expected[case["case_id"]]
            for field in ("environment_version", "reset_snapshot_id", "observation_mode"):
                if case.get(field) != pin[field]: raise PermissionError("benchmark fixture/mode/version mismatch")
            trajectory = case["trajectory"]
            if not trajectory or trajectory[0]["phase"] != "reset": raise PermissionError("benchmark reset receipt absent")
            verifier = None
            for step in trajectory:
                operation = control.durable.operation_status(step["operation_id"], owner)
                if operation["run_id"] != report["run_id"] or operation["state"] != "SUCCEEDED":
                    raise PermissionError("benchmark trajectory lacks completed central receipt")
                receipt = authority.receipt_for_operation(step["operation_id"], owner)
                result = authority.result_for_receipt(receipt)
                if result is None: raise PermissionError("benchmark retained evidence unavailable")
                if step["phase"] == "reset" and result.evidence.get("snapshot_id") != pin["reset_snapshot_id"]:
                    raise PermissionError("actual reset snapshot differs from manifest")
                if step["phase"] == "verify":
                    if operation["progress"].get("capability_id") != pin["verifier_capability_id"]:
                        raise PermissionError("independent verifier capability mismatch")
                    if operation["progress"].get("machine_id") != pin["verifier_machine_id"]:
                        raise PermissionError("independent verifier machine differs from pinned manifest")
                    verifier = dict(result.evidence)
            if (verifier is None or verifier != case["verifier"] or verifier.get("deterministic") is not True
                    or verifier.get("executor_success_used_as_score") is not False
                    or not verifier.get("criteria") or verifier.get("state") not in {"PASS", "FAIL"}):
                raise PermissionError("independent verifier receipt mismatch/unavailable")
            score = verifier.get("score")
            if type(score) not in {int, float} or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("invalid verified benchmark score")
            minimum = pin.get("minimum_score", 1)
            if type(minimum) not in {int, float} or not math.isfinite(minimum) or not 0 <= minimum <= 1:
                raise ValueError("invalid pinned acceptance score threshold")
            accepted.append({"case_id": case["case_id"], "score": score,
                "passed": score >= minimum,
                "latency_ms": case["latency_ms"], "verifier_sha256": hashlib.sha256(_canonical(verifier).encode()).hexdigest()})
        cost = control.cost_summary(owner, run_id=report["run_id"])
        limit = manifest["max_actual_cost"]
        if type(limit) not in {int, float} or not math.isfinite(limit) or limit < 0:
            raise ValueError("explicit finite acceptance cost bound required")
        return {"allowed": all(item["passed"] for item in accepted) and cost["actual"] <= limit,
            "cases": accepted, "cost": cost, "manifest_sha256": expected_manifest_sha256,
            "report_sha256": report_info["sha256"], "creates_grants": False,
            "authority": "retained-central-independent-verifier-receipts", "runtime_validated_by_this_gate": False}

    @staticmethod
    def aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(reports, list) or len(reports) > 20000:
            raise ValueError("benchmark report list out of bounds")
        evaluated = [
            r for r in reports
            if r.get("evaluated") is True and type(r.get("score")) in (int, float)
            and math.isfinite(r["score"]) and 0 <= r["score"] <= 1
        ]
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for report in reports:
            source = report.get("source", report.get("task", {})) or {}
            key = (str(source.get("dataset", "unknown")), str(source.get("category", "unknown")))
            group = groups.setdefault(key, {"dataset": key[0], "category": key[1],
                                            "total": 0, "evaluated": 0, "unsupported": 0,
                                            "scores": [], "latencies": []})
            group["total"] += 1
            if report.get("state") == "UNSUPPORTED" or report.get("supported") is False:
                group["unsupported"] += 1
            if report in evaluated:
                group["evaluated"] += 1
                group["scores"].append(report["score"])
                group["latencies"].append(report.get("latency_ms", 0))
        for group in groups.values():
            group["mean_score"] = (sum(group["scores"]) / len(group["scores"])
                                   if group["scores"] else None)
            group["mean_latency_ms"] = (sum(group["latencies"]) / len(group["latencies"])
                                        if group["latencies"] else None)
            del group["scores"]
            del group["latencies"]
        return {
            "total": len(reports),
            "evaluated": len(evaluated),
            "unsupported": sum(1 for r in reports
                               if r.get("state") == "UNSUPPORTED" or r.get("supported") is False),
            "mean_score": (sum(r["score"] for r in evaluated) / len(evaluated)
                           if evaluated else None),
            "success_rate": (sum(1 for r in evaluated if r["score"] == 1) / len(evaluated)
                             if evaluated else None),
            "denominator": "actually_scored_independent_evaluations_only",
            "groups": list(groups.values()),
        }

    def seal(self, owner: str, reports: list[dict[str, Any]], *,
             policy_context: dict[str, Any] | None = None,
             provenance: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("owner is required")
        summary = self.aggregate(reports)
        envelope = {
            "owner": owner,
            "created_at": self.clock(),
            "summary": summary,
            "policy_context": dict(policy_context or {}),
            "provenance": dict(provenance or {}),
            "reports_sha256": hashlib.sha256(_canonical(reports).encode()).hexdigest(),
        }
        envelope["seal_sha256"] = hashlib.sha256(_canonical(envelope).encode()).hexdigest()
        return envelope
