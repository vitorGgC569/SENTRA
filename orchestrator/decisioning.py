"""Typed decision-provider layer for fast System One style routing.

Decision models are advisory. Deterministic SENTRA policy remains authoritative:
callers always provide a safe default and may ignore/override any model answer.
"""
from __future__ import annotations

import asyncio
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


class DecisionProviderError(RuntimeError):
    """A decision backend could not return a trustworthy typed response."""


@dataclass(frozen=True, slots=True)
class DecisionBatch:
    provider: str
    model: str
    answers: Mapping[str, Mapping[str, Any]]
    latency_ms: float | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionSelection:
    value: str
    confidence: float
    probabilities: Mapping[str, float]
    source: str
    model: str = ""
    used_deterministic_fallback: bool = False


class DecisionProvider(Protocol):
    name: str

    async def decide(
        self,
        *,
        state: Any,
        questions: Mapping[str, Mapping[str, Any]],
    ) -> DecisionBatch:
        ...


def _validated_base_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("decision provider base_url must be absolute http/https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("decision provider base_url must not contain credentials/query/fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("plaintext decision provider URLs are restricted to loopback")
    if parsed.path not in {"", "/"}:
        raise ValueError("decision provider base_url must not contain a path")
    return raw


class SystemOneHTTPProvider:
    """Minimal TypeSafe System One compatible HTTP client.

    Works with local Kev and hosted System One compatible services without
    importing either SDK into SENTRA.
    """

    def __init__(
        self,
        base_url: str,
        *,
        model: str = "kev-latest",
        api_key: str | None = None,
        timeout_s: float = 5.0,
        name: str = "systemone",
        max_request_bytes: int = 512_000,
    ) -> None:
        if timeout_s <= 0 or timeout_s > 120:
            raise ValueError("decision provider timeout_s must be in (0, 120]")
        if max_request_bytes < 1024 or max_request_bytes > 4_000_000:
            raise ValueError("decision provider max_request_bytes out of range")
        self.base_url = _validated_base_url(base_url)
        self.model = str(model or "").strip() or "kev-latest"
        self.api_key = api_key
        self.timeout_s = float(timeout_s)
        self.name = str(name or "systemone")
        self.max_request_bytes = int(max_request_bytes)

    def _post_sync(
        self,
        state: Any,
        questions: Mapping[str, Mapping[str, Any]],
    ) -> DecisionBatch:
        payload = {
            "state": state,
            "model": self.model,
            "questions": dict(questions),
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > self.max_request_bytes:
            raise DecisionProviderError("decision request exceeds configured byte limit")
        headers = {"content-type": "application/json", "accept": "application/json"}
        if self.api_key:
            headers["authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(
            self.base_url + "/v1/systemone",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as response:
                if response.status != 200:
                    raise DecisionProviderError(f"decision provider HTTP {response.status}")
                raw = response.read(self.max_request_bytes + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DecisionProviderError(f"decision provider unavailable: {exc}") from exc
        if len(raw) > self.max_request_bytes:
            raise DecisionProviderError("decision response exceeds configured byte limit")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DecisionProviderError("decision provider returned invalid JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
            raise DecisionProviderError("decision provider response has no answers object")
        answers = data["answers"]
        missing = set(questions) - set(answers)
        if missing:
            raise DecisionProviderError("decision provider omitted questions: " + ", ".join(sorted(missing)))
        latency = data.get("latency_ms")
        latency_ms = float(latency) if isinstance(latency, (int, float)) and math.isfinite(latency) else None
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return DecisionBatch(
            provider=self.name,
            model=str(data.get("model") or self.model),
            answers=answers,
            latency_ms=latency_ms,
            usage=usage,
        )

    async def decide(
        self,
        *,
        state: Any,
        questions: Mapping[str, Mapping[str, Any]],
    ) -> DecisionBatch:
        if not isinstance(questions, Mapping) or not questions:
            raise ValueError("questions must be a non-empty mapping")
        return await asyncio.to_thread(self._post_sync, state, questions)


class DecisionController:
    """Try typed decision providers, then fail closed to a deterministic default."""

    def __init__(
        self,
        providers: list[DecisionProvider] | tuple[DecisionProvider, ...] = (),
        *,
        min_confidence: float = 0.0,
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be in [0, 1]")
        self.providers = tuple(providers)
        self.min_confidence = float(min_confidence)

    async def choose(
        self,
        *,
        state: Any,
        instructions: Any,
        criteria: Mapping[str, Any],
        default: str,
        question_id: str = "decision",
        min_confidence: float | None = None,
    ) -> DecisionSelection:
        allowed = tuple(str(key) for key in criteria)
        if not allowed or default not in allowed:
            raise ValueError("default must be one of the non-empty criteria")
        threshold = self.min_confidence if min_confidence is None else float(min_confidence)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("min_confidence must be in [0, 1]")
        question = {
            question_id: {
                "type": "choice",
                "instructions": instructions,
                "criteria": dict(criteria),
            }
        }
        for provider in self.providers:
            try:
                batch = await provider.decide(state=state, questions=question)
                answer = batch.answers.get(question_id)
                if not isinstance(answer, Mapping):
                    continue
                choice = str(answer.get("choice") or "")
                if choice not in allowed:
                    continue
                raw_probs = answer.get("probabilities")
                probs: dict[str, float] = {}
                if isinstance(raw_probs, Mapping):
                    for key in allowed:
                        value = raw_probs.get(key)
                        if isinstance(value, (int, float)) and math.isfinite(float(value)):
                            probs[key] = float(value)
                raw_conf = answer.get("confidence")
                confidence = (
                    float(raw_conf)
                    if isinstance(raw_conf, (int, float)) and math.isfinite(float(raw_conf))
                    else max(probs.values(), default=0.0)
                )
                confidence = min(1.0, max(0.0, confidence))
                if confidence < threshold:
                    continue
                return DecisionSelection(
                    value=choice,
                    confidence=confidence,
                    probabilities=probs,
                    source=batch.provider,
                    model=batch.model,
                    used_deterministic_fallback=False,
                )
            except (DecisionProviderError, ValueError, TypeError, KeyError):
                continue
        return DecisionSelection(
            value=default,
            confidence=1.0,
            probabilities={default: 1.0},
            source="deterministic",
            used_deterministic_fallback=True,
        )

    async def noul(
        self,
        *,
        state: Any,
        instructions: Any,
        default_probability: float = 0.0,
        question_id: str = "decision",
    ) -> tuple[float, str]:
        default_probability = min(1.0, max(0.0, float(default_probability)))
        question = {question_id: {"type": "noul", "instructions": instructions}}
        for provider in self.providers:
            try:
                batch = await provider.decide(state=state, questions=question)
                answer = batch.answers.get(question_id)
                value = answer.get("noul") if isinstance(answer, Mapping) else None
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    return min(1.0, max(0.0, float(value))), batch.provider
            except (DecisionProviderError, ValueError, TypeError, KeyError):
                continue
        return default_probability, "deterministic"

    async def score(
        self,
        *,
        state: Any,
        instructions: Any,
        criteria: list[Any] | tuple[Any, ...],
        default_score: float = 0.0,
        question_id: str = "decision",
    ) -> tuple[float, float, str]:
        levels = list(criteria)
        if not levels:
            raise ValueError("score criteria must be non-empty")
        upper = float(len(levels) - 1)
        default_score = min(upper, max(0.0, float(default_score)))
        question = {
            question_id: {
                "type": "score",
                "instructions": instructions,
                "criteria": levels,
            }
        }
        for provider in self.providers:
            try:
                batch = await provider.decide(state=state, questions=question)
                answer = batch.answers.get(question_id)
                if not isinstance(answer, Mapping):
                    continue
                value = answer.get("score")
                if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    continue
                raw_conf = answer.get("confidence")
                confidence = (
                    float(raw_conf)
                    if isinstance(raw_conf, (int, float)) and math.isfinite(float(raw_conf))
                    else 0.0
                )
                return (
                    min(upper, max(0.0, float(value))),
                    min(1.0, max(0.0, confidence)),
                    batch.provider,
                )
            except (DecisionProviderError, ValueError, TypeError, KeyError):
                continue
        return default_score, 1.0, "deterministic"
