"""Bounded, failure-focused test output for model repair feedback."""
from __future__ import annotations

import re
from typing import Any, Optional

_MARKERS = re.compile(
    r"(Traceback|AssertionError|FAILED|ERROR|E\s{2,}|SyntaxError|"
    r"TypeError|ValueError|ImportError|ModuleNotFoundError|"
    r"expected|actual|assert\b|short test summary info)",
    re.IGNORECASE,
)


def summarize_failure_text(text: str, *, max_chars: int = 6000) -> str:
    """Keep the actionable failure neighborhood instead of arbitrary log tails."""
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if len(value) <= max_chars:
        return value
    lines = value.splitlines()
    interesting = [i for i, line in enumerate(lines) if _MARKERS.search(line)]
    selected: set[int] = set()
    for index in interesting[-20:]:
        selected.update(range(max(0, index - 4), min(len(lines), index + 7)))
    if not selected:
        head = lines[:20]
        tail = lines[-60:]
        compact = "\n".join(head + ["... [SENTRA log truncated] ..."] + tail)
        return compact[-max_chars:]
    chunks: list[str] = []
    last = None
    for index in sorted(selected):
        if last is not None and index > last + 1:
            chunks.append("... [SENTRA unrelated log omitted] ...")
        chunks.append(lines[index])
        last = index
    result = "\n".join(chunks)
    if len(result) > max_chars:
        result = result[-max_chars:]
    return result


def summarize_test_results(
    evidence: dict[str, Any],
    *,
    max_result_chars: int = 6000,
    max_results: int = 8,
) -> dict[str, Any]:
    """Return deterministic bounded repair evidence preserving failing assertions."""
    summary: dict[str, Any] = {
        "all_passed": bool(evidence.get("all_passed")),
        "failed_commands": list(evidence.get("failed_commands") or []),
        "refused_commands": list(evidence.get("refused_commands") or []),
        "parse_error": evidence.get("parse_error") or "",
        "dry_run": evidence.get("dry_run") or {},
        "version_check": evidence.get("version_check") or {},
        "failures": [],
    }
    results = evidence.get("results") or evidence.get("all_results") or []
    failures = [
        item for item in results
        if isinstance(item, dict) and not item.get("passed", False)
        and not item.get("refused", False)
    ]
    for item in failures[:max_results]:
        stdout = summarize_failure_text(
            str(item.get("stdout") or ""), max_chars=max_result_chars // 2
        )
        stderr = summarize_failure_text(
            str(item.get("stderr") or ""), max_chars=max_result_chars
        )
        summary["failures"].append({
            "command": item.get("command"),
            "exit_code": item.get("returncode", item.get("exit_code")),
            "timed_out": bool(item.get("timed_out", False)),
            "stdout": stdout,
            "stderr": stderr,
        })
    summary["omitted_failure_count"] = max(0, len(failures) - max_results)
    return summary


def summarize_incident(report: dict[str, Any], *, max_items: int = 20) -> dict[str, Any]:
    """Keep recovery dispositions. Drop prompts, paths, secrets and command text."""
    if not isinstance(report, dict):
        raise ValueError("incident report must be an object")
    if type(max_items) is not int or not 1 <= max_items <= 100:
        raise ValueError("max_items must be 1..100")
    raw_items = report.get("items") or []
    if not isinstance(raw_items, list):
        raise ValueError("incident items must be a list")
    items = []
    for item in raw_items[:max_items]:
        if not isinstance(item, dict):
            continue
        items.append({
            "kind": item.get("kind"),
            "id": item.get("id"),
            "state": item.get("state"),
            "disposition": item.get("disposition"),
            "may_resend": False,
        })
    return {
        "incident": report.get("incident"),
        "effects_executed": 0,
        "may_resend": False,
        "automatic_retry": False,
        "items": items,
        "omitted_item_count": max(0, len(raw_items) - max_items),
    }


_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_STATUS = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


class GateAuditRefusal(ValueError):
    """The gate observation was not emitted. Missing proof is not a pass."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def accepted_identifier(value: Any) -> Optional[str]:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        return None
    return value


def accepted_status(value: Any) -> Optional[str]:
    if not isinstance(value, str) or _STATUS.fullmatch(value) is None:
        return None
    return value


def accepted_evidence_ids(values: Any) -> list[str]:
    """Keep identifier-shaped ids. A string, path, or secret is not evidence."""
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ValueError("evidence_ids must be a list")
    accepted: list[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        kept = accepted_identifier(item.strip())
        if kept is not None:
            accepted.append(kept)
    return list(dict.fromkeys(accepted))


def bound_gate_audit(observation: dict[str, Any]) -> dict[str, Any]:
    """Allowlisted gate body. Approval without evidence is refused.

    Unknown keys (prompts, paths, secrets, commands, grants) are dropped.
    The result does not authorize a promotion.
    """
    if not isinstance(observation, dict):
        raise ValueError("gate observation must be an object")
    if observation.get("authorizes_effect") is not False:
        raise GateAuditRefusal("gate observation cannot authorize an effect", code="effect")
    if observation.get("grant_id") not in (None, ""):
        raise GateAuditRefusal("gate observation cannot carry a grant", code="grant")
    passed = observation.get("passed")
    if type(passed) is not bool:
        raise ValueError("passed must be a boolean")
    reason = observation.get("reason")
    if not isinstance(reason, str):
        raise ValueError("reason must be text")
    text = "".join(
        ch for ch in reason.replace("\r", " ").replace("\n", " ")
        if ch.isprintable()
    )[:500]
    evidence_ids = accepted_evidence_ids(observation.get("evidence_ids") or [])
    if passed and not evidence_ids:
        raise GateAuditRefusal("approved gate requires evidence", code="evidence")
    return {
        "passed": passed,
        "reason": text,
        "candidate_id": accepted_identifier(observation.get("candidate_id")),
        "status": accepted_status(observation.get("status")),
        "evidence_ids": evidence_ids,
        "authorizes_effect": False,
        "promotion": False,
        "effects_executed": 0,
        "may_resend": False,
    }
