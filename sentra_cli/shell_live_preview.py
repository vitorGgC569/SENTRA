"""Ephemeral, untrusted, nonauthoritative preview of native CLI model prose.

Only launched Canvas child processes receive the nonce/path. Bytes in this
preview never confer authority and must never be interpreted as tool calls.
"""
from __future__ import annotations
import json
import os

class LivePreviewWriter:
    def __init__(self):
        self.path = os.environ.get("SENTRA_SHELL_PREVIEW_PATH", "")
        self.nonce = os.environ.get("SENTRA_SHELL_PREVIEW_NONCE", "")
        self.sent = 0
        if not self.path or len(self.nonce) != 32:
            self.path = ""

    def activity(self, phase: str, operation: str = "") -> None:
        if not self.path or phase not in {"tool_call", "tool_result", "provider_submitted", "response_complete"}:
            return
        # Tool arguments, paths, results and Grants never enter the preview.
        safe = "".join(c for c in str(operation)[:48] if c.isascii() and
                       (c.isalnum() or c == "_"))
        row = json.dumps({"nonce": self.nonce, "kind": "activity",
                          "phase": phase, "tool": safe}, separators=(",", ":"))
        try:
            with open(self.path, "a", encoding="utf-8", newline="\n") as stream:
                stream.write(row + "\n")
        except OSError:
            self.path = ""

    def send(self, fragment: str) -> None:
        if not self.path or not isinstance(fragment, str) or self.sent >= 64000:
            return
        fragment = fragment[:min(4096, 64000 - self.sent)]
        if not fragment:
            return
        self.sent += len(fragment)
        row = json.dumps({"nonce": self.nonce, "kind": "delta", "text": fragment},
                         ensure_ascii=False, separators=(",", ":"))
        try:
            with open(self.path, "a", encoding="utf-8", newline="\n") as stream:
                stream.write(row + "\n")
        except OSError:
            # Preview must never interfere with the authoritative journal.
            self.path = ""
