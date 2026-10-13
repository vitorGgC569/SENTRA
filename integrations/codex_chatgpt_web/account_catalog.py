"""Fail-closed merge of the Codex-cached Web catalog with the attested account catalog.

The SENTRA gateway caches an authenticated Codex model catalog
(`GatewayServer.cached_model_catalog`). The browser host attests which
models/efforts the *current* account/profile can actually use
(`browser/account_catalog.py` + `BrowserEvidenceService.account_catalog_status`).

This helper intersects both sources WITHOUT exposing Codex auth: a model is
listed only when it appears in the cached gateway catalog AND in a verified
(non-stale) attested account catalog. Anything else fails closed with an
explicit reason. No grants, no sends, no authority — a pure projection for
the shell home and settings surfaces.
"""
from __future__ import annotations

from typing import Any


def merge_catalogs(*, gateway_catalog: dict[str, Any],
                   attested: dict[str, Any]) -> dict[str, Any]:
    models = gateway_catalog.get("models")
    if not isinstance(models, list):
        return {"verified": False, "models": [], "reason": "gateway_catalog_unavailable"}
    if not isinstance(attested, dict) or attested.get("verified") is not True:
        return {"verified": False, "models": [],
                "reason": str(attested.get("reason") or "no_attested_catalog")}
    allowed_models = {str(m) for m in attested.get("models", []) if isinstance(m, str)}
    allowed_efforts = {str(e) for e in attested.get("efforts", []) if isinstance(e, str)}
    visible: list[dict[str, str]] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        slug = str(model.get("slug") or model.get("id") or "")
        if not slug:
            continue
        name = slug.split("/")[-1]
        if name in allowed_models or f"sentra/{name}" == slug or slug in allowed_models:
            safe = {k: v for k, v in model.items()
                    if k in {"slug", "id", "display_name", "description"}
                    and isinstance(v, str) and v}
            if safe:
                visible.append(safe)
    return {"verified": True, "models": visible,
            "efforts": sorted(allowed_efforts),
            "authentication_revision": attested.get("authentication_revision"),
            "age_s": attested.get("age_s")}
