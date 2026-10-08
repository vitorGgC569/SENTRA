"""GeminiWebProvider — Gemini web through the durable principal-Edge relay."""
from __future__ import annotations

from .extension_provider import BrowserExtensionProvider


class GeminiWebProvider(BrowserExtensionProvider):
    """Use Gemini Web (Flash-Lite, Flash or Pro) through the existing Edge controller."""

    def __init__(
        self,
        relay_base: str = "http://127.0.0.1:8765",
        *,
        web_model: str = "flash",
        token: str | None = None,
    ) -> None:
        normalized = str(web_model or "flash").strip().lower()
        super().__init__(
            relay_base=relay_base,
            model_name=f"gemini-web/{normalized}",
            token=token,
            provider="gemini",
            web_model=normalized,
        )
