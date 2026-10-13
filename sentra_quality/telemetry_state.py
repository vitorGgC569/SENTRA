"""Protected persistent SafeTelemetryEvent queue, bounded batch/retention/loss."""
import math
import time

from sentra_runtime.otlp_sink import SafeTelemetryEvent, to_otlp
from .protected_state import digest, StateConflict
from .provider_clients import send_otlp


def validate_queue_configuration(config):
    for name, low, high, default in (("batch_size", 1, 128, 32), ("max_pending", 1, 2000, 2000),
            ("retention_seconds", 60, 30 * 86400, 7 * 86400), ("max_attempts", 1, 10, 3),
            ("batch_delay_seconds", 0, 60, 5)):
        value = config.get(name, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError("invalid telemetry queue bound: " + name)


class ProtectedTelemetryQueue:
    def __init__(self, state, *, config=None):
        self.state, self.config = state.scoped("selo.telemetry"), config or {}
        validate_queue_configuration(self.config)
        self.clock = state.clock

    def _counter(self, tx, name, amount=1):
        old = tx.get("counters")
        value = old["value"] if old else {}
        value[name] = value.get(name, 0) + amount
        tx.put("counters", value, expected_revision=old["revision"] if old else None)

    def enqueue(self, event, *, targets, correlations=None):
        if not isinstance(event, SafeTelemetryEvent) or not set(targets) <= {"otlp", "langfuse"} or not targets:
            raise ValueError("typed sanitized telemetry and configured targets required")
        key = "event:" + digest([event.name, event.state, event.operation_id])
        with self.state.transaction() as tx:
            if tx.get(key): return {"deduped": True, "event_key": key}
            pending = [r["value"] for _, r in tx.records("event:")
                       if any(v["state"] not in {"ACKNOWLEDGED", "DROPPED"} for v in r["value"]["sinks"].values())]
            if len(pending) >= self.config.get("max_pending", 2000):
                self._counter(tx, "dropped_full")
                return {"dropped": True, "reason": "queue_full"}
            document = to_otlp(event)
            span = document["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            span["traceId"] = digest([self.state.owner, self.state.workspace_id, event.operation_id])[:32]
            span["spanId"] = key.split(":", 1)[1][:16]
            # Correlations come from the host, retain only allowlisted hashes.
            for name in ("run_id", "work_item_id", "provider", "machine_id"):
                value = (correlations or {}).get(name)
                if isinstance(value, str) and len(value) <= 256:
                    span["attributes"].append({"key": "sentra." + name + "_sha256",
                                               "value": {"stringValue": digest(value)}})
            tx.put(key, {"created_at": self.clock(), "document": document,
                "sinks": {sink: {"state": "QUEUED", "attempts": 0} for sink in targets}})
            self._counter(tx, "enqueued")
        return {"enqueued": True, "event_key": key, "trace_id": span["traceId"]}

    def stats(self):
        counters = self.state.get("counters")
        counts = {}
        for _, row in self.state.records("event:"):
            for sink, entry in row["value"]["sinks"].items():
                name = sink + ":" + entry["state"]
                counts[name] = counts.get(name, 0) + 1
        return {"counters": counters["value"] if counters else {}, "queue": counts,
                "audit_complete": False, "operation_results_changed": False}

    def flush(self, provider, client, *, limit=None, force=False, retry_uncertain=False):
        if provider not in {"otlp", "langfuse"} or type(force) is not bool or type(retry_uncertain) is not bool:
            raise ValueError("invalid telemetry flush")
        limit = self.config.get("batch_size", 32) if limit is None else limit
        if type(limit) is not int or not 1 <= limit <= self.config.get("batch_size", 32):
            raise ValueError("telemetry batch exceeds configured bound")
        self.prune()
        selected = []
        with self.state.transaction() as tx:
            for key, old in tx.records("event:"):
                item = old["value"]
                sink = item["sinks"].get(provider)
                if not sink or sink["state"] not in ({"QUEUED", "UNCERTAIN", "IN_FLIGHT"} if retry_uncertain else {"QUEUED"}):
                    continue
                if sink["attempts"] >= self.config.get("max_attempts", 3): continue
                if not force and self.clock() - item["created_at"] < self.config.get("batch_delay_seconds", 5): continue
                sink.update(state="IN_FLIGHT", attempts=sink["attempts"] + 1)
                revision = tx.put(key, item, expected_revision=old["revision"])
                selected.append((key, item, revision))
                if len(selected) == limit: break
        if not selected: return {"attempted": 0, "acknowledged": 0}
        document = {"resourceSpans": [span for _, item, _ in selected for span in item["document"]["resourceSpans"]]}
        acknowledged = False
        try:
            if provider == "langfuse": client.dispatch("traces", document)
            else: send_otlp(client, "/v1/traces", document)
            acknowledged = True
        finally:
            with self.state.transaction() as tx:
                for key, item, revision in selected:
                    item["sinks"][provider]["state"] = "ACKNOWLEDGED" if acknowledged else "UNCERTAIN"
                    tx.put(key, item, expected_revision=revision)
                self._counter(tx, "acknowledged_" + provider if acknowledged else "uncertain_" + provider, len(selected))
        return {"attempted": len(selected), "acknowledged": len(selected),
                "explicit_retry_may_duplicate_trace": retry_uncertain, "proves_operation_success": False}

    def prune(self):
        dropped = 0
        cutoff = self.clock() - self.config.get("retention_seconds", 7 * 86400)
        with self.state.transaction() as tx:
            for key, old in tx.records("event:"):
                item = old["value"]
                if item["created_at"] >= cutoff or item.get("document") is None: continue
                for sink in item["sinks"].values():
                    if sink["state"] != "ACKNOWLEDGED":
                        sink["state"] = "DROPPED"
                        dropped += 1
                item["document"] = None
                tx.put(key, item, expected_revision=old["revision"])
            if dropped: self._counter(tx, "dropped_retention", dropped)
        return {"dropped": dropped, "dedupe_tombstones_preserved": True}
