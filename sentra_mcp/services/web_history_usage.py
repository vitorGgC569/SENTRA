"""Host-only ChatGPT Web quota observations, NEVER the SENTRA token ledger.

An observation is displayed with age and collector provenance; the actual Web
account attestation is the responsibility of the Chat2 producer/broker.
"""
from __future__ import annotations

import math
import re
import time
from typing import Any

from .control_store import SQLiteControlPlaneStore


class WebQuotaConflict(RuntimeError):
    pass


class WebQuotaObservations:
    def __init__(self, state_root: str, *, store=None, clock=time.time):
        self.store = store or SQLiteControlPlaneStore(state_root)
        self.clock = clock
        with self.store.connect("provider_content") as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS web_quota_observations(
                    owner TEXT NOT NULL, workspace TEXT NOT NULL,
                    account_fingerprint TEXT NOT NULL, quota_bucket TEXT NOT NULL,
                    remaining_percent REAL NOT NULL, resets_at REAL,
                    observed_at REAL NOT NULL, collector_ref TEXT NOT NULL,
                    source TEXT NOT NULL, PRIMARY KEY(
                    owner,workspace,account_fingerprint,quota_bucket));
            """)

    @staticmethod
    def _id(name: str, value: str, maximum: int = 128) -> str:
        if (not isinstance(value,str) or not 1 <= len(value) <= maximum
                or any(ord(c) < 32 for c in value)):
            raise ValueError(f"invalid bounded {name}")
        return value

    def observe(self, owner: str, workspace: str, *, account_fingerprint: str,
                quota_bucket: str, remaining_percent: float, resets_at: float | None,
                observed_at: float, collector_ref: str,
                source: str = "browser_ui") -> dict[str, Any]:
        owner,workspace=self._id("owner",owner),self._id("workspace",workspace,256)
        if (not isinstance(account_fingerprint,str)
                or not re.fullmatch(r"[a-f0-9]{64}",account_fingerprint)):
            raise ValueError("opaque SHA256 account fingerprint required, not email/token")
        bucket=self._id("quota_bucket",quota_bucket,80)
        collector=self._id("collector_ref",collector_ref,160)
        if source != "browser_ui":
            raise ValueError("only explicit browser observations supported")
        if (type(remaining_percent) not in (float,int)
                or not math.isfinite(remaining_percent)
                or not 0 <= remaining_percent <= 100):
            raise ValueError("remaining_percent must be a bounded numeric observation")
        now=self.clock()
        if (type(observed_at) not in (float,int)
                or not math.isfinite(observed_at)
                or not 0 < observed_at <= now + 60):
            raise ValueError("invalid quota observation clock")
        if (resets_at is not None and (
                type(resets_at) not in (int,float)
                or not math.isfinite(resets_at)
                or not 0 < resets_at < observed_at + 366*86400)):
            raise ValueError("invalid observed quota reset")
        values=(owner,workspace,account_fingerprint,bucket,float(remaining_percent),
                resets_at,float(observed_at),collector,source)
        with self.store.connect("provider_content") as db:
            db.execute("BEGIN IMMEDIATE")
            old=db.execute("SELECT * FROM web_quota_observations WHERE "
                           "owner=? AND workspace=? AND account_fingerprint=? "
                           "AND quota_bucket=?",values[:4]).fetchone()
            if old and float(old["observed_at"]) > observed_at:
                raise WebQuotaConflict("out-of-order quota observation rejected")
            if old and float(old["observed_at"]) == observed_at and (
                    old["remaining_percent"] != remaining_percent
                    or old["collector_ref"] != collector
                    or old["resets_at"] != resets_at):
                raise WebQuotaConflict("same-timestamp quota conflict")
            db.execute("INSERT INTO web_quota_observations VALUES(?,?,?,?,?,?,?,?,?) "
                       "ON CONFLICT(owner,workspace,account_fingerprint,quota_bucket) "
                       "DO UPDATE SET remaining_percent=excluded.remaining_percent,"
                       "resets_at=excluded.resets_at,observed_at=excluded.observed_at,"
                       "collector_ref=excluded.collector_ref,source=excluded.source",values)
        return self.latest(owner,workspace,account_fingerprint,bucket)

    def latest(self, owner: str, workspace: str, account_fingerprint: str,
               quota_bucket: str, *, max_age_s: int = 600) -> dict[str, Any]:
        if type(max_age_s) is not int or not 1 <= max_age_s <= 3600:
            raise ValueError("bounded freshness required")
        owner,workspace=self._id("owner",owner),self._id("workspace",workspace,256)
        with self.store.connect("provider_content") as db:
            row=db.execute("SELECT * FROM web_quota_observations WHERE "
                           "owner=? AND workspace=? AND account_fingerprint=? "
                           "AND quota_bucket=?",
                           (owner,workspace,account_fingerprint,quota_bucket)).fetchone()
        if row is None:
            return {"status":"unknown","source":"browser_ui",
                    "trusted_account_proof":False,
                    "sentra_token_ledger_equivalent":False}
        age=max(0.0,self.clock()-row["observed_at"])
        freshness = "fresh" if age <= max_age_s else "stale"
        reset_expired = row["resets_at"] is not None and row["resets_at"] <= self.clock()
        return {"status":"stale" if reset_expired else freshness,
                "account_fingerprint":account_fingerprint,
                "quota_bucket":row["quota_bucket"],
                "remaining_percent":row["remaining_percent"],
                "resets_at":row["resets_at"],"observed_at":row["observed_at"],
                "age_seconds":age,"source":row["source"],
                "collector_ref":row["collector_ref"],
                "trusted_account_proof":False,
                "sentra_token_ledger_equivalent":False}
