"""Optional, local-only OpenTelemetry OTLP/HTTP JSON evidence sink.

No raw prompts, terminal output, tokens, arguments or audit events are sent.
The authoritative SENTRA ledger, not OTLP, owns operation state. Export is
explicit opt-in; it does not auto-start collectors, open public ports or retry
possibly duplicated events after timeouts. This is OTLP transport validation
against a real loopback HTTP receiver, not an external Collector deployment.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time
from urllib.parse import urlsplit
import urllib.request
import urllib.error
import uuid


_ALLOWED_STATES = frozenset({"ACCEPTED", "RUNNING", "SUCCEEDED",
                             "FAILED", "CANCELLED", "UNCERTAIN"})
_ALLOWED_NAMES = frozenset({"sentra.operation", "sentra.policy",
                            "sentra.machine", "sentra.collab"})


class TelemetryUnavailable(RuntimeError):
    """Optional telemetry delivery is unavailable or malformed."""


@dataclass(frozen=True, slots=True)
class SafeTelemetryEvent:
    name: str
    state: str
    operation_id: str
    elapsed_ms: int = 0

    def __post_init__(self):
        if self.name not in _ALLOWED_NAMES or self.state not in _ALLOWED_STATES:
            raise ValueError("unsupported sanitized telemetry event")
        if (not isinstance(self.operation_id, str) or not self.operation_id
                or len(self.operation_id) > 256):
            raise ValueError("invalid operation identity")
        if type(self.elapsed_ms) is not int or not 0 <= self.elapsed_ms <= 86400000:
            raise ValueError("invalid elapsed_ms")


def to_otlp(event: SafeTelemetryEvent, *, service: str = "sentra-os") -> dict:
    """Use only a strict allowlist; operation IDs become irreversible digests."""
    if not isinstance(event, SafeTelemetryEvent):
        raise ValueError("invalid telemetry type")
    if not isinstance(service, str) or not service or len(service) > 64:
        raise ValueError("invalid service")
    now = time.time_ns()
    start = max(0, now - event.elapsed_ms * 1_000_000)
    return {
        "resourceSpans": [{
            "resource": {"attributes": [{"key": "service.name",
                                         "value": {"stringValue": service}}]},
            "scopeSpans": [{
                "scope": {"name": "sentra.runtime"},
                "spans": [{
                    "traceId": uuid.uuid4().hex,
                    "spanId": uuid.uuid4().hex[:16],
                    "name": event.name,
                    "startTimeUnixNano": str(start),
                    "endTimeUnixNano": str(now),
                    "attributes": [
                        {"key": "sentra.operation_sha256",
                         "value": {"stringValue":
                             hashlib.sha256(event.operation_id.encode("utf-8")).hexdigest()}},
                        {"key": "sentra.operation_state",
                         "value": {"stringValue": event.state}},
                    ],
                }],
            }],
        }]
    }


class LocalOtlpExporter:
    """Push at most one OTLP JSON request to a trusted loopback collector."""

    def __init__(self, endpoint: str, *, timeout_s: float = 2.0):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.username or parsed.password or parsed.fragment
                or parsed.query or parsed.path != "/v1/traces"
                or parsed.port is None):
            raise ValueError("OTLP endpoint must be explicit HTTP loopback /v1/traces")
        if not 0 < timeout_s <= 10:
            raise ValueError("invalid bounded timeout")
        self.endpoint = endpoint
        self.timeout_s = timeout_s

    def emit(self, event: SafeTelemetryEvent) -> None:
        data = json.dumps(to_otlp(event), ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        self._send(data)

    def _send(self,data: bytes) -> None:
        if not isinstance(data,bytes) or not 0<len(data)<=1024*1024:
            raise TelemetryUnavailable("bounded telemetry payload required")
        req = urllib.request.Request(
            self.endpoint, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self,*args,**kwargs):return None
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            with opener.open(req, timeout=self.timeout_s) as response:
                if response.status not in (200, 202, 204):
                    raise TelemetryUnavailable("collector did not accept telemetry")
                reply=response.read(2049)
                if len(reply) > 2048:
                    raise TelemetryUnavailable("collector response exceeded limit")
                if reply:
                    try:
                        receipt=json.loads(reply)
                        partial=receipt.get("partialSuccess",{})
                        rejected=int(partial.get("rejectedSpans",0))
                    except (ValueError,TypeError,AttributeError) as exc:
                        raise TelemetryUnavailable("collector acknowledgement is invalid") from exc
                    if rejected>0:raise TelemetryUnavailable("collector partially rejected telemetry")
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise TelemetryUnavailable("loopback telemetry collector unavailable") from exc
