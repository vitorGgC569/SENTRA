from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "integrations" / "codex_chatgpt_web" / "sentra-upstream.patch"
MANIFEST = ROOT / "integrations" / "codex_chatgpt_web" / "upstream.json"
UPSTREAM = ROOT / "third_party" / "codex-chatgpt-web"
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _sections(text: str):
    current_path = None
    current_hunks = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git "):
            if current_path is not None:
                yield current_path, current_hunks
            match = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
            assert match and match.group(1) == match.group(2)
            current_path = match.group(2)
            current_hunks = []
            index += 1
            continue
        match = HUNK.match(line)
        if current_path is not None and match:
            old_start = int(match.group(1))
            old_expected = int(match.group(2) or 1)
            new_expected = int(match.group(4) or 1)
            old_lines = []
            old_count = new_count = 0
            index += 1
            while index < len(lines) and not lines[index].startswith(("@@ ", "diff --git ")):
                item = lines[index]
                if item.startswith("\\ No newline"):
                    index += 1
                    continue
                assert item[:1] in {" ", "+", "-"}, f"invalid patch line: {item!r}"
                if item[0] in {" ", "-"}:
                    old_count += 1
                    old_lines.append(item[1:])
                if item[0] in {" ", "+"}:
                    new_count += 1
                index += 1
            assert old_count == old_expected
            assert new_count == new_expected
            current_hunks.append((old_start, old_lines))
            continue
        index += 1
    if current_path is not None:
        yield current_path, current_hunks


def test_sentra_upstream_patch_matches_pinned_checkout_exactly() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sections = list(_sections(PATCH.read_text(encoding="utf-8")))
    assert sorted(path for path, _ in sections) == sorted(manifest["patch_files"])

    for relative, hunks in sections:
        source = (UPSTREAM / relative).read_text(encoding="utf-8").splitlines()
        for old_start, old_lines in hunks:
            actual = source[old_start - 1 : old_start - 1 + len(old_lines)]
            assert actual == old_lines, f"patch drift in {relative} at original line {old_start}"
