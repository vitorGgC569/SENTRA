"""Native Messaging host (caminho endurecido, stdio com framing de 4 bytes).

Quando o Edge conecta via chrome.runtime.connectNative(), o browser spawna
este host e ambos falam mensagens JSON prefixadas por uint32LE. Este módulo
implementa o framing + validação; o transporte de fila em produção é o relay
(native_bridge/relay.py), testável sem browser.
"""
from __future__ import annotations

import json
import struct
import sys
from typing import Any, Callable, Dict


def encode_message(payload: Dict[str, Any]) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def decode_messages(buf: bytes):
    """Extrai (mensagens, restante) de um buffer com framing <I+json>."""
    msgs = []
    off = 0
    while len(buf) - off >= 4:
        (size,) = struct.unpack_from("<I", buf, off)
        if len(buf) - off - 4 < size:
            break
        msgs.append(json.loads(buf[off + 4:off + 4 + size].decode("utf-8")))
        off += 4 + size
    return msgs, buf[off:]


def serve_forever(handler: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    buf = b""
    while True:
        chunk = stdin.read(4096)
        if not chunk:
            break
        buf += chunk
        msgs, buf = decode_messages(buf)
        for msg in msgs:
            try:
                reply = handler(msg)
            except Exception as e:  # nunca derruba o host por msg ruim
                reply = {"ok": False, "error": str(e)}
            stdout.write(encode_message(reply))
            stdout.flush()
