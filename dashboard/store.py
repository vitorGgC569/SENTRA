"""Read-only aggregation for the OMA dashboard. No sends, no mutations.

Sources (all local): relay SQLite (jobs + full prompts/results), run
directories (handoff/tasks/validations/conversations/metrics), relay /health.
Every function is pure over explicit paths -> unit-testable without a browser.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
PREVIEW = 600


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _clip(text: str, limit: int = PREVIEW) -> Dict[str, Any]:
    text = text or ""
    if len(text) <= limit:
        return {"text": text, "truncated": False}
    return {"text": text[:limit], "truncated": True, "total_chars": len(text)}


def _iter_run_dirs(root: Path):
    """Run dirs: direct children plus nested pilot repos (depth <= 4)."""
    if not root.is_dir():
        return
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        if (current / "tasks.json").is_file() and current != root:
            yield current
            continue
        if depth >= 4:
            continue
        try:
            children = [p for p in sorted(current.iterdir()) if p.is_dir()
                        and p.name not in {".git", "__pycache__", "node_modules"}]
        except OSError:
            continue
        stack.extend((c, depth + 1) for c in children)


def list_runs(runs_dir) -> List[Dict[str, Any]]:
    """One row per run: status, tasks, scores when available."""
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return []
    rows = []
    for child in _iter_run_dirs(runs_dir):
        if not RUN_ID.fullmatch(child.name):
            continue
        hand = _read_json(child / "handoff.json", {})
        run = _read_json(child / "run.json", {})
        metrics = _read_json(child / "metrics.json", {})
        tasks = _read_json(child / "tasks.json", [])
        if isinstance(tasks, dict):
            tasks = tasks.get("tasks", [])
        rows.append({
            "run_id": child.name,
            "project": str(child.parent.relative_to(runs_dir))
            if child.parent != runs_dir else runs_dir.name,
            "status": hand.get("status") or run.get("status") or "UNKNOWN",
            "objective": (hand.get("objective") or run.get("objective") or "")[:160],
            "completed_tasks": hand.get("completed_tasks", metrics.get("tasks_completed", 0)),
            "total_tasks": hand.get("total_tasks", len(tasks) if isinstance(tasks, list) else 0),
            "updated": child.stat().st_mtime,
        })
    return sorted(rows, key=lambda r: r["updated"], reverse=True)


def run_chats(run_dir) -> List[Dict[str, Any]]:
    """Chats of one run: fixed seats (registry) union relay jobs (observed).

    A seat is the stable identity (run:role); a job is one delivery. Seats
    without URL yet + jobs without seat linkage both appear, labeled.
    """
    run_dir = Path(run_dir)
    conv = _read_json(run_dir / "conversations.json", {})
    seats = conv.get("seats", conv) if isinstance(conv, dict) else {}
    chats: Dict[str, Dict[str, Any]] = {}
    for seat, entry in (seats.items() if isinstance(seats, dict) else []):
        if not isinstance(entry, dict):
            continue
        chats[seat] = {"seat": seat, "role": entry.get("role", ""),
                       "url": entry.get("url"), "state": entry.get("state", ""),
                       "task_id": entry.get("task_id", ""),
                       "jobs": 0, "last_updated": entry.get("updated", 0)}
    validations = _read_json(run_dir / "validations.json", [])
    reps = validations if isinstance(validations, list) else validations.get("reports", [])
    scores: Dict[str, List[float]] = {}
    for r in reps if isinstance(reps, list) else []:
        if not isinstance(r, dict):
            continue
        s = r.get("score")
        if s is None:
            try:
                s = round(max(0.0, min(1.0, float(r.get("confidence", 0.0)))) * 10.0, 2)
            except (TypeError, ValueError):
                continue
        scores.setdefault(r.get("validator_role", "?"), []).append(float(s))
    return [{"seat": k, **v,
             "min_score": min(scores[v["role"]]) if v["role"] in scores and scores[v["role"]] else None}
            for k, v in sorted(chats.items())]


def relay_jobs(db_path, limit: int = 50, task_id: Optional[str] = None,
               conversation_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """Recent relay jobs (read-only). Prompts/results clipped with MORE flags."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    except Exception:
        return []
    try:
        rows = conn.execute(
            "SELECT id, payload, state, worker, updated FROM jobs "
            "ORDER BY updated DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
    except Exception:
        conn.close()
        return []
    out = []
    for jid, payload, state, worker, updated in rows:
        try:
            data = json.loads(payload or "{}")
        except Exception:
            continue
        if task_id and data.get("task_id") != task_id:
            continue
        url = data.get("conversation_url")
        if conversation_url and url != conversation_url:
            continue
        res = _read_result(conn, jid)
        prompt = data.get("prompt", "") or ""
        out.append({"job_id": jid, "task_id": data.get("task_id", ""),
                    "state": state, "worker": worker or "",
                    "kind": data.get("kind", "CHAT_TASK"),
                    "conversation_url": url, "updated": updated,
                    "images": len(data.get("images", []) or []),
                    "images_attached": (res.get("images_attached", 0)
                                        if isinstance(res, dict) else 0),
                    "prompt": _clip(prompt),
                    "response": _clip(res.get("result", "")) if res else None,
                    "response_error": (res.get("error") if res else None)})
    conn.close()
    return out


def _read_result(conn, job_id: str) -> Optional[Dict[str, Any]]:
    try:
        row = conn.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()
    except Exception:
        return None
    if not row or not row[0]:
        return None
    try:
        data = json.loads(row[0])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


BROKEN_SEATS = {"NOT_SENT", "UNCERTAIN", "BLOCKED"}


def _project_of(runs_dir: Path, run_dir: Path) -> str:
    runs_dir, run_dir = Path(runs_dir), Path(run_dir)
    if run_dir.parent != runs_dir:
        try:
            return str(run_dir.parent.relative_to(runs_dir))
        except ValueError:
            return runs_dir.name
    return runs_dir.name


def _run_tasks(run_dir: Path) -> List[Dict[str, Any]]:
    tasks = _read_json(Path(run_dir) / "tasks.json", [])
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])
    return [t for t in tasks] if isinstance(tasks, list) else []


