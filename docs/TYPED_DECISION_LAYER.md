# Typed decision layer (Kev / Jev / System One)

SENTRA can optionally use a typed decision model for fast probabilistic choices without replacing its deterministic safety policy.

## Contract

The integration speaks the TypeSafe-compatible `POST /v1/systemone` contract directly over HTTP and does not import Kev, Jev, Torch, Transformers, or a vendor SDK into the SENTRA runtime.

Supported primitives:

- `choice`: pick among named options with probabilities and confidence.
- `noul`: probability of yes/true.
- `score`: ordered readiness/rating levels.

A local Kev server is one compatible backend. A hosted System One-compatible service can be chained after it as a fallback.

## Safety invariants

The decision layer is advisory.

1. Explicit provider selection is never overridden.
2. Critical provider routing is never overridden.
3. Delivery states such as `UNCERTAIN` and `BLOCKED` remain deterministic and cannot be turned into retries.
4. Retry advice is consulted only after SENTRA has already classified a failure as safe/transient. The model may stop a retry early; it cannot create a new retry permission or extend the retry budget.
5. Validator selection never removes validators already active. For ordinary non-critical expansion it may add one confident standby validator first. Low confidence or provider failure restores the historical full deterministic expansion. High/critical work bypasses this reduction.
6. Quality readiness is telemetry only. It cannot alter the deterministic Quality Gate result, quorum, objective-test requirement, critical rejection rules, release score, or promotion boundary.
7. Plain HTTP decision endpoints are accepted only on loopback. Remote providers must use HTTPS.
8. If every decision backend fails, times out, returns malformed data, or falls below the configured confidence threshold, SENTRA falls back to its existing deterministic behavior.

## Configuration

The feature is off by default.

```yaml
decisioning:
  enabled: true
  routing: true
  retry: true
  validator_selection: true
  quality_advisory: true
  min_confidence: 0.35
  providers:
    - name: kev
      type: systemone
      base_url: "http://127.0.0.1:8009"
      model: "kev-latest"
      timeout_s: 5.0
```

Providers are tried in listed order. A second hosted provider can be added with an API key supplied through an environment variable:

```yaml
    - name: hosted-systemone
      type: systemone
      base_url: "https://example.invalid"
      model: "jev-latest"
      api_key_env: "SYSTEMONE_API_KEY"
      timeout_s: 5.0
```

Secrets are not stored in the configuration.

## Kev local

Kev is kept outside the SENTRA Git tree. A compatible server can be started independently, for example:

```text
python -m kev.serve --run jaredpalmer/kev-0.8b --port 8009
```

The server should bind to loopback. SENTRA then sends typed state/questions to `http://127.0.0.1:8009/v1/systemone`.

## Runtime mapping

### Model Router

For non-explicit, non-critical routing, the decision model receives the deterministic route, role, priority/risk, observed provider reliability, circuit state, and a bounded request excerpt.

A confident recommendation can be tried first. The deterministic route remains immediately behind it, so a bad recommendation cannot remove the known route.

### Retry controller

Only safe/transient failures reach the decision model. It chooses between:

- `retry`: use the existing bounded retry/backoff.
- `abort`: stop the retry loop early.

It cannot authorize a replay that deterministic delivery policy forbids.

### Validator selection

On disagreement or low-confidence expansion for ordinary work, the model can choose the most useful single standby validator for the next round. Active validators remain active. If advice is unavailable or weak, SENTRA performs its existing full expansion.

Critical/high-risk work keeps the full deterministic expansion.

### Quality readiness

After deterministic verification and Quality Gate evaluation, the decision model may emit a readiness `score`. The result is stored as advisory telemetry only and cannot flip the gate result.

## Observability

Decision traces are persisted as `DECISION_ADVISORY` events. They include the decision kind, source/model, confidence, selected option or score, and whether deterministic fallback was used where applicable.

This keeps decision-model activity distinct from `MODEL_RESPONSE` events produced by generative agents.

## Validation

The integration is covered by unit tests for:

- System One HTTP request/response handling.
- Choice/Noul/Score parsing.
- low-confidence deterministic fallback.
- provider routing with deterministic route preservation.
- critical/explicit route bypass.
- retry early-abort without expansion of retry authority.
- validator selection with active-role preservation.
- critical validator bypass.
- Quality Gate advisory non-authority.
- configuration and endpoint-security validation.

A live Kev-0.8B inference was also exercised through the project's public demo using the same typed question shapes.
