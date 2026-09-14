"""SelfImprovementEngine — usa o próprio OMA (não uma segunda engine paralela).

Fluxo: CURRENT -> Research -> Proposal -> Sandbox/Branch -> Implement(PATCH) ->
Validators/Tests -> Benchmark -> Regression -> QualityGate -> Candidate.
Promoção de PROTECTED_COMPONENTS exige validação forte/aprovação externa.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from repository.gateway import CommandGateway
from repository.parser import find_all
from self_improvement.evaluator import ScoreInput, compute
from self_improvement.promotion import decide
from self_improvement.sandbox import isolated_copy


@dataclass
class SwarmResult:
    total_chats: int
    critics: int
    implementers: int
    directives_executed: int
    patches_applied: int
    tests_pass: int
    tests_fail: int
    elapsed_s: float
    details: List[Dict[str, Any]] = field(default_factory=list)


class SelfImprovementEngine:
    def __init__(self, gateway: CommandGateway, router=None, quality_gate=None, *, engine_options=None):
        self.gateway = gateway
        self.router = router
        self.quality_gate = quality_gate
        self.engine_options = dict(engine_options or {})
        self.engine_options.setdefault("execution", gateway.execution)
        self.engine_options.setdefault("command_profiles", gateway.profiles)

    # Focos de pesquisa: cada preset distribui os chats sobre arquivos-alvo e
    # palavras-chave de ataque. Críticos caçam fragilidade; implementadores mapeiam
    # estrutura para propor melhorias.
    FOCUS_PRESETS: Dict[str, Dict[str, Any]] = {
        "bridge": {
            "files": [
                "edge_extension/service-worker.js",
                "edge_extension/content-script.js",
                "edge_extension/observer.js",
                "edge_extension/selectors.js",
                "native_bridge/protocol.py",
                "native_bridge/relay.py",
                "native_bridge/host.py",
                "browser/tab_pool.py",
                "browser/worker.py",
                "browser/protocol.py",
                "browser/extension_transport.py",
                "orchestrator/providers/extension_provider.py",
                "orchestrator/providers/playwright_provider.py",
                "orchestrator/projects.py",
            ],
            "critic_keywords": ["TAB_ERROR", "TIMEOUT", "UNKNOWN_OPERATION", "catch",
                                "sleep", "poll", "TODO", "FIXME", "assert", "except"],
            "dirs": ["edge_extension", "native_bridge", "browser"],
        },
    }

    async def _agent_directives(self, role: str, objective: str, idx: int,
                               focus: Optional[str] = None) -> str:
        """Chama o provider do OMA para obter diretivas; fallback determinístico se sem router."""
        if self.router is None:
            if focus in self.FOCUS_PRESETS:
                preset = self.FOCUS_PRESETS[focus]
                files = preset["files"]
                if role == "critic":
                    kw = preset["critic_keywords"][idx % len(preset["critic_keywords"])]
                    scope = preset["dirs"][idx % len(preset["dirs"])]
                    f = files[idx % len(files)]
                    n = (idx % 40) + 1
                    return (f"[[S|{kw}|{scope}]]\n"
                            f"[[R|{f}|{n}|{n + 59}]]")
                d = preset["dirs"][idx % len(preset["dirs"])]
                f = files[(idx + 3) % len(files)]
                return f"[[T|{d}|2]]\n[[R|{f}|1|60]]"
            if role == "critic":
                return "[[S|READY_FOR_MASTER|orchestrator]]\n[[R|orchestrator/quality_gate.py|1|60]]"
            return "[[T|orchestrator|2]]\n[[R|orchestrator/models.py|1|40]]"
        from orchestrator.providers.base import AgentRequest
        sys_prompt = ("Você tem acesso ao repositório via Local Repository Gateway. "
                      "NÃO gere shell; emita SOMENTE diretivas compactas [[OP|args]]. "
                      "Operações: [[R|path|ini|fim]] [[S|pattern|path]] [[T|path|depth]] "
                      "[[SYM|símbolo]] [[TEST|alvo]] [[DIFF]] [[STATUS]].")
        user = f"Role={role} chat={idx} Objetivo: {objective}. Emita 2-4 diretivas, uma por linha."
        req = AgentRequest(system_prompt=sys_prompt, user_prompt=user, role=role,
                           timeout=90, metadata={"task_id": f"swarm-{role}-{idx}"})
        try:
            resp = await self.router.execute(req)
            text = resp.content if resp.success else ""
            if "[[" not in text:
                return ("[[S|READY_FOR_MASTER|orchestrator]]" if role == "critic"
                        else "[[T|repository|2]]")
            return text
        except asyncio.CancelledError:
            raise
        except Exception:
            return "[[STATUS]]"

    async def _run_single_chat(self, session_id: str, role: str, idx: int,
                               objective: str,
                               focus: Optional[str] = None) -> Dict[str, Any]:
        from repository.session import RepositorySession
        session = self.gateway.sessions.get(session_id)
        text = await self._agent_directives(role, objective, idx, focus=focus)
        executed = 0
        patches = 0
        last_result = ""
        for d in find_all(text)[:4]:  # limite determinístico por chat
            res = await self.gateway.execute(session, d.raw, agent_id=f"{role}-{idx:02d}",
                                             task_id=f"swarm-{role}-{idx}", role=role)
            executed += 1
            last_result = res
            if d.operation == "PATCH" and res.startswith("PATCH OK"):
                patches += 1
        return {"role": role, "idx": idx, "directives": executed, "patches": patches,
                "tail": last_result[:300]}

    async def orchestrate_swarm(self, session_id: str, objective: str,
                                n_critics: int = 25, n_implementers: int = 25,
                                max_concurrency: int = 10,
                                focus: Optional[str] = None,
                                final_test: str = "[[TEST|all]]") -> SwarmResult:
        """Orquestra N chats (críticos + implementadores) com concorrência limitada.

        focus: preset de FOCUS_PRESETS que distribui os chats sobre arquivos-alvo
        (ex. "bridge" para a integração extensão/relay/pool).
        """
        if focus is not None and focus not in self.FOCUS_PRESETS:
            raise ValueError(f"unknown focus preset: {focus}")
        t0 = time.time()
        sem = asyncio.Semaphore(max_concurrency)

        async def _bounded(role: str, idx: int):
            async with sem:
                return await self._run_single_chat(session_id, role, idx, objective,
                                                   focus=focus)

        jobs = ([_bounded("critic", i) for i in range(n_critics)] +
                [_bounded("executor", i) for i in range(n_implementers)])
        details = await asyncio.gather(*jobs)
        # Teste/benchmark consolidados no fim (determinísticos, via gateway)
        session = self.gateway.sessions.get(session_id)
        test_out = await self.gateway.execute(session, final_test, agent_id="master",
                                              task_id="swarm-consolidation", role="master")
        tests_pass = test_out.count("passed") > 0 and "FAIL" not in test_out.splitlines()[0]
        return SwarmResult(
            total_chats=n_critics + n_implementers, critics=n_critics,
            implementers=n_implementers,
            directives_executed=sum(d["directives"] for d in details),
            patches_applied=sum(d["patches"] for d in details),
            tests_pass=1 if tests_pass else 0, tests_fail=0 if tests_pass else 1,
            elapsed_s=round(time.time() - t0, 2), details=details,
        )

    async def run_cycle(self, session_id: str, objective: str,
                        proposed_patch_alias: Optional[str] = None,
                        external_approval: bool = False) -> Dict[str, Any]:
        """Use the operational OMA runtime; never self-promote or invent approvals."""
        import uuid
        from orchestrator.models import Candidate
        from orchestrator.runtime import IntegratedRun
        from orchestrator.verification import CandidateVerifier

        session = self.gateway.sessions.get(session_id)
        patch = session.patch_registry.get(proposed_patch_alias) if proposed_patch_alias else None
        if proposed_patch_alias and patch is None:
            return {"verdict": "DISCARD", "reason": "unknown proposed patch alias"}
        verifier = CandidateVerifier(session.repository_root,
                                     self.engine_options.get("validation_commands"),
                                     self.engine_options.get("command_profiles"),
                                     self.engine_options.get("test_timeout",120),
                                     self.engine_options.get("execution"), self.engine_options.get("allowed_patch_paths"))
        baseline = await verifier.verify(Candidate(task_id="BASELINE", candidate_id="baseline"))
        proposal = None
        if patch:
            proposal = await verifier.verify(Candidate(task_id="PROPOSAL", candidate_id="proposal", patch=patch))
            if not proposal["all_passed"]:
                return {"verdict": "DISCARD", "reason": "proposed patch failed deterministic verification",
                        "baseline": baseline, "proposal": proposal}
        if self.router is None:
            return {"verdict": "HOLD", "reason": "configure an OMA router for independent validators and review",
                    "baseline": baseline, "proposal": proposal, "needs_external_approval": True}
        # Operator proposals enter the same OMA planner/executor/repair/gate.
        prompt = objective + ("\nOperator proposal (must be independently verified):\nBEGIN_OPERATOR_PATCH\n" + patch + "\nEND_OPERATOR_PATCH" if patch else "")
        run_id = "self-" + uuid.uuid4().hex[:12]
        runtime = IntegratedRun(session.repository_root, run_id, prompt, self.router, **self.engine_options)
        result = await runtime.run()
        runtime.store._atomic_write_json(runtime.store.run_dir / "baseline-tests.json", baseline)
        return {"verdict": "IMPROVEMENT_CANDIDATE" if result["status"] == "CANDIDATE_READY" else "DISCARD",
                "reason": "OMA candidate only; promotion is a separate explicit operator action",
                "baseline": baseline, "candidate": result, "needs_external_approval": True,
                "score": None, "benchmark_note": "No performance improvement claimed without an operator benchmark."}
