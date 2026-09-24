"""Bounded, failure-focused test output for model repair feedback."""
from __future__ import annotations

import re
from typing import Any

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
