"""PlaywrightProvider — AgentProvider via Playwright/CDP (Edge persistente).

Papel na arquitetura: protótipo, E2E e testes (inclusive da própria extensão).
Uso normal/live: BrowserExtensionProvider (extension_provider.py).
"""
from __future__ import annotations

from .browser_provider import BrowserProvider


class PlaywrightProvider(BrowserProvider):
    """Nome canônico do provider Playwright. Implementação em browser_provider.py."""
