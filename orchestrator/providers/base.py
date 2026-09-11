from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol

from ..models import TokenUsage


@dataclass
class AgentRequest:
    system_prompt: str
    user_prompt: str
    temperature: float = 0.1
    timeout: int = 120
    role: str = "general"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    content: str
    structured_data: Optional[Dict[str, Any]] = None
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    latency: float = 0.0
    success: bool = True
    error: Optional[str] = None
    model: str = ""


class AgentProvider(Protocol):
    async def execute(self, request: AgentRequest) -> AgentResponse:
        ...
