"""E2E Self-Improvement: agente -> sessão -> protocolo -> patch sandbox -> teste ->
falha -> reparo -> teste -> diff -> QualityGate -> Improvement Candidate."""
import pytest

from repository.gateway import CommandGateway
from self_improvement.engine import SelfImprovementEngine
from self_improvement.promotion import decide
from orchestrator.quality_gate import QualityGate, QuorumPolicy
from orchestrator.models import Candidate, Task, ValidationReport


def _seed_repo(root):
    import git
    (root / "app").mkdir(exist_ok=True)
    (root / "app" / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_calc.py").write_text(
        "from app.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    repo = git.Repo.init(root)
    repo.git.add(A=True)
    repo.index.commit("baseline")


@pytest.mark.asyncio
async def test_self_improvement_full_chain(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _seed_repo(root)
    gw = CommandGateway(root)
    sess = gw.open_session()
    engine = SelfImprovementEngine(gw)

    # agente recebe tarefa -> abre sessão (já aberta) -> lê código via protocolo
    r = await gw.execute(sess, "[[R|app/calc.py|1|10]]", agent_id="executor-01",
                         task_id="T-SI-1", role="executor")
    assert "return a - b" in r
    # pesquisa símbolos
    s = await gw.execute(sess, "[[SYM|add]]", agent_id="executor-01", task_id="T-SI-1", role="executor")
    assert "calc.py" in s
    # cria alteração (patch com bug proposital ainda? aqui já propõe a correção)
    good_patch = ("--- a/app/calc.py\n+++ b/app/calc.py\n"
                  "@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n")
    p = gw.stage_patch(sess, good_patch)
    # demonstra falha primeiro: patch com sintaxe inválida é descartado no sandbox
    bad_patch = ("--- a/app/calc.py\n+++ b/app/calc.py\n"
                 "@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    def broken(:\n")
    bad_alias = gw.stage_patch(sess, bad_patch)
    cyc_fail = await engine.run_cycle(sess.session_id, "fix add", proposed_patch_alias=bad_alias)
    assert cyc_fail["verdict"] in ("DISCARD", "HOLD", "REJECT")
    # repara: ciclo com o patch correto
    cyc = await engine.run_cycle(sess.session_id, "fix add", proposed_patch_alias=p)
    assert cyc["verdict"] == "HOLD"  # no router means no independent cognitive validation
    assert cyc["proposal"]["all_passed"]
    assert "return a - b" in (root / "app" / "calc.py").read_text()
    # diff gerado
    d = await gw.execute(sess, "[[DIFF]]", agent_id="validator-01", task_id="T-SI-1", role="validator")
    assert "return a + b" not in d  # the active checkout never received the proposal
    # Quality Gate valida o candidato (3 aprovações + testes passando)
    gate = QualityGate(QuorumPolicy(validators_required=3, minimum_approvals=2,
                                    objective_test_required=True))
    task = Task(id="T-SI-1", run_id="si", objective="fix add")
    cand = Candidate(candidate_id="C-SI", task_id="T-SI-1", summary="fixed add", patch=good_patch)
    reports = [ValidationReport(validator_role=f"v{i}", status="APPROVED") for i in range(3)]
    from orchestrator.verification import CandidateVerifier
    evidence = await CandidateVerifier(root).verify(cand)
    passed, _, pkg = gate.evaluate(task, cand, reports, test_results=evidence)
    assert passed and pkg.status == "READY_FOR_MASTER"


@pytest.mark.asyncio
async def test_protected_promotion_requires_approval(tmp_path):
    d = decide(touches_protected=True, tests_passed=True, approvals=3, external_approval=False)
    assert d.verdict == "HOLD" and d.needs_external_approval is True
    d2 = decide(touches_protected=True, tests_passed=True, approvals=3, external_approval=True)
    assert d2.verdict == "PROMOTE"
