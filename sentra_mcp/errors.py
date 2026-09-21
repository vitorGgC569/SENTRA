"""Public error handling and secret redaction."""
from __future__ import annotations

import re

from .models import ResponseEnvelope

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)"),
    re.compile(
        r"(?i)\b(api[-_ ]?key|token|password|secret|client_secret)"
        r"(\s*[:=]\s*)([^\s,;]+)"
    ),
    re.compile(r"\b(?:sk[-_]|ghp_|github_pat_)[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"(://[^\s:/]+:)([^\s/@]+)(@)"),
)


class ConfigurationError(ValueError):
    """Raised when MCP configuration violates a security invariant."""


def sanitize_error(error: BaseException | str, *, max_length: int = 1000) -> str:
    """Return a bounded, single-line error string with common secrets removed."""

    text = str(error).replace("\r", " ").replace("\n", " ")
    text = _SECRET_PATTERNS[0].sub(r"\1[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub(r"\1\2[REDACTED]", text)
    text = _SECRET_PATTERNS[2].sub("[REDACTED]", text)
    text = _SECRET_PATTERNS[3].sub(r"\1[REDACTED]\3", text)
    if len(text) > max_length:
        text = text[: max_length - 3] + "..."
    return text


def error_envelope(error: BaseException | str, *, code: str = "internal_error") -> ResponseEnvelope:
    """Convert an exception into the public stable envelope without leaking secrets."""

    return ResponseEnvelope.failure(code=code, message=sanitize_error(error))
