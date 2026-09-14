"""SENTRA program memory: persistent cross-run memory + seat-rotation briefs.

Persisted under ``<workspace>/memory/`` as atomic JSON files (same tmp+fsync+
``os.replace`` discipline as :mod:`orchestrator.persistence`)::

    memory/adrs.json        list of ADR dicts
    memory/lessons.json     list of lesson dicts (evidence mandatory)
    memory/candidates.json  dict task_type -> list of attempt dicts

JSON formats (all UTF-8, LF, ``indent=2``)::

    adrs.json:       [{"id": "ADR-0007", "date": "2026-09-14T12:00:00Z",
                       "decision": "...", "rationale": "...",
                       "refs": {"run_id": "run-abc", "task_id": "T-1"}}]
    lessons.json:    [{"id": "LES-0003", "date": "...Z",
                       "text": "...", "evidence": "run-abc ... engine.py:123"}]
    candidates.json: {"bugfix": [{"patch_ref": "...", "outcome": "SUCCESS",
                                  "run_id": "...", "task_id": "...",
                                  "notes": "...", "date": "...Z"}]}

Only the standard library is used. Reads never raise: missing files yield an
empty functional store; corrupted files (bad JSON, bad UTF-8, wrong shape)
are quarantined next to the original as ``<name>.corrupt-<unixtime>.bak``
and the store continues empty for that file. Writes raise ``ValueError`` on
oversized records / full files (anti-explosion, loud on write).

Integration spec (for the integrator wiring the engine later; this module
performs NO sends, NO rotation by itself):

* after a master/operator decision sticks -> ``record_adr``.
* after a validated finding with a concrete pointer -> ``record_lesson``.
* after every task settles (pass/fail/reject) -> ``record_candidate``.
* before planning a new task -> ``recall`` (lexical overlap, deterministic).
* when the chat approaches the ~20000 char message ceiling ->
  ``compact_brief`` and carry only the brief forward.
* to continue in a fresh chat -> ``build_rotation_brief`` and post its
  return value as the FIRST user message of the NEW chat (see its docstring
  for the rotation protocol; pool/engine rotation itself is owned by another
  workstream).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

MEMORY_DIRNAME = "memory"
ADRS_FILENAME = "adrs.json"
LESSONS_FILENAME = "lessons.json"
CANDIDATES_FILENAME = "candidates.json"

# Anti-explosion caps (loud ValueError on write, never silent growth).
MAX_RECORD_CHARS = 4000
MAX_REF_CHARS = 500
MAX_REFS_ITEMS = 32
MAX_ADRS = 500
MAX_LESSONS = 1000
MAX_CANDIDATE_TYPES = 200
MAX_CANDIDATES_TOTAL = 2000
MAX_CANDIDATES_PER_TYPE = 200
MAX_FILE_BYTES = 1_000_000

DEFAULT_RECALL_LIMIT = 5
MAX_RECALL_LIMIT = 50
DEFAULT_COMPACT_CHARS = 8000
DEFAULT_ROTATION_CHARS = 20000
SNIPPET_CHARS = 500
TRUNCATION_MARKER = "\n[...truncado para caber no teto...]"

_RUN_RE = re.compile(
    r"run(?:[\s_\-]*id)?[\s_\-:]*[A-Za-z0-9][A-Za-z0-9_\-.]*", re.IGNORECASE
)
_FILELINE_RE = re.compile(r"[A-Za-z0-9_./\\\-]+\.[A-Za-z]{1,10}:\d+")
_EVENT_RE = re.compile(
    r"event|events\.jsonl|TASK_[A-Z_]+|CANDIDATE_[A-Z_]+|VALIDATION_[A-Z_]+|"
    r"QUALITY_GATE|REPAIR_[A-Z_]+|conversations\.json|conversation",
    re.IGNORECASE,
)
_UNCERTAIN_KEYS = {"uncertain_content", "in_flight_content", "unconfirmed_payload"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _tokens(text: str) -> Set[str]:
    return set(re.sub(r"[^\w\s]", " ", text.lower()).split())


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def has_evidence(evidence: str) -> bool:
    """True when evidence cites a run id AND a file:line or event pointer."""
    if not isinstance(evidence, str):
        return False
    return bool(_RUN_RE.search(evidence)) and bool(
        _FILELINE_RE.search(evidence) or _EVENT_RE.search(evidence)
    )


def _check_text(name: str, value: Any, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if required and not value.strip():
        raise ValueError(f"{name} must be non-empty")
    if len(value) > MAX_RECORD_CHARS:
        raise ValueError(f"{name} exceeds {MAX_RECORD_CHARS} chars (anti-explosion)")
    return value


def _normalize_refs(refs: Any) -> Any:
    if refs is None:
        return {}
    if isinstance(refs, str):
        if len(refs) > MAX_REF_CHARS:
            raise ValueError("refs string exceeds size cap")
        return {"note": refs}
    if isinstance(refs, (list, tuple)):
        items = list(refs)
        if len(items) > MAX_REFS_ITEMS:
            raise ValueError("too many refs entries")
        for item in items:
            if not isinstance(item, str) or len(item) > MAX_REF_CHARS:
                raise ValueError("refs entries must be strings within size cap")
        return {"items": items}
    if isinstance(refs, dict):
        if len(refs) > MAX_REFS_ITEMS:
            raise ValueError("too many refs entries")
        out: Dict[str, str] = {}
        for key, val in refs.items():
            if not isinstance(key, str) or len(key) > 100:
                raise ValueError("refs keys must be short strings")
            text = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
            if len(text) > MAX_REF_CHARS:
                raise ValueError("refs value exceeds size cap")
            out[key] = text
        return out
    raise ValueError("refs must be None, a string, a list of strings, or a dict")


def _fit_lines(lines: List[str], max_chars: int) -> str:
    """Join lines, dropping trailing lines (keeping a marker) to fit max_chars."""
    if type(max_chars) is not int or isinstance(max_chars, bool) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    full = "\n".join(lines)
    if len(full) <= max_chars:
        return full
    budget = max_chars - len(TRUNCATION_MARKER)
    if budget <= 0:
        return TRUNCATION_MARKER.strip()[:max_chars]
    kept: List[str] = []
    used = 0
    for line in lines:
        cost = len(line) + (1 if kept else 0)
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    if not kept:
        return (lines[0][:budget] + TRUNCATION_MARKER)[:max_chars]
    return "\n".join(kept) + TRUNCATION_MARKER


class ProgramMemory:
    """Persistent program-level memory rooted at a workspace directory.

    :param workspace: workspace root; files live in ``<workspace>/memory/``.
    """

    def __init__(self, workspace: Union[str, Path]):
        self.workspace = Path(workspace)
        self.memory_dir = self.workspace / MEMORY_DIRNAME
        if self.memory_dir.is_symlink() or (
            hasattr(self.memory_dir, "is_junction") and self.memory_dir.is_junction()
        ):
            raise ValueError("memory directory cannot be a filesystem link")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.adrs_file = self.memory_dir / ADRS_FILENAME
        self.lessons_file = self.memory_dir / LESSONS_FILENAME
        self.candidates_file = self.memory_dir / CANDIDATES_FILENAME

    # -- atomic IO ------------------------------------------------------
    def _atomic_write_json(self, path: Path, payload: Any) -> None:
        raw = json.dumps(payload, indent=2, ensure_ascii=False)
        if len(raw.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"{path.name} would exceed {MAX_FILE_BYTES} bytes")
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".tmp."
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(raw)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
            raise

    def _quarantine(self, path: Path) -> None:
        target = path.with_suffix(path.suffix + f".corrupt-{int(time.time())}.bak")
        try:
            os.replace(str(path), str(target))
        except Exception:
            pass

    def _load_list(self, path: Path) -> List[Any]:
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8", newline="\n") as handle:
                data = json.load(handle)
            if not isinstance(data, list):
                raise ValueError("top-level JSON must be a list")
            return data
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError):
            self._quarantine(path)
            return []

    def _load_dict(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8", newline="\n") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("top-level JSON must be an object")
            return data
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError):
            self._quarantine(path)
            return {}

    @staticmethod
    def _clean_adr(raw: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        entry_id = raw.get("id")
        if not isinstance(entry_id, str) or not re.fullmatch(r"ADR-\d{4}", entry_id):
            return None
        if not isinstance(raw.get("decision"), str) or not raw["decision"].strip():
            return None
        return {
            "id": entry_id,
            "date": raw.get("date", ""),
            "decision": raw["decision"],
            "rationale": raw.get("rationale", ""),
            "refs": raw.get("refs", {}),
        }

    @staticmethod
    def _clean_lesson(raw: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        entry_id = raw.get("id")
        if not isinstance(entry_id, str) or not re.fullmatch(r"LES-\d{4}", entry_id):
            return None
        if not isinstance(raw.get("text"), str) or not raw["text"].strip():
            return None
        return {
            "id": entry_id,
            "date": raw.get("date", ""),
            "text": raw["text"],
            "evidence": raw.get("evidence", ""),
        }

    # -- ADR ------------------------------------------------------------
    def list_adrs(self) -> List[Dict[str, Any]]:
        out = []
        for raw in self._load_list(self.adrs_file):
            clean = self._clean_adr(raw)
            if clean is not None:
                out.append(clean)
        out.sort(key=lambda e: e["id"])
        return out

    def record_adr(
        self,
        decision: str,
        rationale: str = "",
        refs: Optional[Any] = None,
    ) -> str:
        """Persist one Architecture Decision Record; return its stable id.

        Ids are sequential (``ADR-0001`` ...) derived from the max stored id,
        never reused. ``refs`` should point at the deciding run/task, e.g.
        ``{"run_id": "run-abc", "task_id": "T-1"}``.
        """
        _check_text("decision", decision)
        if rationale is None:
            rationale = ""
        _check_text("rationale", rationale, required=False)
        norm_refs = _normalize_refs(refs)
        adrs = self.list_adrs()
        if len(adrs) >= MAX_ADRS:
            raise ValueError(f"ADR store full ({MAX_ADRS} records)")
        taken = {a["id"] for a in adrs}
        seq = 1
        for item in adrs:
            try:
                seq = max(seq, int(item["id"].split("-")[1]) + 1)
            except (IndexError, ValueError):
                continue
        while f"ADR-{seq:04d}" in taken:
            seq += 1
        entry = {
            "id": f"ADR-{seq:04d}",
            "date": _utcnow(),
            "decision": decision.strip(),
            "rationale": rationale.strip() if isinstance(rationale, str) else "",
            "refs": norm_refs,
        }
        raw = self._load_list(self.adrs_file)
        raw.append(entry)
        self._atomic_write_json(self.adrs_file, raw)
        return entry["id"]

    # -- lessons --------------------------------------------------------
    def list_lessons(self) -> List[Dict[str, Any]]:
        out = []
        for raw in self._load_list(self.lessons_file):
            clean = self._clean_lesson(raw)
            if clean is not None:
                out.append(clean)
        out.sort(key=lambda e: e["id"])
        return out

    def record_lesson(self, text: str, evidence: str) -> str:
        """Persist one lesson; return its id (``LES-0001`` ...).

        Lessons are accepted ONLY with evidence citing a run id plus a
        ``file:line`` pointer or an event reference; otherwise ``ValueError``.
        """
        _check_text("text", text)
        _check_text("evidence", evidence)
        if not has_evidence(evidence):
            raise ValueError(
                "lesson refused: evidence must cite a run id plus a file:line "
                "or event reference"
            )
        lessons = self.list_lessons()
        if len(lessons) >= MAX_LESSONS:
            raise ValueError(f"lesson store full ({MAX_LESSONS} records)")
        taken = {entry["id"] for entry in lessons}
        seq = 1
        for item in lessons:
            try:
                seq = max(seq, int(item["id"].split("-")[1]) + 1)
            except (IndexError, ValueError):
                continue
        while f"LES-{seq:04d}" in taken:
            seq += 1
        entry = {
            "id": f"LES-{seq:04d}",
            "date": _utcnow(),
            "text": text.strip(),
            "evidence": evidence.strip(),
        }
        raw = self._load_list(self.lessons_file)
        raw.append(entry)
        self._atomic_write_json(self.lessons_file, raw)
        return entry["id"]

    # -- candidate index ------------------------------------------------
    def get_candidates(
        self, task_type: Optional[str] = None
    ) -> Union[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
        data = self._load_dict(self.candidates_file)
        clean: Dict[str, List[Dict[str, Any]]] = {}
        for key, val in data.items():
            if not isinstance(key, str) or not isinstance(val, list):
                continue
            items = [i for i in val if isinstance(i, dict)]
            clean[key] = items
        if task_type is None:
            return clean
        return list(clean.get(task_type.strip().lower(), []))

    def record_candidate(
        self,
        task_type: str,
        patch_ref: str,
        outcome: str,
        run_id: str = "",
        task_id: str = "",
        notes: str = "",
    ) -> int:
        """Index one task attempt under its task type; return its index.

        ``outcome`` is stored verbatim (e.g. ``SUCCESS`` / ``FAILED``);
        ``patch_ref`` should locate the patch (path, candidate id, hash).
        """
        _check_text("task_type", task_type)
        _check_text("patch_ref", patch_ref)
        _check_text("outcome", outcome)
        for name, val in (("run_id", run_id), ("task_id", task_id)):
            if val is None:
                raise ValueError(f"{name} must be a string")
            if not isinstance(val, str) or len(val) > MAX_REF_CHARS:
                raise ValueError(f"{name} exceeds size cap")
        _check_text("notes", notes, required=False)
        kind = task_type.strip().lower()
        data = self._load_dict(self.candidates_file)
        total = sum(len(v) for v in data.values() if isinstance(v, list))
        if total >= MAX_CANDIDATES_TOTAL:
            raise ValueError("candidate index full")
        if not isinstance(data.get(kind), list):
            if kind not in data and len(data) >= MAX_CANDIDATE_TYPES:
                raise ValueError("too many candidate task types")
            data[kind] = []
        if len(data[kind]) >= MAX_CANDIDATES_PER_TYPE:
            raise ValueError(f"candidate list full for task type {kind!r}")
        entry = {
            "patch_ref": patch_ref.strip(),
            "outcome": outcome.strip(),
            "run_id": run_id.strip() if isinstance(run_id, str) else "",
            "task_id": task_id.strip() if isinstance(task_id, str) else "",
            "notes": notes.strip() if isinstance(notes, str) else "",
            "date": _utcnow(),
        }
        data[kind].append(entry)
        self._atomic_write_json(self.candidates_file, data)
        return len(data[kind]) - 1

    def stats(self) -> Dict[str, int]:
        data = self._load_dict(self.candidates_file)
        total = sum(len(v) for v in data.values() if isinstance(v, list))
        return {
            "adrs": len(self.list_adrs()),
            "lessons": len(self.list_lessons()),
            "candidate_types": len(data),
            "candidates": total,
        }

    # -- recall ---------------------------------------------------------
    def recall(self, query: str, limit: int = DEFAULT_RECALL_LIMIT) -> List[Dict[str, Any]]:
        """Rank stored snippets by token overlap with ``query`` (deterministic).

        Pure lexical overlap (``len(query_tokens & doc_tokens)`` primary,
        Jaccard secondary, ``kind``/``ref`` tie-break); no new dependencies.
        Returns ``[{"kind", "ref", "snippet", "score"}]`` with ``score`` the
        overlap count. Blank queries and zero-overlap corpora return ``[]``.
        """
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if type(limit) is not int or isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, MAX_RECALL_LIMIT))
        qtokens = _tokens(query)
        if not qtokens:
            return []
        corpus: List[Tuple[str, str, str]] = []
        for adr in self.list_adrs():
            corpus.append(
                ("adr", adr["id"], f"{adr['decision']} {adr.get('rationale', '')}")
            )
        for les in self.list_lessons():
            corpus.append(("lesson", les["id"], f"{les['text']} {les.get('evidence', '')}"))
        data = self._load_dict(self.candidates_file)
        for kind in sorted(data):
            entries = data[kind]
            if not isinstance(entries, list):
                continue
            for idx, item in enumerate(entries):
                if not isinstance(item, dict):
                    continue
                text = " ".join(
                    str(item.get(k, ""))
                    for k in ("patch_ref", "outcome", "notes")
                )
                corpus.append((f"candidate:{kind}", f"{kind}#{idx}", f"{kind} {text}"))
        scored: List[Tuple[int, float, str, str, str]] = []
        for kind, ref, text in corpus:
            dtokens = _tokens(text)
            overlap = len(qtokens & dtokens)
            if overlap <= 0:
                continue
            scored.append((overlap, _jaccard(qtokens, dtokens), kind, ref, text))
        scored.sort(key=lambda row: (-row[0], -row[1], row[2], row[3]))
        out = []
        for overlap, _sim, kind, ref, text in scored[:limit]:
            snippet = " ".join(text.split())
            if len(snippet) > SNIPPET_CHARS:
                snippet = snippet[: SNIPPET_CHARS - 3] + "..."
            out.append({"kind": kind, "ref": ref, "snippet": snippet, "score": overlap})
        return out

    # -- compact brief --------------------------------------------------
    def compact_brief(self, max_chars: int = DEFAULT_COMPACT_CHARS) -> str:
        """Summarize ADRs + top lessons (+ candidate counts) within ``max_chars``.

        Drop-in context for opening a fresh chat without losing the thread:
        ADRs oldest-first, lessons newest-first, one line per record, trailing
        lines dropped with a marker when the ceiling bites. Never exceeds
        ``max_chars``.
        """
        lines = ["# SENTRA program memory (compact brief)"]
        adrs = self.list_adrs()
        lines.append(f"## ADRs vigentes ({len(adrs)})")
        if adrs:
            for adr in adrs:
                rationale = adr.get("rationale", "").strip()
                tail = f" -- {rationale}" if rationale else ""
                lines.append(f"- [{adr['id']} {adr.get('date', '')}] {adr['decision']}{tail}")
        else:
            lines.append("- (nenhum ADR registrado)")
        lessons = self.list_lessons()
        lines.append(f"## Licoes com evidencia, mais recentes ({len(lessons)})")
        if lessons:
            for les in reversed(lessons[-20:]):
                lines.append(f"- [{les['id']}] {les['text']} (evidencia: {les['evidence']})")
        else:
            lines.append("- (nenhuma licao registrada)")
        data = self._load_dict(self.candidates_file)
        lines.append(f"## Indice de candidatos ({len(data)} tipos)")
        if data:
            for kind in sorted(data):
                entries = data[kind] if isinstance(data[kind], list) else []
                ok = sum(1 for e in entries if "success" in str(e.get("outcome", "")).lower()
                         or str(e.get("outcome", "")).upper() in {"PASS", "PASSED", "OK"})
                lines.append(f"- {kind}: {len(entries)} tentativas, {ok} sucesso")
        else:
            lines.append("- (indice vazio)")
        return _fit_lines(lines, max_chars)

    # -- rotation brief -------------------------------------------------
    def build_rotation_brief(self, run_context: Dict[str, Any], max_chars: int = DEFAULT_ROTATION_CHARS) -> str:
        """Build the FIRST user message of a fresh continuation chat.

        Pure function: reads memory files only, writes nothing, sends nothing,
        performs no network calls.

        ROTATION PROTOCOL (seat rotation spec; the pool/engine implementation
        that actually opens the new chat is owned by another workstream):

        1. The operator (or engine) opens a brand-NEW chat, never a reply
           inside a stuck seat.
        2. The return value of this function is posted as the FIRST user
           message of that new chat, verbatim.
        3. NEVER resend content whose delivery is uncertain (seats stuck in
           ``IN_FLIGHT`` / ``UNCERTAIN`` / ``BLOCKED``): do not paste the old
           prompt, do not replay the old send. Keys ``uncertain_content``,
           ``in_flight_content`` and ``unconfirmed_payload`` in ``run_context``
           are therefore summarized as omitted, never quoted.
        4. Record the previous chat URL in history (``prior_conversation_url``
           / ``prior_urls`` below) so forensics can find it, then continue
           from the brief alone.
        5. If the old seat later unblocks, reconcile via
           ``inspect_conversations`` / explicit drop -- never by merging two
           live chats.

        ``run_context`` keys (all optional; missing -> ``nao informado``)::

            {"objective": str, "run_id": str, "task_id": str,
             "current_state": str | dict, "next_actions": str | list[str],
             "prior_conversation_url": str, "prior_urls": list[str],
             "extra_notes": str}

        Layout: protocol banner, objective, current state, next actions,
        standing decisions (ADRs), relevant memory (recall over the
        objective), history/URLs. Truncation drops lower sections first and
        never exceeds ``max_chars``.
        """
        if not isinstance(run_context, dict):
            raise TypeError("run_context must be a dict")
        if type(max_chars) is not int or isinstance(max_chars, bool) or max_chars <= 0:
            raise ValueError("max_chars must be a positive integer")

        def _omit_uncertain(value: Any) -> str:
            return "[omitido: conteudo de envio incerto nunca e reenviado -- reconciliar via historico]"

        def _as_text(value: Any) -> str:
            if value is None or value == "":
                return "nao informado"
            if isinstance(value, str):
                return value
            if isinstance(value, (list, tuple)):
                return "; ".join(str(v) for v in value) if value else "nao informado"
            if isinstance(value, dict):
                try:
                    return json.dumps(value, ensure_ascii=False, sort_keys=True)
                except (TypeError, ValueError):
                    return str(value)
            return str(value)

        objective = _as_text(run_context.get("objective"))
        run_id = _as_text(run_context.get("run_id"))
        task_id = _as_text(run_context.get("task_id"))
        Dirham = run_context.get("current_state", "nao informado")
        current_state = _as_text(Dirham)
        nxt = run_context.get("next_actions", "nao informado")
        next_actions = _as_text(nxt)
        prior_urls: List[str] = []
        single = run_context.get("prior_conversation_url")
        if isinstance(single, str) and single.strip():
            prior_urls.append(single.strip())
        multi = run_context.get("prior_urls")
        if isinstance(multi, (list, tuple)):
            for item in multi:
                if isinstance(item, str) and item.strip() and item.strip() not in prior_urls:
                    prior_urls.append(item.strip())
        history_line = "; ".join(prior_urls) if prior_urls else "nao informado"
        extra = run_context.get("extra_notes", "")
        extra_line = _as_text(extra) if extra else ""

        omitted: List[str] = []
        for key in _UNCERTAIN_KEYS:
            if key in run_context and run_context[key] not in (None, "", [], {}):
                omitted.append(key)

        head = [
            "# SENTRA -- continuacao em chat novo (rotation brief)",
            "> ESTA MENSAGEM E A PRIMEIRA MENSAGEM user DE UM CHAT NOVO.",
            "> Protocolo: chat novo; nunca reenviar conteudo de envio incerto "
            "(IN_FLIGHT/UNCERTAIN/BLOCKED); URL anterior registrada no historico; "
            "reconciliacao do assento antigo por outro responsavel (pool/engine).",
            f"## 1. Objetivo\n{objective}",
            f"## 2. Estado atual (run {run_id}, task {task_id})\n{current_state}",
            f"## 3. O que fazer agora\n{next_actions}",
        ]
        if omitted:
            head.append(
                "## 3b. Envios incertos (NAO reenviados)\n"
                + _omit_uncertain(None)
                + f" (campos omitidos: {', '.join(sorted(omitted))})"
            )
        tail_core = [f"## 6. Historico / URLs anteriores\n{history_line}"]
        if extra_line and extra_line != "nao informado":
            tail_core.append(f"## 7. Notas\n{extra_line}")

        adrs = self.list_adrs()
        adr_lines = [f"## 4. Decisoes vigentes ({len(adrs)} ADRs)"]
        if adrs:
            for adr in reversed(adrs[-30:]):
                adr_lines.append(f"- [{adr['id']}] {adr['decision']}")
        else:
            adr_lines.append("- (nenhum ADR vigente)")

        recall_hits = self.recall(objective, limit=5) if objective != "nao informado" else []
        mem_lines = [f"## 5. Memoria relevante ({len(recall_hits)} trechos)"]
        if recall_hits:
            for hit in recall_hits:
                mem_lines.append(f"- [{hit['kind']}/{hit['ref']}] {hit['snippet']}")
        else:
            for les in reversed(self.list_lessons()[-5:]):
                mem_lines.append(f"- [lesson/{les['id']}] {les['text']}")

        # Priority order under the ceiling: head, actions/state already in head,
        # then ADRs, then memory, then history. Drop from the bottom up.
        sections: List[List[str]] = [head, adr_lines, mem_lines, tail_core]
        flat: List[str] = []
        for section in sections:
            flat.extend(section)
        try:
            return _fit_lines(flat, max_chars)
        except ValueError:
            raise
