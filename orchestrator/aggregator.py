from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class Aggregator:
    @staticmethod
    def _extract_patch(content: str) -> str:
        """
        Extracts a unified diff from free-form LLM output. Real-world responses
        don't always wrap the diff in a ```diff fence as requested, so this tries
        progressively looser strategies before giving up.
        """
        # 1) Explicit ```diff fenced block
        match = re.search(r"```diff\s*\n(.*?)\n```", content, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 2) Any fenced code block that looks like a diff
        for match in re.finditer(r"```[a-zA-Z]*\s*\n(.*?)\n```", content, re.DOTALL):
            candidate = match.group(1)
            if "--- " in candidate and "+++ " in candidate:
                return candidate.strip()

        # 3) No code fence at all: take everything after PATCH: up to the next
        # ALL_CAPS section header, optionally skipping a bare "diff"/"Diff" label.
        match = re.search(
            r"PATCH:\s*\n(?:[ \t]*[Dd]iff[ \t]*\n)?(.*?)(?=\n[A-Z_]+:\s*\n|\Z)",
            content,
            re.DOTALL,
        )
        if match:
            candidate = match.group(1).strip()
            if "--- " in candidate and "+++ " in candidate:
                return candidate

        return ""

    @staticmethod
    def parse_structured_result(raw_text: str) -> Dict[str, Any]:
        """
        Parses structured outputs formatted between BEGIN_RESULT and END_RESULT.
        Extracts STATUS, SUMMARY, PATCH, VALIDATION_COMMANDS, etc.
        """
        parsed: Dict[str, Any] = {
            "status": "UNKNOWN",
            "summary": "",
            "patch": "",
            "raw_text": raw_text,
            "validation_commands": [],
            "issues": [],
        }

        # Check for result boundaries or extract text as best as possible
        content = raw_text
        if "BEGIN_RESULT" in raw_text:
            content = raw_text.split("BEGIN_RESULT")[-1]
        if "END_RESULT" in content:
            content = content.split("END_RESULT")[0]

        # Extract STATUS
        status_match = re.search(r"STATUS:\s*([A-Z_]+)", content, re.IGNORECASE)
        if status_match:
            parsed["status"] = status_match.group(1).upper()

        # Extract SUMMARY
        summary_match = re.search(r"SUMMARY:\s*(.*?)(?=\n[A-Z_]+:|\Z)", content, re.DOTALL)
        if summary_match:
            parsed["summary"] = summary_match.group(1).strip()

        # Extract PATCH block
        parsed["patch"] = Aggregator._extract_patch(content)

        # Extract VALIDATION_COMMANDS
        val_match = re.search(r"VALIDATION_COMMANDS:\s*(.*?)(?=\n[A-Z_]+:|\Z)", content, re.DOTALL)
        if val_match:
            cmds = [line.strip("- ").strip() for line in val_match.group(1).splitlines() if line.strip()]
            parsed["validation_commands"] = cmds

        return parsed

    @staticmethod
    def aggregate_session_results(raw_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        for item in raw_results:
            role = item.get("role", "unknown")
            task_id = item.get("task_id", "")
            raw = item.get("raw_response", "")

            parsed = Aggregator.parse_structured_result(raw)
            parsed["role"] = role
            parsed["task_id"] = task_id
            normalized.append(parsed)

        return normalized
