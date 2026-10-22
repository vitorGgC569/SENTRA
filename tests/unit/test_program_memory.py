"""ProgramMemory: persistent cross-run memory. Real tmp_path IO, no live calls."""
import json

import pytest

from orchestrator.program_memory import ProgramMemory


def _mem(tmp_path):
    return ProgramMemory(tmp_path / "ws")


def test_adr_roundtrip_and_stable_ids(tmp_path):
    mem = _mem(tmp_path)
    first = mem.record_adr("Usar fila unica", "evita condicao de corrida",
                           {"run_id": "run-1", "task_id": "T-1"})
    second = mem.record_adr("Teto de 20000 chars por mensagem", "chats longos degradam")
    assert first == "ADR-0001" and second == "ADR-0002"
    # Reload from disk: persistence across runs/instances.
    mem2 = ProgramMemory(tmp_path / "ws")
    adrs = mem2.list_adrs()
    assert [a["id"] for a in adrs] == ["ADR-0001", "ADR-0002"]
    assert adrs[0]["refs"] == {"run_id": "run-1", "task_id": "T-1"}
    third = mem2.record_adr("Nova decisao", "motivo")
    assert third == "ADR-0003"  # never reuses ids


def test_lesson_requires_evidence(tmp_path):
    mem = _mem(tmp_path)
    with pytest.raises(ValueError):
        mem.record_lesson("algo util", "")
    with pytest.raises(ValueError):
        mem.record_lesson("algo util", "vi num arquivo engine.py:12")  # sem run
    with pytest.raises(ValueError):
        mem.record_lesson("algo util", "run-abc deu ruim")  # sem arquivo/evento
    lesson_id = mem.record_lesson("validar antes de promover",
                                  "run-abc falhou; ver orchestrator/engine.py:120")
    assert lesson_id == "LES-0001"
    event_ok = mem.record_lesson("replay e idempotente",
                                 "run-xyz TASK_COMPLETED em events.jsonl")
    assert event_ok == "LES-0002"


def test_recall_ranked_deterministic(tmp_path):
    mem = _mem(tmp_path)
    mem.record_adr("Usar fila de prioridade unica", "ordem deterministica")
    mem.record_lesson("fila satura com 10000 tarefas",
                      "run-q1 ver orchestrator/queue.py:60")
    mem.record_lesson("timeout do provedor local",
                      "run-q2 evento TASK_FAILED em events.jsonl")
    first = mem.recall("fila de prioridade satura", limit=5)
    second = mem.recall("fila de prioridade satura", limit=5)
    assert first == second  # deterministico
    assert first, "consulta com sobreposicao deve retornar trechos"
    assert first[0]["score"] >= first[-1]["score"]
    assert mem.recall("   ") == []
    assert mem.recall("zzzqux inexistente") == []


def test_candidates_index_and_recall(tmp_path):
    mem = _mem(tmp_path)
    idx0 = mem.record_candidate("bugfix", "patch-a.diff", "SUCCESS",
                                run_id="run-1", task_id="T-1")
    idx1 = mem.record_candidate("bugfix", "patch-b.diff", "FAILED",
                                run_id="run-2", task_id="T-2", notes="flaky")
    assert (idx0, idx1) == (0, 1)
    got = mem.get_candidates("bugfix")
    assert [g["outcome"] for g in got] == ["SUCCESS", "FAILED"]
    hits = mem.recall("bugfix patch-a", limit=5)
    assert any(h["kind"] == "candidate:bugfix" for h in hits)
    assert mem.stats()["candidates"] == 2


def test_corruption_quarantined_fail_open(tmp_path):
    mem = _mem(tmp_path)
    mem.record_adr("Decisao real", "motivo", {"run_id": "run-1"})
    mem.record_lesson("licao real", "run-1 ver main.py:10")
    mem.record_candidate("bugfix", "p.diff", "SUCCESS", run_id="run-1")
    for name in ("adrs.json", "lessons.json", "candidates.json"):
        (mem.memory_dir / name).write_text("{invalido!!!", encoding="utf-8")
    mem2 = ProgramMemory(tmp_path / "ws")
    assert mem2.list_adrs() == []
    assert mem2.list_lessons() == []
    assert mem2.get_candidates() == {}
    assert mem2.recall("qualquer coisa") == []
    assert mem2.compact_brief(2000)  # store vazio ainda funcional
    quarantined = list(mem2.memory_dir.glob("*.corrupt-*.bak"))
    assert len(quarantined) == 3
    # Store segue gravavel apos quarentena.
    assert mem2.record_adr("Depois da corrupcao", "segue") == "ADR-0001"


