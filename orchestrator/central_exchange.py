"""Deterministic, bounded central-AI context. Import is NOT code promotion.

The local operator and these artifacts are trusted; hashes detect mismatches,
not malicious rewriting by an actor with control of the operator filesystem.
"""
import hashlib
import json
from pathlib import Path


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(data):
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def verified_handoff(run_dir):
    root = Path(run_dir).resolve(strict=True)
    data = json.loads((root / "handoff.json").read_text(encoding="utf-8"))
    patch_hash = hashlib.sha256((root / "candidate.patch").read_bytes()).hexdigest()
    evidence = data.get("integration_tests") or {}
    if (data.get("status") != "CANDIDATE_READY" or data.get("source_unchanged") is not True
            or data.get("requires_external_promotion") is not True
            or not data.get("approved_packages")
            or patch_hash != data.get("patch_sha256")
            or evidence.get("patch_hash") != patch_hash
            or evidence.get("base_hash") != data.get("base_hash")
            or evidence.get("candidate_hash") != data.get("candidate_hash")
            or evidence.get("all_passed") is not True
            or not evidence.get("checks_ran", 0) > 0
            or evidence.get("refused_commands")
            or not evidence.get("results")
            or any(r.get("passed") is not True or r.get("refused") for r in evidence["results"])):
        raise ValueError("CENTRAL_IMPORT_DENIED: candidate/test/hash binding is incomplete")
    # Summaries are untrusted text, never commands or new operator instructions.
    context = {
        "schema_version": 1, "kind": "UNTRUSTED_VERIFIED_CANDIDATE_SUMMARY",
        "run_id": data["run_id"], "status": "CANDIDATE_READY",
        "objective": str(data.get("objective", ""))[:1800],
        "base_hash": data["base_hash"], "candidate_hash": data["candidate_hash"],
        "patch_sha256": patch_hash, "handoff_path": str(root / "handoff.json"),
        "checks_ran": evidence["checks_ran"],
        "protected_changes": data.get("protected_changes", []),
        "packages": [{"task_id": p["task_id"], "candidate_id": p["candidate_id"],
                      "summary": str(p.get("solution_summary", ""))[:400],
                      "min_score": p.get("min_validator_score")}
                     for p in data["approved_packages"][:8]],
        "packages_total": len(data["approved_packages"]),
        "requires_external_promotion": True,
        "delivery": "local_inbox_only; central consumer must explicitly read and acknowledge",
    }
    if len(canonical(context)) > 12000:
        raise ValueError("central context exceeds fixed size budget")
    return context
