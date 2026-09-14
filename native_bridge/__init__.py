"""Native bridge OMA <-> Edge Extension (relay local + host stdio)."""
from .protocol import ChatJob, ChatResult
from .relay import RelayServer, RelayState
from .host import encode_message, decode_messages, serve_forever

__all__ = ["ChatJob", "ChatResult", "RelayServer", "RelayState",
           "encode_message", "decode_messages", "serve_forever"]