def test_ceilings_respected(tmp_path):
    mem = _mem(tmp_path)
    for i in range(30):
        mem.record_adr(f"decisao numero {i} sobre fila e Radeon", f"motivo {i}")
        mem.record_lesson(f"licao {i} sobre fila e timeout",
                          f"run-{i} ver orchestrator/queue.py:{10 + i}")
    small = mem.compact_brief(800)
    assert len(small) <= 800
    tiny = mem.compact_brief(200)
    assert len(tiny) <= 200
    ctx = {"objective": "Estabilizar a fila",
           "run_id": "run-new", "task_id": "T-9",
           "current_state": "3/10 tarefas prontas",
           "next_actions": ["retomar T-9", "rodar testes"],
           "prior_conversation_url": "https://chatgpt.com/c/antiga-1"}
    brief = mem.build_rotation_brief(ctx, 1500)
    assert len(brief) <= 1500
    micro = mem.build_rotation_brief(ctx, 300)
    assert len(micro) <= 300


def test_rotation_brief_sections_and_no_uncertain_replay(tmp_path):
    mem = _mem(tmp_path)
    mem.record_adr("Uma decisao vigente", "motivo claro")
    mem.record_lesson("lembrar do teto", "run-1 ver main.py:20")
    ctx = {"objective": "Fechar a run",
           "run_id": "run-new", "task_id": "T-3",
           "current_state": "aguardando validacao",
           "next_actions": "validar e promover",
           "prior_conversation_url": "https://chatgpt.com/c/antiga-9",
           "uncertain_content": "PROMPT ANTIGO SECRETO NAO REPETIR"}
    brief = mem.build_rotation_brief(ctx, 20000)
    for needle in ("Objetivo", "Estado atual", "O que fazer agora",
                   "Decisoes vigentes", "Historico",
                   "https://chatgpt.com/c/antiga-9",
                   "NUNCA" if "NUNCA" in brief else "nunca"):
        assert needle in brief
    assert "PROMPT ANTIGO SECRETO NAO REPETIR" not in brief


def test_record_size_caps(tmp_path):
    mem = _mem(tmp_path)
    with pytest.raises(ValueError):
        mem.record_adr("x" * 5000, "motivo")
    with pytest.raises(ValueError):
        mem.record_lesson("texto", "e" * 5000)
    with pytest.raises(ValueError):
        mem.record_candidate("bugfix", "p.diff", "")
    with pytest.raises(ValueError):
        mem.recall("q", limit="5")
    with pytest.raises(ValueError):
        mem.compact_brief(0)


def test_json_files_are_lf_and_parseable(tmp_path):
    mem = _mem(tmp_path)
    mem.record_adr("D", "R")
    mem.record_lesson("T", "run-1 ver a.py:1")
    mem.record_candidate("k", "p", "SUCCESS")
    for name in ("adrs.json", "lessons.json", "candidates.json"):
        raw = (mem.memory_dir / name).read_bytes()
        assert b"\r" not in raw
        json.loads(raw.decode("utf-8"))


def test_cross_instance_writes_do_not_lose_updates(tmp_path):
    import concurrent.futures

    first = _mem(tmp_path)
    second = ProgramMemory(tmp_path / "ws")

    def write(mem, prefix):
        for i in range(20):
            mem.record_candidate(
                "parallel",
                f"{prefix}-{i}.diff",
                "SUCCESS",
                run_id=f"run-{prefix}",
                task_id=f"T-{i}",
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(write, first, "a"),
            pool.submit(write, second, "b"),
        ]
        for future in futures:
            future.result(timeout=10)

    items = ProgramMemory(tmp_path / "ws").get_candidates("parallel")
    assert len(items) == 40
    assert {item["patch_ref"] for item in items} == {
        *(f"a-{i}.diff" for i in range(20)),
        *(f"b-{i}.diff" for i in range(20)),
    }


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_windows_publication_retries_only_same_fsynced_snapshot(tmp_path, monkeypatch, winerror):
    import os
    from types import SimpleNamespace
    from orchestrator import program_memory as module

    mem = _mem(tmp_path)
    replace = os.replace
    publications = []
    pauses = []

    def temporary_denial(source, target):
        publications.append((source, target, module.Path(source).read_text(encoding="utf8")))
        if len(publications) <= 2:
            error = PermissionError("transient Windows sharing refusal")
            error.winerror = winerror
            raise error
        replace(source, target)

    # Replace this module's facade only, without changing pathlib or other IO.
    monkeypatch.setattr(module, "os", SimpleNamespace(
        name="nt", fdopen=os.fdopen, fsync=os.fsync,
        replace=temporary_denial, unlink=os.unlink,
    ))
    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=pauses.append))
    mem._atomic_write_json(mem.candidates_file, {"one": ["snapshot"]})
    assert len(publications) == 3
    assert len(set(publications)) == 1
    assert pauses == [0.01, 0.02]
    assert json.loads(mem.candidates_file.read_text()) == {"one": ["snapshot"]}
    assert not list(mem.memory_dir.glob("*.tmp.*"))


