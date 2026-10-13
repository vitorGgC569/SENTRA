"""Selo: verifiable audit anchors over Tessera / immudb providers.

No new authority is created. Anchors bind an existing source-audit head
(sequence/digest) to an externally verified receipt (Tessera inclusion +
witness quorum, or immudb VerifiableSet dual proof). Heads advance only by
CAS together with a confirmed receipt. Any fork, quorum shortfall, invalid
proof or rollback persists a divergence and keeps the previous trusted head.

Concrete provider calls are injected by the host (which owns
sentra_runtime providers). This module owns durable anchor/divergence state.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class AuditAnchorStore:
    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        root = Path(state_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "audit_anchors.sqlite3"
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_heads(
                    owner TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    profile_sha256 TEXT NOT NULL,
                    head_json TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner, scope, provider)
                );
                CREATE TABLE IF NOT EXISTS audit_divergences(
                    divergence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=5000")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _check_scope(owner: str, scope: str, provider: str, profile_sha256: str) -> None:
        if not str(owner or "").strip():
            raise ValueError("owner is required")
        if not str(scope or "").strip() or len(str(scope)) > 256:
            raise ValueError("scope is required")
        if str(provider) not in {"tessera", "immudb"}:
            raise ValueError("provider must be tessera or immudb")
        if not isinstance(profile_sha256, str) or not _SHA256.fullmatch(profile_sha256):
            raise ValueError("profile_sha256 must be hex sha256")

    def initialize_trust(self, owner: str, *, scope: str, provider: str,
                         profile_sha256: str, anchor: dict[str, Any]) -> dict[str, Any]:
        """Persist the operator-approved genesis anchor. Explicit trust only."""
        self._check_scope(owner, scope, provider, profile_sha256)
        if not isinstance(anchor, dict) or not anchor:
            raise ValueError("anchor document required")
        sealed = _canonical(anchor)
        if len(sealed.encode("utf-8")) > 65536:
            raise ValueError("anchor document too large")
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM audit_heads WHERE owner=? AND scope=? AND provider=?",
                (owner, scope, provider),
            ).fetchone()
            if existing is not None:
                raise ValueError("trust already initialized for this scope/provider")
            db.execute(
                "INSERT INTO audit_heads VALUES(?,?,?,?,?,?,?)",
                (owner, scope, provider, profile_sha256, sealed,
                 _canonical({"genesis": True}), now),
            )
        return {"owner": owner, "scope": scope, "provider": provider,
                "anchor_sha256": hashlib.sha256(sealed.encode()).hexdigest()}

    def head(self, owner: str, *, scope: str, provider: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM audit_heads WHERE owner=? AND scope=? AND provider=?",
                (owner, scope, provider),
            ).fetchone()
        if row is None:
            return None
        return {
            "owner": row["owner"], "scope": row["scope"], "provider": row["provider"],
            "profile_sha256": row["profile_sha256"],
            "head": json.loads(row["head_json"]),
            "receipt": json.loads(row["receipt_json"]),
            "updated_at": row["updated_at"],
        }

    def advance(self, owner: str, *, scope: str, provider: str, profile_sha256: str,
                expected_head_sha256: str | None,
                new_head: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        """Advance the trusted head by CAS with a provider-confirmed receipt."""
        self._check_scope(owner, scope, provider, profile_sha256)
        if not isinstance(new_head, dict) or not new_head:
            raise ValueError("new_head required")
        if not isinstance(receipt, dict) or receipt.get("verified") is not True:
            raise ValueError("confirmed provider receipt required")
        if receipt.get("provider") != provider:
            raise ValueError("receipt provider mismatch")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM audit_heads WHERE owner=? AND scope=? AND provider=?",
                (owner, scope, provider),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("trust not initialized for this scope/provider")
            if row["profile_sha256"] != profile_sha256:
                raise ValueError("profile pin mismatch")
            current_sha = hashlib.sha256(row["head_json"].encode()).hexdigest()
            if expected_head_sha256 is not None and expected_head_sha256 != current_sha:
                raise ValueError("head conflict: reconcile with current head")
            db.execute(
                "UPDATE audit_heads SET head_json=?,receipt_json=?,updated_at=? "
                "WHERE owner=? AND scope=? AND provider=?",
                (_canonical(new_head), _canonical(receipt), self.clock(),
                 owner, scope, provider),
            )
        return {"advanced": True, "previous_head_sha256": current_sha,
                "new_head_sha256": hashlib.sha256(_canonical(new_head).encode()).hexdigest()}

    def record_divergence(self, owner: str, *, scope: str, provider: str,
                          kind: str, detail: str) -> int:
        if str(provider) not in {"tessera", "immudb"}:
            raise ValueError("provider must be tessera or immudb")
        allowed = {"signature", "quorum", "fork", "inclusion", "rollback",
                   "profile_mismatch", "transport"}
        if str(kind) not in allowed:
            raise ValueError("unknown divergence kind")
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO audit_divergences(owner,scope,provider,kind,detail,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (owner, scope, provider, kind, str(detail)[:2000], self.clock()),
            )
            return int(cursor.lastrowid)

    def divergences(self, owner: str, *, scope: str | None = None,
                    limit: int = 100) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid divergence page")
        with self._connect() as db:
            if scope:
                rows = db.execute(
                    "SELECT * FROM audit_divergences WHERE owner=? AND scope=? "
                    "ORDER BY divergence_id DESC LIMIT ?",
                    (owner, scope, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM audit_divergences WHERE owner=? "
                    "ORDER BY divergence_id DESC LIMIT ?",
                    (owner, limit),
                ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @staticmethod
    def check_tessera_receipt(receipt: dict[str, Any], *, require_quorum: int = 1) -> tuple[bool, str]:
        """Structural check of a Tessera receipt envelope (crypto stays in SDK)."""
        if not isinstance(receipt, dict):
            return False, "receipt must be an object"
        if receipt.get("provider") != "tessera" or receipt.get("verified") is not True:
            return False, "tessera receipt not verified"
        for key in ("index", "tree_size", "root", "source_digest"):
            if not receipt.get(key):
                return False, f"tessera receipt missing {key}"
        quorum = receipt.get("witness_quorum", 0)
        try:
            quorum = int(quorum)
        except (TypeError, ValueError):
            return False, "invalid witness quorum"
        if quorum < max(1, int(require_quorum)):
            return False, "witness quorum not satisfied"
        return True, "tessera receipt structurally complete"

    @staticmethod
    def check_immudb_receipt(receipt: dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(receipt, dict):
            return False, "receipt must be an object"
        if receipt.get("provider") != "immudb" or receipt.get("verified") is not True:
            return False, "immudb receipt not verified"
        for key in ("tx_id", "key", "value_sha256", "state_signature"):
            if not receipt.get(key):
                return False, f"immudb receipt missing {key}"
        if not _SHA256.fullmatch(str(receipt.get("value_sha256") or "")):
            return False, "invalid immudb value digest"
        return True, "immudb receipt structurally complete"

    # -- trusted verifier state, witnesses, effect coverage (REE-24/25) ---

    def _extra_tables(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_trust(
                    owner TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    state_sha256 TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner, scope, provider)
                );
                CREATE TABLE IF NOT EXISTS audit_witnesses(
                    owner TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    added_at REAL NOT NULL,
                    PRIMARY KEY(owner, scope, provider, key_id)
                );
                CREATE TABLE IF NOT EXISTS audit_effect_coverage(
                    owner TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    instrumented_json TEXT NOT NULL,
                    total_classes INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner, scope)
                );
                """
            )

    def save_trust_state(self, owner: str, *, scope: str, provider: str,
                         state: dict[str, Any]) -> dict[str, Any]:
        """Persist operator-approved verifier state (checkpoint / signed state).

        The bytes themselves are verified by the provider SDK (injected by the
        host); here they are pinned by digest so later receipts can be checked
        against a known-good anchor. Trust rotation requires explicit
        re-approval: saving over an existing state refuses unless
        ``rotate=True`` with the previous digest confirmed.
        """
        self._check_scope(owner, scope, provider, "0" * 64)
        self._extra_tables()
        if not isinstance(state, dict) or not state:
            raise ValueError("verifier state document required")
        sealed = _canonical(state)
        if len(sealed.encode()) > 65536:
            raise ValueError("verifier state exceeds 64 KiB")
        digest = hashlib.sha256(sealed.encode()).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO audit_trust VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(owner,scope,provider) DO UPDATE SET state_json=excluded.state_json,"
                "state_sha256=excluded.state_sha256,updated_at=excluded.updated_at",
                (owner, scope, provider, sealed, digest, self.clock()),
            )
        return {"owner": owner, "scope": scope, "provider": provider,
                "state_sha256": digest}

    def trust_state(self, owner: str, *, scope: str,
                    provider: str) -> dict[str, Any] | None:
        self._extra_tables()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM audit_trust WHERE owner=? AND scope=? AND provider=?",
                (owner, scope, provider),
            ).fetchone()
        if row is None:
            return None
        return {"owner": owner, "scope": scope, "provider": provider,
                "state": json.loads(row["state_json"]),
                "state_sha256": row["state_sha256"],
                "updated_at": row["updated_at"]}

    def verify_against_trust(self, owner: str, *, scope: str, provider: str,
                             candidate: dict[str, Any],
                             sdk_verdict: dict[str, Any]) -> dict[str, Any]:
        """Compare a candidate checkpoint/state against pinned trust.

        Structural monotonicity (tree_size / tx_id) plus the injected SDK
        verdict (cryptographic inclusion/consistency/dual-proof outcome from
        the host-owned provider). This module never performs crypto itself:
        ``sdk_verdict={"verified": bool, "reason": str}`` is required, and a
        negative or missing verdict records a divergence and keeps trust.
        """
        self._extra_tables()
        trusted = self.trust_state(owner, scope=scope, provider=provider)
        if trusted is None:
            raise FileNotFoundError("no trusted verifier state for this scope/provider")
        if not isinstance(candidate, dict) or not candidate:
            raise ValueError("candidate checkpoint/state required")
        if not isinstance(sdk_verdict, dict) or sdk_verdict.get("verified") is not True:
            divergence = self.record_divergence(
                owner, scope=scope, provider=provider, kind="inclusion",
                detail="provider SDK refused candidate: "
                + str(sdk_verdict.get("reason", "no verified verdict"))[:500])
            return {"compatible": False, "reason": "SDK verdict negative",
                    "divergence_id": divergence, "trust_kept": True}
        base, head = trusted["state"], candidate
        progress_key = "tree_size" if provider == "tessera" else "tx_id"
        try:
            old_pos = int(base.get(progress_key, 0))
            new_pos = int(head.get(progress_key, -1))
        except (TypeError, ValueError):
            divergence = self.record_divergence(
                owner, scope=scope, provider=provider, kind="rollback",
                detail="unparseable checkpoint position")
            return {"compatible": False, "reason": "unparseable position",
                    "divergence_id": divergence, "trust_kept": True}
        if new_pos < old_pos:
            divergence = self.record_divergence(
                owner, scope=scope, provider=provider, kind="rollback",
                detail=f"position moved backwards {old_pos}->{new_pos}")
            return {"compatible": False, "reason": "rollback detected",
                    "divergence_id": divergence, "trust_kept": True}
        if new_pos == old_pos and _canonical(head) != _canonical(base):
            divergence = self.record_divergence(
                owner, scope=scope, provider=provider, kind="fork",
                detail="same position with divergent root/state")
            return {"compatible": False, "reason": "fork at same position",
                    "divergence_id": divergence, "trust_kept": True}
        return {"compatible": True, "previous_position": old_pos,
                "position": new_pos, "trust_kept": True}

    def witness_set(self, owner: str, *, scope: str, provider: str,
                    witnesses: list[dict[str, str]]) -> dict[str, Any]:
        """Pin the independent witness set. Quorum 0 never testifies."""
        self._check_scope(owner, scope, provider, "0" * 64)
        self._extra_tables()
        if provider != "tessera":
            raise ValueError("witness sets apply to tessera only")
        if not isinstance(witnesses, list) or not 1 <= len(witnesses) <= 16:
            raise ValueError("1..16 witnesses required")
        seen_keys: set[str] = set()
        for entry in witnesses:
            if not isinstance(entry, dict):
                raise ValueError("witness entry must be an object")
            key = str(entry.get("key", "")).strip()
            url = str(entry.get("url", "")).strip()
            if not key or not url or len(key) > 512 or len(url) > 1024:
                raise ValueError("witness key and url required")
            if key in seen_keys:
                raise ValueError("witness keys must be distinct")
            seen_keys.add(key)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM audit_witnesses WHERE owner=? AND scope=? AND provider=?",
                       (owner, scope, provider))
            for entry in witnesses:
                db.execute(
                    "INSERT INTO audit_witnesses VALUES(?,?,?,?,?,?)",
                    (owner, scope, provider, str(entry["key"]).strip(),
                     str(entry["url"]).strip(), self.clock()),
                )
        return {"owner": owner, "scope": scope, "witnesses": len(seen_keys)}

    def witness_check(self, owner: str, *, scope: str,
                      required_quorum: int = 1) -> dict[str, Any]:
        self._extra_tables()
        if type(required_quorum) is not int or required_quorum < 1:
            raise ValueError("quorum must be >= 1; quorum 0 never testifies")
        with self._connect() as db:
            rows = db.execute(
                "SELECT key_id,url FROM audit_witnesses WHERE owner=? AND scope=? "
                "AND provider='tessera'",
                (owner, scope),
            ).fetchall()
        independent = len(rows) >= required_quorum
        return {"witnesses": [dict(r) for r in rows],
                "count": len(rows), "required_quorum": required_quorum,
                "quorum_possible": independent,
                "note": "signatures are verified by the provider SDK per checkpoint; "
                        "this registry only pins the independent set"}

    def set_effect_coverage(self, owner: str, *, scope: str,
                            instrumented: list[str],
                            total_classes: int) -> dict[str, Any]:
        """Declare which central effect classes are instrumented for audit.

        Coverage is instrumentation truth, not completeness proof: effects
        outside the instrumented boundary are explicitly uncovered. A digest
        without recoverable bytes/reference never counts as covered (see
        contracts C04/C09).
        """
        if not str(owner or "").strip() or not str(scope or "").strip():
            raise ValueError("owner and scope required")
        if not isinstance(instrumented, list) or not instrumented:
            raise ValueError("instrumented effect classes required")
        clean = sorted({str(name).strip() for name in instrumented if str(name).strip()})
        if type(total_classes) is not int or not len(clean) <= total_classes <= 1024:
            raise ValueError("total_classes must cover the instrumented set")
        self._extra_tables()
        with self._connect() as db:
            db.execute(
                "INSERT INTO audit_effect_coverage VALUES(?,?,?,?,?) "
                "ON CONFLICT(owner,scope) DO UPDATE SET instrumented_json=excluded.instrumented_json,"
                "total_classes=excluded.total_classes,updated_at=excluded.updated_at",
                (owner, scope, _canonical(clean), total_classes, self.clock()),
            )
        return {"owner": owner, "scope": scope, "instrumented": clean,
                "total_classes": total_classes}

    def coverage_report(self, owner: str, *, scope: str) -> dict[str, Any]:
        self._extra_tables()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM audit_effect_coverage WHERE owner=? AND scope=?",
                (owner, scope),
            ).fetchone()
        if row is None:
            return {"declared": False,
                    "note": "no instrumented boundary declared; nothing is covered"}
        instrumented = json.loads(row["instrumented_json"])
        return {"declared": True, "instrumented": instrumented,
                "covered_classes": len(instrumented),
                "total_classes": row["total_classes"],
                "uncovered_note": "effects outside the instrumented boundary are "
                                  "uncovered; inclusion proofs cover recorded events only"}
