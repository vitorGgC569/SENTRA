"""Read-only analysis of OBSERVED critic scores; never script the live trajectory."""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def analyze(run_dir, required_model="gpt-5.6-sol"):
    root = Path(run_dir).resolve(strict=True)
    events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    responses = [e.get("payload", {}) for e in events if e.get("event_type") == "MODEL_RESPONSE"]
    reports = json.loads((root / "validations.json").read_text(encoding="utf-8"))
    rounds = {}
    for report in reports:
        key = report["candidate_id"]
        entry = rounds.setdefault(key, {"candidate_id": key, "scores": [], "findings": [], "verified_model": True})
        score = report.get("score")
        if not report.get("ran", True) or type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 10:
            entry["verified_model"] = False
            continue
        matching = [r for r in responses if r.get("candidate_id") == key
                    and r.get("role") == report["validator_role"] and r.get("success")]
        identity = matching[-1].get("conversation", {}).get("model_identity", {}) if matching else {}
        if (identity.get("source") != "openai_response" or identity.get("observed") != required_model
                or identity.get("requested") != required_model or not identity.get("response_id")):
            entry["verified_model"] = False
        entry["scores"].append({"role": report["validator_role"], "score": score, "status": report["status"]})
        entry["findings"].extend(f.get("description", "") for f in report.get("findings", []))
    observed = list(rounds.values())
    for entry in observed:
        entry["min_score"] = min((s["score"] for s in entry["scores"]), default=None)
    valid = bool(observed) and all(e["verified_model"] and e["scores"] for e in observed)
    return {"status": "OBSERVED_LIVE_SCORES" if valid else "MODEL_OR_SCORE_EVIDENCE_MISSING",
            "required_model": required_model, "rounds": observed,
            "claim": "Observed scores are not proof of quality. 8→9→9.6 is a test scenario, not a live target."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--required-model", default="gpt-5.6-sol")
    args = parser.parse_args()
    print(json.dumps(analyze(args.run_dir, args.required_model), ensure_ascii=False, indent=2))
