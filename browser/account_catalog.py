"""Authenticated account model/effort catalog for Web providers.

Chat On Steroids asks for a *real* catalog: show only the models and efforts
available to the currently authenticated account. DOM model labels and
hardcoded lists are not proof. This ledger stores catalogs that are bound to
a host-attested (collector, worker, document, identity_epoch, authentication
revision) observation; anything else is reported as unverified and the
consumer (gateway proof, shell home) must fail closed.
"""
from __future__ import annotations

import time

from sentra_mcp.services.chat_access import _ID, _PRINCIPAL, _validate

_KNOWN_CHATGPT_MODELS = frozenset({
    "gpt-4o", "gpt-4.1", "gpt-5", "gpt-5-mini", "gpt-5-thinking", "o3", "o4-mini",
})
_KNOWN_GEMINI_EFFORTS = frozenset({"flash-lite", "flash", "pro"})


class AccountCatalog:
    """Per-principal/provider catalog snapshots with attestation binding."""

    def __init__(self, store) -> None:
        self.store = store
        db = self.store.connect("chat_access")
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS browser_account_catalogs(
                    principal TEXT NOT NULL, provider TEXT NOT NULL,
                    models TEXT NOT NULL, efforts TEXT NOT NULL,
                    extension_id TEXT NOT NULL, worker TEXT NOT NULL,
                    document_id TEXT NOT NULL, identity_epoch TEXT NOT NULL,
                    authentication_revision INTEGER NOT NULL,
                    observed REAL NOT NULL,
                    PRIMARY KEY(principal,provider));
            """)
        finally:
            db.close()

    def publish(self, *, principal: str, provider: str, models: list[str],
                efforts: list[str], extension_id: str, worker: str,
                document_id: str, identity_epoch: str,
                authentication_revision: int) -> dict:
        _validate("principal", principal, _PRINCIPAL)
        if provider not in {"chatgpt", "gemini"}:
            raise ValueError("catalog provider must be chatgpt or gemini")
        for label, values, known in (("model", models, _KNOWN_CHATGPT_MODELS if provider == "chatgpt" else None),
                                     ("effort", efforts, _KNOWN_GEMINI_EFFORTS if provider == "gemini" else None)):
            if not isinstance(values, list) or not values or len(values) > 64:
                raise ValueError(f"catalog {label} list must hold 1..64 entries")
            for entry in values:
                if not isinstance(entry, str) or not 1 <= len(entry) <= 120:
                    raise ValueError(f"catalog {label} entry must be 1..120 characters")
                if known is not None and entry not in known and provider == "gemini":
                    raise ValueError(f"unknown Gemini effort: {entry}")
        _validate("document identity", document_id, _ID)
        _validate("identity epoch", identity_epoch, _ID)
        if type(authentication_revision) is not int or authentication_revision < 0:
            raise ValueError("authentication revision must be a non-negative integer")
        db = self.store.connect("chat_access")
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO browser_account_catalogs VALUES(?,?,?,?,?,?,?,?,?,?) "
                       "ON CONFLICT(principal,provider) DO UPDATE SET models=excluded.models,"
                       "efforts=excluded.efforts,extension_id=excluded.extension_id,worker=excluded.worker,"
                       "document_id=excluded.document_id,identity_epoch=excluded.identity_epoch,"
                       "authentication_revision=excluded.authentication_revision,observed=excluded.observed",
                       (principal, provider, ",".join(models), ",".join(efforts),
                        extension_id, worker, document_id, identity_epoch,
                        authentication_revision, time.time()))
            db.commit()
            return {"provider": provider, "models": list(models),
                    "efforts": list(efforts), "grants_created": False}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def status(self, principal: str, provider: str, *, max_age_s: float = 600.0) -> dict:
        _validate("principal", principal, _PRINCIPAL)
        if provider not in {"chatgpt", "gemini"}:
            raise ValueError("catalog provider must be chatgpt or gemini")
        if not isinstance(max_age_s, (int, float)) or max_age_s <= 0 or max_age_s > 86400:
            raise ValueError("invalid catalog freshness window")
        db = self.store.connect("chat_access")
        try:
            row = db.execute("SELECT models,efforts,authentication_revision,observed "
                             "FROM browser_account_catalogs WHERE principal=? AND provider=?",
                             (principal, provider)).fetchone()
        finally:
            db.close()
        if row is None:
            return {"verified": False, "models": [], "efforts": [],
                    "reason": "no_attested_catalog"}
        age = max(0.0, time.time() - float(row["observed"]))
        if age > max_age_s:
            return {"verified": False, "models": [], "efforts": [],
                    "reason": "attestation_stale", "age_s": round(age, 2)}
        return {"verified": True,
                "models": str(row["models"]).split(",") if row["models"] else [],
                "efforts": str(row["efforts"]).split(",") if row["efforts"] else [],
                "authentication_revision": int(row["authentication_revision"]),
                "age_s": round(age, 2)}