def all_chats(roots) -> List[Dict[str, Any]]:
    """Every chat of every run: seat identity + run/project context."""
    out = []
    for root in [Path(r) for r in roots]:
        for run_dir in _iter_run_dirs(root):
            if not RUN_ID.fullmatch(run_dir.name):
                continue
            project = _project_of(root, run_dir)
            for chat in run_chats(run_dir):
                out.append({"run_id": run_dir.name, "project": project, **chat})
    return sorted(out, key=lambda c: (c["run_id"], c["seat"]))


def failures(roots, db_path, job_limit: int = 200) -> Dict[str, Any]:
    """Broken conversations + failed deliveries + failed tasks. Read-only."""
    seats, tasks = [], []
    for root in [Path(r) for r in roots]:
        for run_dir in _iter_run_dirs(root):
            if not RUN_ID.fullmatch(run_dir.name):
                continue
            project = _project_of(root, run_dir)
            for chat in run_chats(run_dir):
                if (chat.get("state") or "") in BROKEN_SEATS:
                    seats.append({"run_id": run_dir.name, "project": project, **chat})
            for t in _run_tasks(run_dir):
                if isinstance(t, dict) and (t.get("status") or "") == "FAILED":
                    tasks.append({
                        "run_id": run_dir.name, "project": project,
                        "task_id": t.get("id", ""),
                        "objective": str(t.get("objective", ""))[:120],
                        "repairs": t.get("current_repair_round", 0)})
    jobs = [j for j in relay_jobs(db_path, limit=job_limit) if j.get("state") == "FAILED"]
    return {"seats": seats, "jobs": jobs, "tasks": tasks,
            "counts": {"seats": len(seats), "jobs": len(jobs), "tasks": len(tasks)}}


