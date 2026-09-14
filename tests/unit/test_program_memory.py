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
