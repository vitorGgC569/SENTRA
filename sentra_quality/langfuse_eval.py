"""Selo: Langfuse-format eval store (REE-27 amplified, local-first).

Implements the amplified Langfuse shape, not just OTLP tracing:
- prompts with version/labels/config (PromptDomainSchema),
- datasets with expected input/output (DatasetRunItemSchema input/output fields),
- dataset run <-> trace linkage (trace_id/observation_id per run item),
- typed scores NUMERIC/CATEGORICAL/BOOLEAN/CORRECTION/TEXT (score validation),
- human corrections (author + correction_of),
- linkage to central QualityGate (recorded reference, never recomputed here)
  and central cost records (referenced ids, never a second budget).

Scores are advisory evidence for comparison; they never replace the
QualityGate verdict nor authoritative budget accounting. A local comparison
(prompts/providers over the same dataset version) reports objective
success, cost, latency and per-task regressions.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SCORE_TYPES = {"NUMERIC", "CATEGORICAL", "BOOLEAN", "CORRECTION", "TEXT"}
_TEXT_MAX = 8000


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _score(value: Any, data_type: str, *, categories: list[str] | None = None,
           min_value: float | None = None, max_value: float | None = None) -> Any:
    if data_type == "NUMERIC":
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)):
            raise ValueError("NUMERIC score must be finite")
        result = float(value)
        if min_value is not None and result < float(min_value):
            raise ValueError("score below configured minimum")
        if max_value is not None and result > float(max_value):
            raise ValueError("score above configured maximum")
        return result
    if data_type == "CATEGORICAL":
        if not isinstance(value, str) or not value:
            raise ValueError("CATEGORICAL score must be a non-empty label")
        if not categories or value not in categories:
            raise ValueError("score label not in configured categories")
        return value
    if data_type == "BOOLEAN":
        if type(value) not in {bool, int} or value not in (0, 1, True, False):
            raise ValueError("BOOLEAN score must be 0 or 1")
        return 1 if value in (1, True) else 0
    if data_type in {"CORRECTION", "TEXT"}:
        if not isinstance(value, str) or not 1 <= len(value) <= _TEXT_MAX:
            raise ValueError(f"{data_type} score must be 1..{_TEXT_MAX} chars")
        return value
    raise ValueError("unknown score data type")


class LangfuseEvalStore:
    def __init__(self, state_root: Path | str, *, clock=time.time) -> None:
        root = Path(state_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "selo_langfuse_eval.sqlite3"
        self.clock = clock
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS lf_prompts(
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    labels_json TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    prompt_sha256 TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(owner, name, version)
                );
                CREATE TABLE IF NOT EXISTS lf_datasets(
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    environment_json TEXT NOT NULL,
                    provider TEXT,
                    model TEXT,
                    tools_json TEXT NOT NULL,
                    verifier_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(owner, name, version)
                );
                CREATE TABLE IF NOT EXISTS lf_dataset_items(
                    owner TEXT NOT NULL,
                    dataset_name TEXT NOT NULL,
                    dataset_version INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    expected_json TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    expected_sha256 TEXT NOT NULL,
                    PRIMARY KEY(owner, dataset_name, dataset_version, item_id)
                );
                CREATE TABLE IF NOT EXISTS lf_dataset_runs(
                    owner TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    dataset_name TEXT NOT NULL,
                    dataset_version INTEGER NOT NULL,
                    prompt_name TEXT NOT NULL,
                    prompt_version INTEGER NOT NULL,
                    provider TEXT,
                    model TEXT,
                    config_json TEXT NOT NULL,
                    gate_json TEXT,
                    cost_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(owner, run_id)
                );
                CREATE TABLE IF NOT EXISTS lf_run_items(
                    owner TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    trace_id TEXT,
                    observation_id TEXT,
                    output_json TEXT,
                    output_sha256 TEXT,
                    error TEXT,
                    latency_ms REAL,
                    cost REAL,
                    PRIMARY KEY(owner, run_id, item_id)
                );
                CREATE TABLE IF NOT EXISTS lf_scores(
                    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    correction_of INTEGER,
                    author TEXT NOT NULL,
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
    def _name(value: str, field: str) -> str:
        text = str(value or "").strip()
        if not _NAME.fullmatch(text):
            raise ValueError(f"invalid {field}")
        return text

    # -- prompts --------------------------------------------------------

    def prompt_create(self, owner: str, *, name: str, prompt: Any,
                      labels: list[str] | None = None,
                      config: dict[str, Any] | None = None,
                      commit_message: str | None = None) -> dict[str, Any]:
        owner = str(owner or "").strip()
        name = self._name(name, "prompt name")
        if not owner:
            raise ValueError("owner is required")
        sealed = _canonical({"prompt": prompt, "config": dict(config or {})})
        if len(sealed.encode()) > 256 * 1024:
            raise ValueError("prompt+config exceeds 256 KiB")
        clean_labels = sorted({str(label).strip()[:64] for label in (labels or [])
                               if str(label).strip()})
        if len(clean_labels) > 32:
            raise ValueError("too many prompt labels")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT MAX(version) AS top FROM lf_prompts WHERE owner=? AND name=?",
                (owner, name),
            ).fetchone()
            version = int(row["top"] or 0) + 1
            db.execute(
                "INSERT INTO lf_prompts VALUES(?,?,?,?,?,?,?,?)",
                (owner, name, version, _canonical(clean_labels),
                 _canonical(dict(config or {})), _digest(sealed), 0, self.clock()),
            )
        return {"name": name, "version": version, "labels": clean_labels,
                "prompt_sha256": _digest(sealed),
                "commit_message": (commit_message or "")[:512]}

    def prompt_activate(self, owner: str, *, name: str, version: int) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute(
                "SELECT 1 FROM lf_prompts WHERE owner=? AND name=? AND version=?",
                (owner, name, version),
            ).fetchone()
            if exists is None:
                raise FileNotFoundError("prompt version not found")
            db.execute("UPDATE lf_prompts SET active=0 WHERE owner=? AND name=?",
                       (owner, name))
            db.execute("UPDATE lf_prompts SET active=1 WHERE owner=? AND name=? AND version=?",
                       (owner, name, version))
        return {"name": name, "active_version": version}

    # -- datasets -------------------------------------------------------

    def dataset_create(self, owner: str, *, name: str,
                       environment: dict[str, Any] | None = None,
                       provider: str | None = None, model: str | None = None,
                       tools: list[str] | None = None,
                       verifier: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = str(owner or "").strip()
        name = self._name(name, "dataset name")
        if not owner:
            raise ValueError("owner is required")
        clean_tools = sorted({str(tool).strip()[:128] for tool in (tools or [])
                              if str(tool).strip()})
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT MAX(version) AS top FROM lf_datasets WHERE owner=? AND name=?",
                (owner, name),
            ).fetchone()
            version = int(row["top"] or 0) + 1
            db.execute(
                "INSERT INTO lf_datasets VALUES(?,?,?,?,?,?,?,?,?)",
                (owner, name, version, _canonical(dict(environment or {})),
                 provider, model, _canonical(clean_tools),
                 _canonical(dict(verifier or {})), self.clock()),
            )
        return {"name": name, "version": version, "provider": provider,
                "model": model, "tools": clean_tools}

    def dataset_item_add(self, owner: str, *, dataset_name: str, dataset_version: int,
                         item_id: str, input: Any, expected_output: Any) -> dict[str, Any]:
        dataset_name = self._name(dataset_name, "dataset name")
        item_id = self._name(item_id, "item id")
        sealed_in = _canonical(input)
        sealed_out = _canonical(expected_output)
        if len(sealed_in.encode()) > 65536 or len(sealed_out.encode()) > 65536:
            raise ValueError("dataset item input/output exceeds 64 KiB")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute(
                "SELECT 1 FROM lf_datasets WHERE owner=? AND name=? AND version=?",
                (owner, dataset_name, dataset_version),
            ).fetchone()
            if exists is None:
                raise FileNotFoundError("dataset version not found")
            db.execute(
                "INSERT OR REPLACE INTO lf_dataset_items VALUES(?,?,?,?,?,?,?,?)",
                (owner, dataset_name, dataset_version, item_id, sealed_in,
                 sealed_out, _digest(sealed_in), _digest(sealed_out)),
            )
        return {"dataset": dataset_name, "version": dataset_version,
                "item_id": item_id, "input_sha256": _digest(sealed_in),
                "expected_sha256": _digest(sealed_out)}

    # -- runs -----------------------------------------------------------

    def run_create(self, owner: str, *, dataset_name: str, dataset_version: int,
                   prompt_name: str, prompt_version: int,
                   provider: str | None = None, model: str | None = None,
                   config: dict[str, Any] | None = None,
                   gate: dict[str, Any] | None = None,
                   cost: dict[str, Any] | None = None) -> dict[str, Any]:
        run_id = "dset-run-" + uuid.uuid4().hex
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for table, keys in (
                ("lf_datasets", (dataset_name, dataset_version)),
                ("lf_prompts", (prompt_name, prompt_version)),
            ):
                name_col = "name"
                row = db.execute(
                    f"SELECT 1 FROM {table} WHERE owner=? AND {name_col}=? AND version=?",
                    (owner, keys[0], keys[1]),
                ).fetchone()
                if row is None:
                    raise FileNotFoundError(f"{table} version not found")
            if gate is not None and not isinstance(gate, dict):
                raise ValueError("gate reference must be an object")
            db.execute(
                "INSERT INTO lf_dataset_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (owner, run_id, dataset_name, dataset_version, prompt_name,
                 prompt_version, provider, model, _canonical(dict(config or {})),
                 _canonical(gate) if gate is not None else None,
                 _canonical(dict(cost or {})), self.clock()),
            )
        return {"run_id": run_id, "dataset": dataset_name,
                "dataset_version": dataset_version, "prompt": prompt_name,
                "prompt_version": prompt_version, "scores_advisory": True}

    def run_item_record(self, owner: str, *, run_id: str, item_id: str,
                        output: Any = None, error: str | None = None,
                        trace_id: str | None = None,
                        observation_id: str | None = None,
                        latency_ms: float | None = None,
                        cost: float | None = None) -> dict[str, Any]:
        sealed = _canonical(output) if output is not None else None
        if sealed is not None and len(sealed.encode()) > 65536:
            raise ValueError("run output exceeds 64 KiB")
        for value, field in ((latency_ms, "latency_ms"), (cost, "cost")):
            if value is not None and (
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)) or float(value) < 0):
                raise ValueError(f"{field} must be non-negative finite")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute(
                "SELECT dataset_name,dataset_version FROM lf_dataset_runs "
                "WHERE owner=? AND run_id=?", (owner, run_id),
            ).fetchone()
            if run is None:
                raise FileNotFoundError("dataset run not found")
            known = db.execute(
                "SELECT 1 FROM lf_dataset_items WHERE owner=? AND dataset_name=? "
                "AND dataset_version=? AND item_id=?",
                (owner, run["dataset_name"], run["dataset_version"], item_id),
            ).fetchone()
            if known is None:
                raise FileNotFoundError("dataset item not in this run version")
            db.execute(
                "INSERT OR REPLACE INTO lf_run_items VALUES(?,?,?,?,?,?,?,?,?,?)",
                (owner, run_id, item_id, trace_id, observation_id, sealed,
                 _digest(sealed) if sealed is not None else None,
                 (error or "")[:2000] or None,
                 float(latency_ms) if latency_ms is not None else None,
                 float(cost) if cost is not None else None),
            )
        return {"run_id": run_id, "item_id": item_id,
                "output_sha256": _digest(sealed) if sealed is not None else None,
                "trace_id": trace_id}

    def score_record(self, owner: str, *, run_id: str, item_id: str, name: str,
                     data_type: str, value: Any,
                     categories: list[str] | None = None,
                     min_value: float | None = None,
                     max_value: float | None = None,
                     correction_of: int | None = None,
                     author: str = "system") -> dict[str, Any]:
        data_type = str(data_type or "").upper()
        if data_type not in _SCORE_TYPES:
            raise ValueError("unknown score data type")
        name = self._name(name, "score name")
        author = str(author or "").strip()[:128] or "system"
        checked = _score(value, data_type, categories=categories,
                         min_value=min_value, max_value=max_value)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            known = db.execute(
                "SELECT 1 FROM lf_run_items WHERE owner=? AND run_id=? AND item_id=?",
                (owner, run_id, item_id),
            ).fetchone()
            if known is None:
                raise FileNotFoundError("run item not recorded")
            if correction_of is not None:
                base = db.execute(
                    "SELECT score_id FROM lf_scores WHERE score_id=? AND owner=?",
                    (correction_of, owner),
                ).fetchone()
                if base is None:
                    raise FileNotFoundError("corrected score not found")
            cursor = db.execute(
                "INSERT INTO lf_scores(owner,run_id,item_id,name,data_type,value_json,"
                "correction_of,author,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (owner, run_id, item_id, name, data_type, _canonical(checked),
                 correction_of, author, self.clock()),
            )
        return {"score_id": int(cursor.lastrowid), "data_type": data_type,
                "human_correction": correction_of is not None,
                "advisory": True}

    # -- comparison -----------------------------------------------------

    def compare_runs(self, owner: str, *, run_a: str, run_b: str) -> dict[str, Any]:
        with self._connect() as db:
            runs = {}
            for run_id in (run_a, run_b):
                row = db.execute(
                    "SELECT * FROM lf_dataset_runs WHERE owner=? AND run_id=?",
                    (owner, run_id),
                ).fetchone()
                if row is None:
                    raise FileNotFoundError(f"dataset run not found: {run_id}")
                runs[run_id] = dict(row)
            if (runs[run_a]["dataset_name"], runs[run_a]["dataset_version"]) != \
               (runs[run_b]["dataset_name"], runs[run_b]["dataset_version"]):
                raise ValueError("runs cover different dataset versions")
            items = db.execute(
                "SELECT item_id FROM lf_dataset_items WHERE owner=? AND dataset_name=? "
                "AND dataset_version=?",
                (owner, runs[run_a]["dataset_name"], runs[run_a]["dataset_version"]),
            ).fetchall()
            per_item = []
            for entry in items:
                item_id = entry["item_id"]
                sides = {}
                for run_id in (run_a, run_b):
                    record = db.execute(
                        "SELECT output_sha256,error,latency_ms,cost FROM lf_run_items "
                        "WHERE owner=? AND run_id=? AND item_id=?",
                        (owner, run_id, item_id),
                    ).fetchone()
                    scores = db.execute(
                        "SELECT name,data_type,value_json,author,correction_of FROM lf_scores "
                        "WHERE owner=? AND run_id=? AND item_id=? ORDER BY score_id",
                        (owner, run_id, item_id),
                    ).fetchall()
                    sides[run_id] = {
                        "recorded": record is not None,
                        "output_sha256": record["output_sha256"] if record else None,
                        "error": record["error"] if record else None,
                        "latency_ms": record["latency_ms"] if record else None,
                        "cost": record["cost"] if record else None,
                        "scores": [{**dict(s), "value": json.loads(s["value_json"])}
                                   for s in scores],
                    }
                expected = db.execute(
                    "SELECT expected_sha256 FROM lf_dataset_items WHERE owner=? "
                    "AND dataset_name=? AND dataset_version=? AND item_id=?",
                    (owner, runs[run_a]["dataset_name"],
                     runs[run_a]["dataset_version"], item_id),
                ).fetchone()
                success = {run_id: bool(sides[run_id]["output_sha256"]
                                        == expected["expected_sha256"])
                           for run_id in (run_a, run_b)}
                per_item.append({
                    "item_id": item_id,
                    "success": success,
                    "regression": success[run_a] and not success[run_b],
                    "fixed": success[run_b] and not success[run_a],
                    "latency_ms": {r: sides[r]["latency_ms"] for r in (run_a, run_b)},
                    "cost": {r: sides[r]["cost"] for r in (run_a, run_b)},
                    "scores": {r: sides[r]["scores"] for r in (run_a, run_b)},
                })
        regressions = [p["item_id"] for p in per_item if p["regression"]]
        fixes = [p["item_id"] for p in per_item if p["fixed"]]
        return {
            "dataset": runs[run_a]["dataset_name"],
            "dataset_version": runs[run_a]["dataset_version"],
            "run_a": {"run_id": run_a, "prompt": runs[run_a]["prompt_name"],
                      "prompt_version": runs[run_a]["prompt_version"],
                      "provider": runs[run_a]["provider"], "model": runs[run_a]["model"]},
            "run_b": {"run_id": run_b, "prompt": runs[run_b]["prompt_name"],
                      "prompt_version": runs[run_b]["prompt_version"],
                      "provider": runs[run_b]["provider"], "model": runs[run_b]["model"]},
            "items": per_item,
            "success_a": sum(1 for p in per_item if p["success"][run_a]),
            "success_b": sum(1 for p in per_item if p["success"][run_b]),
            "regressions": regressions,
            "fixed": fixes,
            "scores_advisory": True,
            "quality_gate_authoritative": True,
        }
