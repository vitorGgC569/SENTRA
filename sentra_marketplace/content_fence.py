"""External bytes are data. They never replace a superior instruction."""
from __future__ import annotations

import hashlib
import re

MAX_CONTENT_BYTES = 256 * 1024

_OVERRIDES = (
    "ignore previous instructions",
    "ignore all previous",
    "ignore prior instructions",
    "you are now authorized",
    "grant yourself",
    "concede grant",
    "conceder grant",
    "</system>",
    "[[grant",
)


def fence_external_content(text: str) -> dict:
    """Wrap text as data. Override attempts are recorded and not applied."""
    if type(text) is not str:
        raise ValueError("external content must be text")
    raw = text.encode("utf-8")
    if len(raw) > MAX_CONTENT_BYTES:
        raise ValueError("CONTENT_UNBOUNDED")
    folded = text.casefold()
    override = any(marker in folded for marker in _OVERRIDES)
    return {
        "role": "data",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "text": text,
        "instruction_authority": False,
        "override_attempt": override,
    }


def superior_digest(instruction: str) -> str:
    if type(instruction) is not str or not instruction.strip() or len(instruction) > 4000:
        raise ValueError("superior instruction required")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", instruction):
        raise ValueError("superior instruction contains control characters")
    return hashlib.sha256(instruction.encode("utf-8")).hexdigest()
