"""Canonical provider-aware conversation identity.

This module intentionally has no SENTRA service/orchestrator dependencies so it
can be imported by Control Plane, providers, browser adapters and cleanup code.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class ConversationIdentity:
    provider: str
    conversation_id: str

    @property
    def canonical_url(self) -> str:
        if self.provider == "chatgpt":
            return f"https://chatgpt.com/c/{self.conversation_id}"
        if self.provider == "gemini":
            return f"https://gemini.google.com/app/{self.conversation_id}"
        raise ValueError(f"unsupported conversation provider: {self.provider}")

    @classmethod
    def from_parts(
        cls, provider: str, conversation_id: str, conversation_url: str | None = None
    ) -> "ConversationIdentity":
        normalized = str(provider or "").strip().lower()
        cid = str(conversation_id or "").strip()
        if normalized not in {"chatgpt", "gemini"}:
            raise ValueError("conversation provider must be chatgpt or gemini")
        if not cid:
            raise ValueError("conversation_id is required")
        if normalized == "chatgpt":
            import re
            if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", cid):
                raise ValueError("invalid ChatGPT conversation_id")
        else:
            import re
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", cid):
                raise ValueError("invalid Gemini conversation_id")
        identity = cls(normalized, cid)
        if conversation_url is not None and cls.parse(conversation_url) != identity:
            raise ValueError("conversation provider/id/url mismatch")
        return identity

    @classmethod
    def parse(cls, value: str) -> "ConversationIdentity":
        text = str(value or "").strip()
        parsed = urlsplit(text)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("conversation URL must be an absolute credential-free https URL")
        path = parsed.path.rstrip("/")
        parts = [part for part in path.split("/") if part]
        if parsed.hostname == "chatgpt.com" and len(parts) == 2 and parts[0] == "c":
            return cls.from_parts("chatgpt", parts[1])
        if parsed.hostname == "gemini.google.com" and len(parts) == 2 and parts[0] == "app":
            return cls.from_parts("gemini", parts[1])
        raise ValueError("unsupported conversation URL")

    @classmethod
    def maybe_parse(cls, value: object) -> "ConversationIdentity | None":
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return cls.parse(value)
        except ValueError:
            return None

    def matches(
        self,
        *,
        provider: str | None = None,
        conversation_id: str | None = None,
        conversation_url: str | None = None,
    ) -> bool:
        try:
            if provider is not None and str(provider).strip().lower() != self.provider:
                return False
            if conversation_id is not None and str(conversation_id) != self.conversation_id:
                return False
            if conversation_url is not None and self.parse(conversation_url) != self:
                return False
        except ValueError:
            return False
        return True
