"""Concrete bounded TLS/loopback transports and Langfuse/OTLP clients.

Protocols come from the pinned third_party/langfuse Fern definitions. No SDK,
collector or optional service is started by construction. No proxies, redirects
or automatic retries. Credential refs are resolved by the trusted facade.
"""
import base64
import http.client
import json
import ssl
from urllib.parse import quote, urlencode, urlsplit

from sentra_runtime._policy_http import strict_json


class ProviderUnavailable(RuntimeError):
    pass


class ScopedJSONHTTP:
    def __init__(self, *, base, credential=None, auth="bearer", allow_loopback=False,
                 timeout_s=5, checkpoint, max_response=2_000_000):
        parsed = urlsplit(base)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or ".." in parsed.path or "\\" in parsed.path
                or parsed.scheme == "http" and
                (not allow_loopback or parsed.hostname not in {"127.0.0.1", "::1"})
                or type(timeout_s) not in {int, float} or not 0 < timeout_s <= 30
                or not callable(checkpoint)):
            raise ValueError("explicit trusted TLS/loopback provider configuration required")
        self.base, self.url = base.rstrip("/"), parsed
        self.timeout_s, self.max_response, self.checkpoint = timeout_s, max_response, checkpoint
        self.authorization = None
        if credential is not None:
            if auth == "basic":
                if (not isinstance(credential, dict) or set(credential) != {"public_key", "secret_key"}
                        or any(not isinstance(v, str) or not v or any(c in v for c in "\r\n\0")
                               for v in credential.values()) or ":" in credential["public_key"]):
                    raise ValueError("Langfuse public/secret key pair required")
                self.authorization = "Basic " + base64.b64encode(
                    (credential["public_key"] + ":" + credential["secret_key"]).encode()).decode()
            elif auth == "bearer" and isinstance(credential, str) and credential and not any(
                    c in credential for c in "\r\n\0"):
                self.authorization = "Bearer " + credential
            else:
                raise ValueError("invalid provider credential")

    def request(self, method, path, *, payload=None, form=None, params=None,
                expected=(200,), bearer=None):
        if (method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}
                or not isinstance(path, str) or not path.startswith("/")
                or any(c in path for c in "?#\\\r\n\0") or ".." in path
                or payload is not None and form is not None):
            raise ValueError("invalid provider route")
        headers = {"Accept": "application/json"}
        if self.authorization:
            headers["Authorization"] = self.authorization
        if bearer is not None:
            if not isinstance(bearer, str) or not bearer or any(c in bearer for c in "\r\n\0"):
                raise ValueError("invalid scoped bearer")
            headers["Authorization"] = "Bearer " + bearer
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if form is not None:
            body = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if body is not None and len(body) > 1_000_000:
            raise ValueError("provider request exceeds bound")
        target = self.url.path.rstrip("/") + path + ("?" + urlencode(params) if params else "")
        connection = (http.client.HTTPSConnection(self.url.hostname, self.url.port or 443,
                       timeout=self.timeout_s, context=ssl.create_default_context())
                      if self.url.scheme == "https" else
                      http.client.HTTPConnection(self.url.hostname, self.url.port or 80,
                                                 timeout=self.timeout_s))
        try:
            self.checkpoint()
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(self.max_response + 1)
            if response.status not in expected or len(raw) > self.max_response:
                raise ProviderUnavailable("PROVIDER_RESPONSE_REJECTED")
            result = strict_json(raw) if raw else {}
            self.checkpoint()
            return result
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise ProviderUnavailable("PROVIDER_UNAVAILABLE_OR_UNCERTAIN") from exc
        finally:
            connection.close()

    def post(self, path, payload):
        return self.request("POST", path, payload=payload, expected=(200, 201))

    def get(self, path, *, params=None):
        return self.request("GET", path, params=params)

    def put(self, path, payload):
        return self.request("PUT", path, payload=payload, expected=(200, 204))


class LangfuseClient:
    """Version-pinned prompts/datasets/runs/items/scores + OTLP traces.

Dataset run API is v3 (explicit profile). Unsupported service versions fail
explicitly; scores/traces use current public scores and OTLP ingestion APIs.
"""
    ACTIONS = frozenset({"prompt_create", "prompt_get", "prompt_labels",
        "dataset_create", "dataset_get", "item_put", "item_get", "run_item",
        "run_get", "score_create", "scores_get", "traces"})

    def __init__(self, http, *, api_profile="langfuse-v3-dataset-runs"):
        if api_profile != "langfuse-v3-dataset-runs":
            raise ValueError("configured Langfuse dataset-run API profile unsupported")
        self.http = http

    def dispatch(self, action, body):
        if action not in self.ACTIONS or not isinstance(body, dict):
            raise ValueError("unknown Langfuse action")
        encoded = lambda name: quote(str(body[name]), safe="")
        if action == "prompt_create":
            return self.http.post("/api/public/v2/prompts", body)
        if action == "prompt_get":
            return self.http.get("/api/public/v2/prompts/" + encoded("name"),
                                 params={k: body[k] for k in ("version", "label") if k in body})
        if action == "prompt_labels":
            return self.http.request("PATCH", "/api/public/v2/prompts/" + encoded("name") +
                                     "/versions/" + encoded("version"),
                                     payload={"newLabels": body["labels"]})
        if action in {"dataset_create", "dataset_get"}:
            path = "/api/public/v2/datasets"
            return (self.http.post(path, body) if action == "dataset_create"
                    else self.http.get(path + "/" + encoded("name")))
        if action == "item_put":
            return self.http.post("/api/public/dataset-items", body)
        if action == "item_get":
            return self.http.get("/api/public/dataset-items/" + encoded("id"))
        if action == "run_item":
            return self.http.post("/api/public/dataset-run-items", body)
        if action == "run_get":
            return self.http.get("/api/public/datasets/" + encoded("datasetName") +
                                 "/runs/" + encoded("runName"))
        if action == "score_create":
            # Single score ACK is acceptance; it is not an independent verdict.
            return self.http.post("/api/public/scores", body)
        if action == "scores_get":
            return self.http.get("/api/public/v3/scores", params=body)
        return send_otlp(self.http, "/api/public/otel/v1/traces", body)


def send_otlp(http, path, document):
    response = http.request("POST", path, payload=document, expected=(200, 202))
    partial = response.get("partialSuccess", {})
    if not isinstance(partial, dict) or int(partial.get("rejectedSpans", 0)):
        raise ProviderUnavailable("OTLP_PARTIAL_REJECTION")
    return {"transport_acknowledged": True, "proves_operation_success": False}
