"""Read-only Realtime sideband; provider events never execute tools.

Protocol: OpenAI voice-server-controls?voice-api=realtime (Location call ID,
wss /realtime?call_id=). No reconnect/resend of session creation or commands.
The optional websockets package is loaded only by the admitted host effect.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from urllib.parse import quote, urlsplit, urlunsplit

from .protected_assets import checkpoint


class RealtimeSideband:
    def __init__(self, base_url, api_key):
        self.base_url, self.api_key = base_url, api_key
        self._connections = {}
        self._lock = threading.RLock()

    def attach(self, call_ref):
        if not isinstance(call_ref, str) or not call_ref.startswith("rtc_") or len(call_ref) > 200:
            raise ValueError("provider-authenticated WebRTC call reference required")
        with self._lock:
            if call_ref in self._connections:
                return
            from websockets.sync.client import connect
            parsed = urlsplit(self.base_url)
            url = urlunsplit(("wss" if parsed.scheme == "https" else "ws", parsed.netloc,
                             parsed.path.rstrip("/") + "/realtime", "call_id=" + quote(call_ref), ""))
            checkpoint(required=True)
            socket = connect(url, additional_headers={"Authorization": "Bearer " + self.api_key},
                             open_timeout=8, close_timeout=2, max_size=65536, max_queue=64)
            self._connections[call_ref] = socket

    def drain(self, call_ref, *, max_events=256):
        self.attach(call_ref)
        result = []
        deadline = time.monotonic() + 2
        with self._lock:
            socket = self._connections[call_ref]
            while len(result) < max_events and time.monotonic() < deadline:
                checkpoint(required=True)
                try:
                    raw = socket.recv(timeout=0.01)
                except TimeoutError:
                    break
                except Exception:
                    self._connections.pop(call_ref, None)
                    socket.close()
                    raise RuntimeError("Realtime sideband disconnected; transcript continuity uncertain")
                event = json.loads(raw)
                if isinstance(event, dict) and isinstance(event.get("event_id"), str):
                    result.append(event)
        return result

    def detach(self, call_ref):
        with self._lock:
            socket = self._connections.pop(call_ref, None)
            if socket is not None:
                socket.close()

    @staticmethod
    def transcript(event):
        kind = event.get("type")
        roles = {"conversation.item.input_audio_transcription.completed": "user",
                 "response.output_audio_transcript.done": "assistant",
                 "response.audio_transcript.done": "assistant"}
        if kind not in roles:
            return None
        content, item_id, event_id = event.get("transcript"), event.get("item_id"), event.get("event_id")
        if (not isinstance(content, str) or not content or len(content) > 32000
                or not isinstance(item_id, str) or not isinstance(event_id, str)):
            return None
        identity = hashlib.sha256(json.dumps([item_id, event.get("content_index", 0)],
                                             separators=(",", ":")).encode()).hexdigest()[:32]
        return {"message_id": "voice-" + identity, "role": roles[kind],
                "content": content, "provider_receipt": event_id,
                "provider_item_id": item_id, "event_type": kind}
