"""Account-aware Web model/effort catalog (Rastro).

Provenance: adapts the Chat On Steroids P0 "real account model" contract
(`third_party/chat-on-steroids/src/main/chat-models.ts`,
`src/renderer/chat-models.ts`, `test/model-picker-state.test.ts`):
states unknown/pending/ready/unavailable, nonce-bound observation, the
effectively offered model/effort, and Automatic for accounts without a
picker. No model is inferred from a name; only observed entries can be
selected. Control Plane/Grants are never created here.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_FINGERPRINT_RE = re.compile(r"[a-f0-9]{64}")
_NONCE_RE = re.compile(r"[A-Za-z0-9_-]{8,160}")
_DEFAULT_EFFORTS = ("low", "medium", "high")
_AUTOMATIC_ALIASES = {"automatic", "auto", ""}


def _bounded_ref(value: Any, *, field: str, maximum: int = 160) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{field} requires 1..{maximum} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{field} contains control characters")
    return value


class AccountModelCatalog:
    """Per-account observed Web models with generation-bound selection.

    Persistence is a single 0600 JSON file under <state>/web-models/.
    The file holds only safe display metadata plus opaque account
    fingerprints (SHA-256 hex, never e-mail/token). Missing attestor or
    missing observation fails closed via unknown/unavailable states.
    """

    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        self.state_root = Path(state_root).resolve()
        self.clock = clock
        self.lock = threading.RLock()
        self.path = self.state_root / "web-models" / "account-catalog.json"

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"generation": 0, "accounts": {}}
        except (OSError, ValueError, json.JSONDecodeError):
            raise RuntimeError("account catalog cache is invalid; host repair required")
        if not isinstance(payload, dict) or not isinstance(payload.get("accounts"), dict):
            raise RuntimeError("account catalog cache is invalid; host repair required")
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(self.path)

    @staticmethod
    def _clean_models(models: Any) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        if not isinstance(models, list):
            raise ValueError("observed models must be a list")
        if len(models) > 512:
            raise ValueError("observed model list exceeds 512 entries")
        for entry in models:
            if not isinstance(entry, dict):
                continue
            slug = entry.get("slug") or entry.get("id") or ""
            if not isinstance(slug, str) or not 1 <= len(slug) <= 160:
                continue
            safe: dict[str, Any] = {"slug": slug, "id": str(entry.get("id") or slug)}
            for key in ("display_name", "description"):
                value = entry.get(key)
                if isinstance(value, str) and value and len(value) <= 500:
                    safe[key] = value
            efforts = entry.get("efforts")
            if isinstance(efforts, list) and efforts:
                safe["efforts"] = [str(item)[:40] for item in efforts
                                   if isinstance(item, str) and 1 <= len(item) <= 40][:16]
            if isinstance(entry.get("picker"), bool):
                safe["picker"] = entry["picker"]
            cleaned.append(safe)
        return cleaned

    def mark_pending(self, account_fingerprint: str, *, collector_ref: str) -> dict[str, Any]:
        if not isinstance(account_fingerprint, str) or not _FINGERPRINT_RE.fullmatch(account_fingerprint):
            raise ValueError("opaque SHA256 account fingerprint required")
        collector = _bounded_ref(collector_ref, field="collector_ref")
        with self.lock:
            payload = self._load()
            accounts = payload["accounts"]
            previous = accounts.get(account_fingerprint) or {}
            accounts[account_fingerprint] = {
                **previous,
                "status": "pending",
                "collector_ref": collector,
                "updated_at": self.clock(),
                "generation": int(payload.get("generation") or 0),
            }
            self._save(payload)
            return self.cached_view(account_fingerprint)

    def mark_unavailable(self, account_fingerprint: str, *, reason: str) -> dict[str, Any]:
        if not isinstance(account_fingerprint, str) or not _FINGERPRINT_RE.fullmatch(account_fingerprint):
            raise ValueError("opaque SHA256 account fingerprint required")
        detail = _bounded_ref(reason, field="reason", maximum=240)
        with self.lock:
            payload = self._load()
            accounts = payload["accounts"]
            previous = accounts.get(account_fingerprint) or {}
            accounts[account_fingerprint] = {
                **previous,
                "status": "unavailable",
                "reason": detail,
                "updated_at": self.clock(),
            }
            self._save(payload)
            return self.cached_view(account_fingerprint)

    def observe(self, account_fingerprint: str, models: list[dict[str, Any]], *,
                collector_ref: str, nonce: str, picker_available: bool = True) -> dict[str, Any]:
        """Record one authenticated account observation; returns the cached view."""
        if not isinstance(account_fingerprint, str) or not _FINGERPRINT_RE.fullmatch(account_fingerprint):
            raise ValueError("opaque SHA256 account fingerprint required, not email/token")
        if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce):
            raise ValueError("bounded observation nonce required")
        if type(picker_available) is not bool:
            raise ValueError("picker_available must be boolean")
        collector = _bounded_ref(collector_ref, field="collector_ref")
        cleaned = self._clean_models(models)
        with self.lock:
            payload = self._load()
            generation = int(payload.get("generation") or 0) + 1
            payload["generation"] = generation
            payload["accounts"][account_fingerprint] = {
                "status": "ready",
                "models": cleaned,
                "picker_available": picker_available,
                "automatic_allowed": True,
                "collector_ref": collector,
                "nonce": nonce,
                "generation": generation,
                "updated_at": self.clock(),
            }
            self._save(payload)
            return self.cached_view(account_fingerprint)

    def cached_view(self, account_fingerprint: str | None = None, *,
                    max_age_s: int = 600) -> dict[str, Any]:
        """Safe projection; use merge_attested for the Brisa-verified shell view."""
        if type(max_age_s) is not int or not 1 <= max_age_s <= 3600:
            raise ValueError("bounded freshness required")
        with self.lock:
            payload = self._load()
        if account_fingerprint is None:
            summary = {fp: {"status": item.get("status"), "generation": item.get("generation"),
                            "updated_at": item.get("updated_at")}
                       for fp, item in payload["accounts"].items()}
            return {"status": "unknown" if not summary else "ready",
                    "accounts": summary, "generation": payload.get("generation") or 0,
                    "automatic_resend": False}
        if not isinstance(account_fingerprint, str) or not _FINGERPRINT_RE.fullmatch(account_fingerprint):
            raise ValueError("opaque SHA256 account fingerprint required")
        item = payload["accounts"].get(account_fingerprint)
        if item is None:
            return {"status": "unknown", "account_fingerprint": account_fingerprint,
                    "models": [], "automatic_allowed": True, "generation": None,
                    "updated_at": None, "age_seconds": None,
                    "trusted_account_proof": False, "automatic_resend": False}
        age = max(0.0, self.clock() - float(item.get("updated_at") or 0.0))
        freshness = item.get("status")
        if freshness == "ready" and age > max_age_s:
            freshness = "stale"
        return {"status": freshness, "account_fingerprint": account_fingerprint,
                "models": list(item.get("models") or []),
                "picker_available": bool(item.get("picker_available", True)),
                "automatic_allowed": True,
                "collector_ref": item.get("collector_ref"),
                "nonce": item.get("nonce"),
                "generation": item.get("generation"),
                "updated_at": item.get("updated_at"), "age_seconds": age,
                "reason": item.get("reason"),
                "trusted_account_proof": False, "automatic_resend": False}

    def merge_attested(self, account_fingerprint: str, attested: dict[str, Any],
                       gateway_catalog: dict[str, Any] | None = None) -> dict[str, Any]:
        """Intersect observed account models with Brisa's verified catalog.

        A model is shell-visible only when observed here AND attested as
        verified (fresh, same account binding) by Brisa
        (`AccountCatalog.status` / `merge_catalogs`). Anything else fails
        closed with an explicit reason. Pure projection: no grants, sends
        or authority.
        """
        view = self.cached_view(account_fingerprint)
        if view["status"] != "ready" or not view["models"]:
            return {"verified": False, "models": [],
                    "reason": "gateway_account_unobserved",
                    "gateway_status": view["status"]}
        if not isinstance(attested, dict) or attested.get("verified") is not True:
            return {"verified": False, "models": [],
                    "reason": str((attested or {}).get("reason")
                                  or "no_attested_catalog")}
        allowed = {str(m) for m in attested.get("models", []) if isinstance(m, str)}
        visible = [m for m in view["models"]
                   if m.get("slug") in allowed or m.get("id") in allowed]
        if gateway_catalog is not None:
            try:
                from integrations.codex_chatgpt_web.account_catalog import (
                    merge_catalogs)
                merged = merge_catalogs(gateway_catalog=gateway_catalog,
                                        attested={**attested, "models": sorted(allowed)})
                gateway_visible = {str(m.get("slug") or m.get("id"))
                                   for m in merged.get("models", [])
                                   if isinstance(m, dict)}
                visible = [m for m in visible
                           if m.get("slug") in gateway_visible
                           or m.get("id") in gateway_visible]
            except (ImportError, ValueError, AttributeError, TypeError):
                return {"verified": False, "models": [],
                        "reason": "gateway_merge_unavailable"}
        return {"verified": True, "models": visible,
                "efforts": sorted(str(e) for e in attested.get("efforts", [])
                                  if isinstance(e, str)),
                "generation": view["generation"],
                "authentication_revision": attested.get("authentication_revision"),
                "age_s": attested.get("age_s"), "grants_created": False}

    def select(self, account_fingerprint: str, requested_model: str | None,
               requested_effort: str | None = None, *,
               expected_generation: int | None = None,
               active_generation: int | None = None) -> dict[str, Any]:
        """Resolve an effective model/effort strictly from observed entries.

        Cancellation or a mid-generation account/model switch never mutates
        the active session: a generation mismatch raises instead of applying.
        """
        view = self.cached_view(account_fingerprint)
        if view["status"] in {"unknown", "pending"}:
            raise PermissionError(f"account catalog is {view['status']}; no model can be chosen yet")
        if view["status"] in {"unavailable", "stale"} and not view["models"] and \
                str(requested_model or "").strip().casefold() not in _AUTOMATIC_ALIASES:
            raise PermissionError("explicit model requires a fresh ready observation")
        if expected_generation is not None and view["generation"] != expected_generation:
            raise ValueError("model observation changed; reconcile selection before sending")
        if active_generation is not None and view["generation"] != active_generation:
            raise ValueError("account catalog rotated during generation; active session is unchanged")
        models: list[dict[str, Any]] = view["models"]
        wanted = str(requested_model or "").strip()
        if wanted.casefold() in _AUTOMATIC_ALIASES:
            if not models:
                return {"model": "automatic", "effort": None, "automatic": True,
                        "account_fingerprint": account_fingerprint,
                        "generation": view["generation"], "grants_created": False}
            first = models[0]
            efforts = first.get("efforts") or list(_DEFAULT_EFFORTS)
            effort = str(requested_effort or "").strip().lower()
            if not effort or effort == "auto":
                effort = str(efforts[0])
            elif effort not in [str(item).lower() for item in efforts]:
                raise ValueError("requested effort is not offered for the automatic model")
            return {"model": first["slug"], "effort": effort, "automatic": True,
                    "account_fingerprint": account_fingerprint,
                    "generation": view["generation"], "grants_created": False}
        match = next((m for m in models
                      if wanted in {m.get("slug"), m.get("id")}), None)
        if match is None:
            raise ValueError("requested model was not announced for this account")
        offered = match.get("efforts") or list(_DEFAULT_EFFORTS)
        lowered = [str(item).lower() for item in offered]
        effort = str(requested_effort or "").strip().lower()
        if not effort or effort == "auto":
            effort = lowered[0]
        elif effort not in lowered:
            raise ValueError("requested effort is not offered for this model")
        return {"model": match["slug"], "effort": effort, "automatic": False,
                "account_fingerprint": account_fingerprint,
                "generation": view["generation"], "grants_created": False}
