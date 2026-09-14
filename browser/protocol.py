"""Protocolo das operações primitivas de tab (lado Python).

O content-script JS (edge_extension/content-script.js) implementa exatamente
estas operações; este módulo é a fonte de verdade dos nomes no Python e
valida mensagens antes de enviá-las ao relay/extensão.
"""
from __future__ import annotations

from typing import Any, Dict

TAB_OPS = frozenset({
    "NEW_CHAT",
    "SEND_MESSAGE",
    "WAIT_RESPONSE",
    "READ_RESPONSE",
    "GET_CONVERSATION_ID",
    "GET_CONVERSATION_URL",
    "STOP_GENERATION",
    "GET_STATUS",
})

WORKER_STATES = frozenset({"IDLE", "BUSY", "WAITING_RESPONSE"})


def build_tab_message(operation: str, **kwargs: Any) -> Dict[str, Any]:
    if operation not in TAB_OPS:
        raise ValueError(f"UNKNOWN_OPERATION: {operation}")
    msg: Dict[str, Any] = {"operation": operation}
    msg.update(kwargs)
    if operation == "SEND_MESSAGE" and not msg.get("text"):
        raise ValueError("SEND_MESSAGE requires text")
    return msg
