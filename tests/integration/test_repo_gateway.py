"""Gateway do repositório — operações compactas, segurança e compressão."""
import pytest

from repository.gateway import CommandGateway


@pytest.fixture
def gw(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    import git
    git.Repo.init(root)
    (root / "orchestrator").mkdir()
    (root / "orchestrator" / "engine.py").write_text(
        "\n".join(f"x_{i} = {i}" for i in range(1, 301)) + "\n")
    (root / "orchestrator" / "quality_gate.py").write_text("READY_FOR_MASTER = True\n")
    return CommandGateway(root)


@pytest.mark.asyncio
async def test_read_pagination_and_alias(gw):
    sess = gw.open_session()
    out = await gw.execute(sess, "[[R|orchestrator/engine.py|1|250]]", agent_id="executor-04",
                           task_id="T-1", role="executor")
    assert "F01" in out and "LINES 1-250/300" in out
    # segunda leitura idêntica do cache? muda last_activity mas retorna conteúdo
    out2 = await gw.execute(sess, "[[R|F01|1|10]]", agent_id="executor-04", task_id="T-1", role="executor")
    assert "x_1" in out2


@pytest.mark.asyncio
async def test_search_tree_symbol(gw):
    sess = gw.open_session()
    s = await gw.execute(sess, "[[S|READY_FOR_MASTER|orchestrator]]", agent_id="e1", task_id="T-1", role="executor")
    assert "quality_gate.py" in s
    t = await gw.execute(sess, "[[T|orchestrator|3]]", agent_id="e1", task_id="T-1", role="executor")
    assert "engine.py" in t
    (sess.repository_root / "orchestrator" / "sym.py").write_text("class MyClass:\n    pass\n")
    sym = await gw.execute(sess, "[[SYM|MyClass]]", agent_id="e1", task_id="T-1", role="executor")
    assert "sym.py" in sym


@pytest.mark.asyncio
async def test_unknown_operation_blocked(gw):
    sess = gw.open_session()
    out = await gw.execute(sess, "[[DELETE_WINDOWS]]", agent_id="e1", task_id="T-1", role="executor")
    assert "UNKNOWN_OPERATION" in out


@pytest.mark.asyncio
async def test_path_traversal_blocked(gw):
    sess = gw.open_session()
    out = await gw.execute(sess, "[[R|../../secret.env|1|10]]", agent_id="e1", task_id="T-1", role="executor")
    assert "DENIED" in out


@pytest.mark.asyncio
async def test_unauthorized_write_blocked(gw):
    sess = gw.open_session()
    a = gw.stage_artifact(sess, "hello")
    out = await gw.execute(sess, f"[[W|orchestrator/x.py|{a}]]", agent_id="planner-1",
                           task_id="T-1", role="planner")
    assert "DENIED" in out  # planner não tem W; W é restrito ao master


@pytest.mark.asyncio
async def test_patch_apply_and_rollback(gw):
    sess = gw.open_session()
    target = sess.repository_root / "orchestrator" / "engine.py"
    before = target.read_bytes()
    patch = ("--- a/orchestrator/engine.py\n+++ b/orchestrator/engine.py\n"
             "@@ -1,1 +1,2 @@\n x_1 = 1\n+# patched\n")
    p = gw.stage_patch(sess, patch)
    out = await gw.execute(sess, f"[[PATCH|{p}]]", agent_id="executor-1", task_id="T-1", role="executor")
    assert out.startswith("PATCH OK")
    assert "# patched" in target.read_text()
    # rollback transacional
    txn_id = [k for k in gw.txns._txns][-1]
    rb = await gw.execute(sess, f"[[ROLLBACK|{txn_id}]]", agent_id="repair-1", task_id="T-1", role="repair")
    assert "ROLLBACK OK" in rb
    assert target.read_bytes() == before


@pytest.mark.asyncio
async def test_patch_syntax_failure_rollbacks(gw):
    sess = gw.open_session()
    (sess.repository_root / "orchestrator" / "bad.py").write_text("x = 1\n")
    patch = ("--- a/orchestrator/bad.py\n+++ b/orchestrator/bad.py\n"
             "@@ -1,1 +1,2 @@\n x = 1\n+def broken(:\n")
    p = gw.stage_patch(sess, patch)
    out = await gw.execute(sess, f"[[PATCH|{p}]]", agent_id="executor-1", task_id="T-1", role="executor")
    assert "ROLLBACK" in out
    assert "def broken(:" not in (sess.repository_root / "orchestrator" / "bad.py").read_text()


@pytest.mark.asyncio
async def test_workspace_escape_patch_blocked(gw):
    sess = gw.open_session()
    p = gw.stage_patch(sess, "--- a/../../evil.txt\n+++ b/../../evil.txt\n@@ -0,0 +1 @@\n+x\n")
    out = await gw.execute(sess, f"[[PATCH|{p}]]", agent_id="executor-1", task_id="T-1", role="executor")
    assert "DENIED" in out or "FAIL" in out


@pytest.mark.asyncio
async def test_audit_and_status_diff(gw):
    sess = gw.open_session()
    await gw.execute(sess, "[[STATUS]]", agent_id="e1", task_id="T-1", role="executor")
    await gw.execute(sess, "[[R|orchestrator/engine.py|1|5]]", agent_id="e1", task_id="T-1", role="executor")
    assert any(a["operation"] == "STATUS" and a["status"] == "SUCCESS" for a in gw.audit)
    d = await gw.execute(sess, "[[DIFF]]", agent_id="e1", task_id="T-1", role="executor")
    assert isinstance(d, str)


@pytest.mark.asyncio
async def test_read_cache_hit(gw):
    sess = gw.open_session()
    await gw.execute(sess, "[[R|orchestrator/quality_gate.py|1|5]]", agent_id="e1", task_id="T-1", role="executor")
    out = await gw.execute(sess, "[[R|orchestrator/quality_gate.py|1|5]]", agent_id="e1", task_id="T-1", role="executor")
    assert "CACHE_HIT" in out
    assert gw.cache_hits >= 1


@pytest.mark.asyncio
async def test_result_pagination_next(gw):
    sess = gw.open_session()
    (sess.repository_root / "big.txt").write_text("\n".join(f"l{i}" for i in range(500)))
    out = await gw.execute(sess, "[[R|big.txt|1|500]]", agent_id="e1", task_id="T-1", role="executor")
    assert "MORE=true" in out
    # extrai RESULT_ID
    import re
    m = re.search(r"RESULT_ID=(RES-[A-F0-9]+)", out)
    assert m
    nxt = await gw.execute(sess, f"[[NEXT|{m.group(1)}|200]]", agent_id="e1", task_id="T-1", role="executor")
    assert "l200" in nxt or "OFFSET=200" in nxt
