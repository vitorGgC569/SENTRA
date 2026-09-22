from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sentra_remote.human_store import HumanStore
from sentra_remote.human_worker import WorkerLease
from sentra_remote.product import ProductPaths, ProductSettings, list_tasks


def _store(tmp_path: Path) -> tuple[HumanStore, ProductPaths, Path]:
    install = tmp_path / "install"
    state = tmp_path / "state"
    workspace = tmp_path / "workspace"
    install.mkdir()
    state.mkdir()
    workspace.mkdir()
    paths = ProductPaths(install, state)
    settings = ProductSettings(
        profile="Developer",
        allowed_roots=[str(workspace)],
        workspace_permissions={str(workspace.resolve()): ["read", "write", "execute"]},
    )
    settings.save(paths.settings)
    return HumanStore(paths, settings), paths, workspace.resolve()


def test_human_message_queues_real_task_without_fake_assistant(tmp_path: Path) -> None:
    store, paths, workspace = _store(tmp_path)

    result = store.send_message(None, str(workspace), "Implemente a validação real")
    conversation = result["conversation"]
    task_id = result["task"]["task_id"]

    assert result["task"]["state"] == "QUEUED"
    tasks = list_tasks(paths)
    assert len(tasks) == 1
    assert tasks[0]["id"] == task_id
    assert tasks[0]["prompt"] == "Implemente a validação real"
    assert [message["role"] for message in conversation["messages"]] == ["user", "system"]
    assert not any(message["role"] == "assistant" for message in conversation["messages"])


def test_human_result_comes_from_real_handoff(tmp_path: Path) -> None:
    store, paths, workspace = _store(tmp_path)
    result = store.send_message(None, str(workspace), "Faça o trabalho")
    task_id = int(result["task"]["task_id"])
    conversation_id = result["conversation"]["id"]

    run_id = "run-real-123"
    run_dir = workspace / "runs" / run_id
    run_dir.mkdir(parents=True)
    patch = run_dir / "candidate.patch"
    patch.write_text("+linha real\n", encoding="utf-8")
    handoff = {
        "run_id": run_id,
        "objective": "Faça o trabalho",
        "status": "CANDIDATE_READY",
        "completed_tasks": 2,
        "total_tasks": 2,
        "final_synthesis": "Síntese persistida pelo OMA.",
        "errors": [],
        "metrics": {
            "tasks_completed": 2,
            "tasks_total": 2,
            "validation_pass_rate": 1.0,
            "repair_rounds": 0,
            "elapsed_seconds": 4.5,
        },
        "patch_path": str(patch),
    }
    (run_dir / "handoff.json").write_text(json.dumps(handoff), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        json.dumps({
            "event_type": "MODEL_RESPONSE",
            "producer": "executor",
            "task_id": "T-01",
            "timestamp": "2026-09-22T12:00:00+00:00",
            "payload": {"status": "SUCCESS"},
        }) + "\n",
        encoding="utf-8",
    )

    logs = paths.state_dir / "logs"
    logs.mkdir()
    (logs / f"task-{task_id}.log").write_text(
        f"Run: {run_id}\nStatus: CANDIDATE_READY\n",
        encoding="utf-8",
    )
    db = sqlite3.connect(paths.state_dir / "desktop-tasks.sqlite3")
    db.execute(
        "UPDATE tasks SET state='COMPLETED',result_code=0 WHERE id=?",
        (task_id,),
    )
    db.commit()
    db.close()

    store.reconcile_results()
    conversation = store.conversation(conversation_id)
    assistant = [m for m in conversation["messages"] if m["role"] == "assistant"]
    assert len(assistant) == 1
    assert assistant[0]["body"] == "Síntese persistida pelo OMA."
    assert assistant[0]["run_id"] == run_id
    assert assistant[0]["metadata"]["state"] == "CANDIDATE_READY"

    detail = store.run_detail(f"oma:{run_id}")
    assert detail["patch_text"].splitlines() == ["+linha real"]
    assert detail["events"][0]["producer"] == "executor"


def test_patch_preview_cannot_escape_run_directory(tmp_path: Path) -> None:
    store, _paths, workspace = _store(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("do-not-read", encoding="utf-8")
    run_dir = workspace / "runs" / "run-safe"
    run_dir.mkdir(parents=True)
    (run_dir / "handoff.json").write_text(
        json.dumps({
            "run_id": "run-safe",
            "objective": "safe",
            "status": "FAILED",
            "completed_tasks": 0,
            "total_tasks": 1,
            "metrics": {},
            "errors": ["failure"],
            "patch_path": str(outside),
        }),
        encoding="utf-8",
    )

    detail = store.run_detail("oma:run-safe")
    assert detail["patch_text"] == ""


def test_human_ui_assets_do_not_ship_demo_content() -> None:
    root = Path(__file__).resolve().parents[2] / "sentra_remote" / "human_ui"
    text = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in ("index.html", "styles.css", "app.js")
    )
    assert "Refatorar módulo de autenticação" not in text
    assert "40 testes passaram" not in text
    assert "Claude 3.5 Sonnet" not in text
    assert "mock" not in text.casefold()


def test_worker_lease_reclaims_invalid_pid(tmp_path: Path) -> None:
    path = tmp_path / "worker.pid"
    path.write_text("0", encoding="ascii")
    lease = WorkerLease(path)
    assert lease.acquire() is True
    lease.release()
    assert not path.exists()


def test_release_payload_includes_human_ui_binaries() -> None:
    root = Path(__file__).resolve().parents[2]
    builder = (root / "scripts" / "commander" / "build_windows.py").read_text(encoding="utf-8")
    installer = (root / "sentra_remote" / "installer.py").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "release-commander.yml").read_text(encoding="utf-8")

    for name in ("sentra-human.exe", "sentra-human-worker.exe"):
        assert name in builder
        assert name in installer
        assert name in workflow
