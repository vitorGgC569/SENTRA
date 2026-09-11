from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


class PatchManager:
    @staticmethod
    def parse_patch_hunks(diff_str: str) -> List[Tuple[str, List[str]]]:
        """
        Parses unified diff into target relative file paths and patch line groups.
        """
        file_patches: List[Tuple[str, List[str]]] = []
        current_file: str | None = None
        current_lines: List[str] = []

        for line in diff_str.splitlines():
            if line.startswith("--- "):
                # File header line (old side). Never part of a file's hunk body.
                continue
            if line.startswith("+++ "):
                if current_file and current_lines:
                    file_patches.append((current_file, current_lines))
                current_file = line[6:].split("\t")[0].strip()
                current_lines = []
                continue
            if current_file:
                current_lines.append(line)

        if current_file and current_lines:
            file_patches.append((current_file, current_lines))

        return file_patches

    @staticmethod
    def _apply_hunks(existing_content: List[str], hunk_lines: List[str]) -> List[str]:
        """
        Applies unified diff hunk lines onto existing file lines, honoring the
        position of each hunk (via its @@ header) and each line's context/add/
        remove role, instead of blindly appending/removing by value.
        """
        result: List[str] = []
        old_idx = 0

        for line in hunk_lines:
            if line.startswith("@@"):
                match = re.search(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", line)
                if match:
                    target_old_start = min(int(match.group(1)) - 1, len(existing_content))
                    target_old_start = max(target_old_start, old_idx)
                    while old_idx < target_old_start:
                        result.append(existing_content[old_idx])
                        old_idx += 1
                continue

            if line.startswith("-") and not line.startswith("---"):
                # Removed line: skip it from the old file, don't emit it.
                old_idx += 1
            elif line.startswith("+") and not line.startswith("+++"):
                # Added line: emit as-is, doesn't consume from the old file.
                result.append(line[1:])
            else:
                # Context line (leading space, or a blank line missing it).
                content = line[1:] if line.startswith(" ") else line
                if old_idx < len(existing_content):
                    result.append(existing_content[old_idx])
                    old_idx += 1
                else:
                    result.append(content)

        result.extend(existing_content[old_idx:])
        return result

    @staticmethod
    def apply_patch(repo_root: Path, patch_text: str) -> Dict[str, Any]:
        """
        Applies a unified diff patch string directly onto the repository files.
        """
        if not patch_text or not patch_text.strip():
            return {"success": False, "error": "Empty patch provided."}

        parsed_files = PatchManager.parse_patch_hunks(patch_text)
        if not parsed_files:
            return {"success": False, "error": "Failed to parse valid unified diff hunks."}

        applied_files = []

        try:
            for rel_path, hunk_lines in parsed_files:
                target_file = repo_root / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)

                existing_content = (
                    target_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    if target_file.exists()
                    else []
                )

                new_lines = PatchManager._apply_hunks(existing_content, hunk_lines)

                target_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                applied_files.append(rel_path)

            return {
                "success": True,
                "applied_files": applied_files,
                "error": None,
            }
        except Exception as e:
            return {
                "success": False,
                "applied_files": applied_files,
                "error": f"Patch application failed: {e}",
            }