def _read_events(run_dir: Path, limit: int = 12) -> List[Dict[str, Any]]:
    path = Path(run_dir) / "events.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            data = json.loads(line)
        except Exception:
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def run_summary(run_dir, run_id: str = "", project: str = "") -> str:
    """Context digest as markdown, composed locally from on-disk records.

    No sends, no mutations: honest operator context (never claim agents saw it).
    """
    run_dir = Path(run_dir)
    run_id = run_id or run_dir.name
    hand = _read_json(run_dir / "handoff.json", {})
    tasks = _run_tasks(run_dir)
    chats = run_chats(run_dir)
    reps = _read_json(run_dir / "validations.json", [])
    reps = reps if isinstance(reps, list) else reps.get("reports", [])
    events = _read_events(run_dir)
    fails = [e for e in events if str(e.get("event_type", "")).endswith(
        ("FAILED", "REJECTED")) or e.get("event_type") == "REPAIR_REQUESTED"]
    lines = [f"# {run_id}", ""]
    if project:
        lines.append(f"Projeto: {project}")
    lines.append(f"Status: {hand.get('status', 'UNKNOWN')}")
    done = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "COMPLETED")
    lines.append(f"Tarefas: {done}/{len(tasks)}")
    lines += ["", "## Objetivo", (hand.get("objective") or "")[:2000] or "(sem objetivo registrado)",
              "", "## Tarefas"]
    for t in tasks[:30]:
        if not isinstance(t, dict):
            continue
        lines.append(f"- {t.get('id', '?')} [{t.get('status', '?')}] "
                     f"repairs={t.get('current_repair_round', 0)} "
                     f"{str(t.get('objective', ''))[:100]}")
    lines += ["", "## Chats"]
    for c in chats:
        lines.append(f"- {c['seat']} [{c.get('state', '?')}] {c.get('url') or 'sem URL'}")
    lines += ["", "## Validações"]
    for r in reps[:20]:
        if isinstance(r, dict):
            lines.append(f"- {r.get('task_id', '?')} {r.get('validator_role', '?')}: "
                         f"{r.get('score', '?')} ({r.get('status', '?')})")
    lines += ["", "## Falhas / rejeições"]
    for e in fails[-8:]:
        payload = e.get("payload", {}) if isinstance(e.get("payload"), dict) else {}
        reason = payload.get("reason", "") or ""
        lines.append(f"- {e.get('event_type')} {e.get('task_id', '')}: {str(reason)[:300]}")
    lines += ["", "## Últimos eventos"]
    for e in events[-8:]:
        lines.append(f"- {e.get('timestamp', '')} {e.get('event_type', '')} "
                     f"{e.get('task_id', '') or ''}")
    return "\n".join(lines) + "\n"


def project_summary(roots, label: str) -> str:
    """One digest per project label: every matching run, compact."""
    lines = [f"# Projeto: {label}", ""]
    found = False
    for root in [Path(r) for r in roots]:
        for run_dir in _iter_run_dirs(root):
            if not RUN_ID.fullmatch(run_dir.name):
                continue
            if _project_of(root, run_dir) != label:
                continue
            found = True
            hand = _read_json(run_dir / "handoff.json", {})
            tasks = _run_tasks(run_dir)
            done = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "COMPLETED")
            broken = sum(1 for c in run_chats(run_dir)
                         if (c.get("state") or "") in BROKEN_SEATS)
            fails = [e for e in _read_events(run_dir)
                     if str(e.get("event_type", "")).endswith(("FAILED", "REJECTED"))]
            last = ""
            if fails:
                payload = fails[-1].get("payload", {})
                last = str(payload.get("reason", ""))[:200] if isinstance(payload, dict) else ""
            lines += [f"## {run_dir.name} [{hand.get('status', 'UNKNOWN')}]",
                      f"Tarefas: {done}/{len(tasks)} · chats quebrados: {broken}",
                      f"Objetivo: {(hand.get('objective') or '')[:300]}",
                      f"Última falha: {last or '—'}", ""]
    if not found:
        lines.append("(nenhuma run com este rótulo)")
    return "\n".join(lines) + "\n"


def relay_health(relay_base: str, timeout: float = 8.0) -> Dict[str, Any]:
    import urllib.request
    try:
        with urllib.request.urlopen(relay_base.rstrip("/") + "/health",
                                    timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"reachable": True, "ok": data.get("ok", False),
                    "submitted": data.get("submitted", 0),
                    "completed": data.get("completed", 0),
                    "failed": data.get("failed", 0),
                    "queued": data.get("queued", 0), "leased": data.get("leased", 0),
                    "workers_online": data.get("workers_online", []),
                    "uptime_s": data.get("uptime_s", 0)}
    except Exception as exc:
        return {"reachable": False, "error": type(exc).__name__}