@pytest.mark.parametrize("platform,winerror,expected_attempts", [
    ("nt", 5, 6), ("nt", 32, 6), ("nt", 33, 6),
    ("nt", None, 1), ("nt", 87, 1), ("posix", 5, 1),
])
def test_publication_refusal_is_bounded_preserves_previous_and_cleans_temp(
        tmp_path, monkeypatch, platform, winerror, expected_attempts):
    import os
    from types import SimpleNamespace
    from orchestrator import program_memory as module

    mem = _mem(tmp_path)
    previous = b'{"previous": true}\n'
    mem.candidates_file.write_bytes(previous)
    attempts = []
    pauses = []
    error = PermissionError("publication refused")
    if winerror is not None:
        error.winerror = winerror

    def refuse(source, target):
        attempts.append((source, target))
        raise error

    monkeypatch.setattr(module, "os", SimpleNamespace(
        name=platform, fdopen=os.fdopen, fsync=os.fsync,
        replace=refuse, unlink=os.unlink,
    ))
    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=pauses.append))
    with pytest.raises(PermissionError) as caught:
        mem._atomic_write_json(mem.candidates_file, {"unpublished": True})
    assert caught.value is error
    assert len(attempts) == expected_attempts
    assert len(set(attempts)) == 1
    assert len(pauses) == expected_attempts - 1
    assert mem.candidates_file.read_bytes() == previous
    assert not list(mem.memory_dir.glob("*.tmp.*"))


def test_windows_real_delete_sharing_refusal_reuses_snapshot(tmp_path, monkeypatch):
    import ctypes
    import os
    from ctypes import wintypes
    from types import SimpleNamespace
    from orchestrator import program_memory as module

    if os.name != "nt":
        pytest.skip("Windows native delete-sharing semantics")
    mem = _mem(tmp_path)
    mem.candidates_file.write_text('{"previous": true}\n', encoding="utf8")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # Read/write sharing is allowed; delete sharing deliberately remains held.
    handle = kernel.CreateFileW(str(mem.candidates_file), 0x80000000, 3,
                                None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value
    replace = os.replace
    observed = []
    snapshot_paths = []

    def real_replace(source, target):
        nonlocal handle
        snapshot_paths.append(source)
        try:
            replace(source, target)
        except PermissionError as exc:
            observed.append(exc.winerror)
            assert kernel.CloseHandle(handle)
            handle = None
            raise

    monkeypatch.setattr(module, "os", SimpleNamespace(
        name="nt", fdopen=os.fdopen, fsync=os.fsync,
        replace=real_replace, unlink=os.unlink,
    ))
    try:
        mem._atomic_write_json(mem.candidates_file, {"published": ["once"]})
    finally:
        if handle is not None:
            assert kernel.CloseHandle(handle)
    assert len(observed) == 1 and observed[0] in {5, 32, 33}
    assert len(snapshot_paths) == 2 and len(set(snapshot_paths)) == 1
    assert json.loads(mem.candidates_file.read_text()) == {"published": ["once"]}
    assert not list(mem.memory_dir.glob("*.tmp.*"))


def test_memory_writes_are_idempotent_by_content(tmp_path):
    mem = _mem(tmp_path)
    refs = {"run_id": "run-idem", "task_id": "T-1"}
    assert mem.record_adr("Mesma decisao", "mesma razao", refs) == "ADR-0001"
    assert mem.record_adr("Mesma decisao", "mesma razao", refs) == "ADR-0001"
    evidence = "run-idem ver orchestrator/engine.py:1516"
    assert mem.record_lesson("mesma licao", evidence) == "LES-0001"
    assert mem.record_lesson("mesma licao", evidence) == "LES-0001"
    assert mem.record_candidate(
        "implementation", "patch-ref", "SUCCESS",
        run_id="run-idem", task_id="T-1", notes="ok",
    ) == 0
    assert mem.record_candidate(
        "implementation", "patch-ref", "SUCCESS",
        run_id="run-idem", task_id="T-1", notes="ok",
    ) == 0
    stats = mem.stats()
    assert stats["adrs"] == 1
    assert stats["lessons"] == 1
    assert stats["candidates"] == 1


def test_engine_records_only_settled_evidence_backed_learning(tmp_path):
    from orchestrator.engine import OMAEngine
    from orchestrator.models import Candidate, MasterDecision, Task

    mem = _mem(tmp_path)
    engine = object.__new__(OMAEngine)
    engine.program_memory = mem
    engine.run_id = "run-learn"

    task = Task(
        id="T-1",
        run_id="run-learn",
        objective="separate project integration from task execution",
        metadata={
            "architecture_decision": "Use one integration coordinator as project writer",
            "decision_rationale": "candidate publication must stay serialized",
            "optimistic_rebase": {
                "applied": True,
                "touched_files": ["orchestrator/runtime.py"],
            },
        },
    )
    task.current_repair_round = 2
    candidate = Candidate(
        candidate_id="cand-learn",
        task_id="T-1",
        run_id="run-learn",
        patch="--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n",
    )
    decision = MasterDecision(
        decision="APPROVED",
        reasoning="reviewed package is compatible with the project invariant",
    )

    engine._record_program_learning(task, candidate, decision)
    first = mem.stats()
    assert first["lessons"] == 2
    assert first["adrs"] == 1

    # Resume/replay of the same settled task is idempotent.
    engine._record_program_learning(task, candidate, decision)
    assert mem.stats() == first
    assert "run-learn" in mem.list_lessons()[0]["evidence"]
    assert mem.list_adrs()[0]["refs"]["candidate_id"] == "cand-learn"
