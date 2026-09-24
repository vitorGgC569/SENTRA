"""Public error handling and secret redaction."""
from __future__ import annotations

import re

from .models import ResponseEnvelope

_SENSITIVE_DETAIL_KEY = re.compile(
    r"(?i)(?:api[-_ ]?key|token|password|secret|cookie|authorization)"
)

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


class SentraSemanticError(RuntimeError):
    """Stable agent-facing error with optional low-level diagnostic detail."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        category: str = "runtime",
        retryable: bool = False,
        operation_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.retryable = retryable
        self.operation_id = operation_id
        self.details = dict(details or {})


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


def _sanitize_detail(value, *, depth: int = 0):
    if depth >= 5:
        return sanitize_error(value, max_length=500)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_error(value, max_length=1000)
    if isinstance(value, dict):
        clean = {}
        for key, child in list(value.items())[:100]:
            safe_key = sanitize_error(str(key), max_length=120)
            clean[safe_key] = (
                "[REDACTED]"
                if _SENSITIVE_DETAIL_KEY.search(str(key))
                else _sanitize_detail(child, depth=depth + 1)
            )
        return clean
    if isinstance(value, (list, tuple)):
        return [_sanitize_detail(child, depth=depth + 1) for child in list(value)[:100]]
    return sanitize_error(value, max_length=500)


def error_envelope(error: BaseException | str, *, code: str = "internal_error") -> ResponseEnvelope:
    """Convert an exception into the public stable envelope without leaking secrets."""

    if isinstance(error, SentraSemanticError):
        details = _sanitize_detail(error.details)
        return ResponseEnvelope.failure(
            error.code,
            sanitize_error(error),
            category=error.category,
            retryable=error.retryable,
            operation_id=error.operation_id,
            details=details or None,
        )
    return ResponseEnvelope.failure(code=code, message=sanitize_error(error))