def program_stats(roots, max_runs: int = 500, max_events_per_run: int = 200,
                  velocity_days: int = 14) -> Dict[str, Any]:
    """Program analytics over all runs: status, velocity, failure taxonomy, flakiness.

    Read-only and pure over explicit roots (no network, no writes). Caps bound
    work on large checkouts: at most max_runs run dirs are scanned and at most
    max_events_per_run trailing events.jsonl lines are parsed per run.
    Velocity buckets COMPLETED tasks by run-dir mtime into 24h UTC-day windows
    covering the last velocity_days days (today inclusive). Failure taxonomy
    counts reasons from TASK_FAILED / QUALITY_GATE_FAILED / CANDIDATE_REJECTED
    payloads (top 10). Flakiness is the fraction of tasks with
    current_repair_round > 0.
    """
    import collections
    import datetime

    failure_types = ("TASK_FAILED", "QUALITY_GATE_FAILED", "CANDIDATE_REJECTED")

    def _tail_lines(path: Path, limit: int):
        try:
            size = path.stat().st_size
        except OSError:
            return []
        try:
            if size > 1_000_000:
                with open(path, "rb") as handle:
                    handle.seek(max(0, size - 1_000_000))
                    chunk = handle.read().decode("utf-8", errors="ignore")
                lines = chunk.splitlines()
                if lines:
                    lines = lines[1:]
                return lines[-limit:] if limit > 0 else []
            return path.read_text(encoding="utf-8").splitlines()[-limit:] if limit > 0 else []
        except OSError:
            return []

    def _failure_reason(event: Dict[str, Any]) -> str:
        payload = event.get("payload")
        reason = ""
        if isinstance(payload, dict):
            reason = (payload.get("reason") or payload.get("error")
                      or payload.get("message") or "")
        reason = " ".join(str(reason).split())
        if not reason:
            reason = str(event.get("event_type") or "UNKNOWN")
        return reason[:160]

    roots_list = [Path(r) for r in (roots or [])]
    run_dirs: List[Path] = []
    truncated = False
    for root in roots_list:
        if truncated:
            break
        for run_dir in _iter_run_dirs(root):
            if not RUN_ID.fullmatch(run_dir.name):
                continue
            if len(run_dirs) >= max(1, max_runs):
                truncated = True
                break
            run_dirs.append(run_dir)

    by_status: Dict[str, int] = {}
    total_tasks = 0
    completed_tasks = 0
    failed_tasks = 0
    repaired_tasks = 0
    per_day: Dict[str, int] = collections.defaultdict(int)
    taxonomy: Dict[str, int] = collections.Counter()

    for run_dir in run_dirs:
        hand = _read_json(run_dir / "handoff.json", {})
        run = _read_json(run_dir / "run.json", {})
        if not isinstance(hand, dict):
            hand = {}
        if not isinstance(run, dict):
            run = {}
        status = hand.get("status") or run.get("status") or "UNKNOWN"
        by_status[str(status)] = by_status.get(str(status), 0) + 1

        tasks = _run_tasks(run_dir)
        done = 0
        for task in tasks:
            if not isinstance(task, dict):
                continue
            total_tasks += 1
            task_status = task.get("status") or ""
            if task_status == "COMPLETED":
                completed_tasks += 1
                done += 1
            if task_status == "FAILED":
                failed_tasks += 1
            try:
                repairs = int(task.get("current_repair_round", 0) or 0)
            except (TypeError, ValueError):
                repairs = 0
            if repairs > 0:
                repaired_tasks += 1
        if not tasks:
            try:
                fallback_done = int(hand.get("completed_tasks", 0) or 0)
            except (TypeError, ValueError):
                fallback_done = 0
            done = max(0, fallback_done)

        try:
            mtime = run_dir.stat().st_mtime
            day = datetime.datetime.fromtimestamp(
                mtime, tz=datetime.timezone.utc).date().isoformat()
            per_day[day] += done
        except OSError:
            pass

        for line in _tail_lines(run_dir / "events.jsonl", max(1, max_events_per_run)):
            try:
                event = json.loads(line)
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("event_type") not in failure_types:
                continue
            taxonomy[_failure_reason(event)] += 1

    try:
        today = datetime.datetime.now(tz=datetime.timezone.utc).date()
    except Exception:
        today = datetime.date.today()
    days = max(1, min(int(velocity_days or 14), 90))
    velocity = []
    for offset in range(days - 1, -1, -1):
        try:
            day = today - datetime.timedelta(days=offset)
        except Exception:
            continue
        key = day.isoformat()
        velocity.append({"date": key, "completed": int(per_day.get(key, 0))})

    ranked = sorted(taxonomy.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    flaky_fraction = (repaired_tasks / total_tasks) if total_tasks else 0.0
    return {
        "runs_total": len(run_dirs),
        "by_status": dict(sorted(by_status.items())),
        "tasks": {"total": total_tasks, "completed": completed_tasks,
                  "failed": failed_tasks},
        "velocity": velocity,
        "failure_taxonomy": [{"reason": reason, "count": count}
                             for reason, count in ranked],
        "flakiness": {"total_tasks": total_tasks,
                      "repaired_tasks": repaired_tasks,
                      "flaky_fraction": flaky_fraction},
        "caps": {"max_runs": max_runs, "max_events_per_run": max_events_per_run,
                 "truncated": truncated},
    }
