"""Dashboard: agregação offline + servidor efêmero. Nenhum envio, nenhum browser."""
import json
import threading
import urllib.error
import urllib.request

from dashboard import store


def _seed_run(root, run_id="R1"):
    d = root / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.json").write_text(json.dumps([{"id": "T-1"}]), encoding="utf-8")
    (d / "handoff.json").write_text(json.dumps(
        {"status": "FAILED", "completed_tasks": 0, "total_tasks": 1}), encoding="utf-8")
    (d / "conversations.json").write_text(json.dumps({"seats": {
        f"{run_id}:executor": {"role": "executor", "state": "CONFIRMED",
                               "url": "https://chatgpt.com/c/abc-1", "task_id": "T-1"}}}),
        encoding="utf-8")
    (d / "validations.json").write_text(json.dumps(
        [{"validator_role": "executor", "score": 9.6}]), encoding="utf-8")
    return d


def test_list_runs_and_chats(tmp_path):
    _seed_run(tmp_path, "R1")
    (tmp_path / "junk.txt").write_text("x", encoding="utf-8")
    runs = store.list_runs(tmp_path)
    assert [r["run_id"] for r in runs] == ["R1"]
    assert runs[0]["status"] == "FAILED"
    chats = store.run_chats(tmp_path / "R1")
    assert len(chats) == 1 and chats[0]["url"] == "https://chatgpt.com/c/abc-1"
    assert chats[0]["min_score"] == 9.6


def test_relay_jobs_filtered_and_clipped(tmp_path):
    from native_bridge.job_store import JobStore
    from native_bridge.protocol import ChatJob, ChatResult
    db = tmp_path / "relay.sqlite3"
    st = JobStore(str(db))
    st.submit(ChatJob(task_id="T-1", prompt="ola mundo", timeout_s=60))
    jid = st.submit(ChatJob(task_id="T-2", prompt="y" * 5000, timeout_s=60))
    first = st.poll("W1")
    assert first and first["job_id"] != jid  # FIFO: T-1 primeiro
    st.store_result(ChatResult(job_id=first["job_id"], task_id="T-1",
                               status="COMPLETED", result="ok", worker="W1"),
                    first["lease_token"])
    got = st.poll("W1")
    assert got["job_id"] == jid
    st.store_result(ChatResult(job_id=jid, task_id="T-2", status="COMPLETED",
                               result="r" * 5000, worker="W1"), got["lease_token"])
    st.close()
    jobs = store.relay_jobs(db, task_id="T-2")
    assert len(jobs) == 1
    assert jobs[0]["prompt"]["truncated"] is True
    assert jobs[0]["response"]["truncated"] is True
    assert store.relay_jobs(db, task_id="ZZZ") == []
    assert store.relay_jobs(tmp_path / "nope.sqlite3") == []


def test_relay_health_unreachable():
    h = store.relay_health("http://127.0.0.1:19999", timeout=1.0)
    assert h["reachable"] is False


def test_server_endpoints_offline(tmp_path):
    from dashboard.server import Handler
    from http.server import ThreadingHTTPServer
    _seed_run(tmp_path, "R9")
    Handler.roots = [tmp_path]
    Handler.relay_base = "http://127.0.0.1:19999"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def get(path):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                            timeout=10) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

        status, body = get("/api/overview")
        assert status == 200 and body["relay"]["reachable"] is False
        assert [r["run_id"] for r in body["workspaces"][0]["runs"]] == ["R9"]
        status, body = get("/api/chats?run_id=R9")
        assert status == 200 and len(body["chats"]) == 1
        status, _ = get("/api/chats?run_id=NOPE")
        assert status == 404
        status, body = get("/api/responses?url=https://chatgpt.com/c/abc-1")
        assert status == 200 and body["responses"] == []  # sem DB -> vazio, não erro
    finally:
        server.shutdown()
        server.server_close()


def _seed_broken_run(root):
    d = root / "RB"
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.json").write_text(json.dumps([
        {"id": "T-1", "objective": "fazer X", "status": "FAILED",
         "current_repair_round": 2},
        {"id": "T-2", "objective": "fazer Y", "status": "COMPLETED",
         "current_repair_round": 0}]), encoding="utf-8")
    (d / "handoff.json").write_text(json.dumps(
        {"status": "FAILED", "objective": "missao teste",
         "completed_tasks": 1, "total_tasks": 2}), encoding="utf-8")
    (d / "conversations.json").write_text(json.dumps({"seats": {
        "RB:executor": {"role": "executor", "state": "UNCERTAIN",
                        "url": "https://chatgpt.com/c/broken-1", "task_id": "T-1"},
        "RB:master": {"role": "master", "state": "CONFIRMED",
                      "url": "https://chatgpt.com/c/ok-1"}}}), encoding="utf-8")
    (d / "validations.json").write_text(json.dumps(
        [{"task_id": "T-1", "validator_role": "validator.logic",
          "score": 7.0, "status": "REJECTED"}]), encoding="utf-8")
    (d / "events.jsonl").write_text(json.dumps(
        {"event_type": "TASK_FAILED", "task_id": "T-1",
         "payload": {"reason": "DELIVERY_EXPIRED: motivo teste"}}) + "\n",
        encoding="utf-8")
    return d


def test_failures_and_summaries(tmp_path):
    run_dir = _seed_broken_run(tmp_path)
    from native_bridge.job_store import JobStore
    from native_bridge.protocol import ChatJob, ChatResult
    db = tmp_path / "relay.sqlite3"
    st = JobStore(str(db))
    st.submit(ChatJob(task_id="T-1", prompt="p", timeout_s=60))
    st.close()
    import sqlite3
    raw = sqlite3.connect(str(db))
    raw.execute("UPDATE jobs SET state='FAILED'")
    raw.commit()
    raw.close()

    chats = store.all_chats([tmp_path])
    assert {c["seat"] for c in chats} == {"RB:executor", "RB:master"}
    assert all(c["run_id"] == "RB" for c in chats)

    fails = store.failures([tmp_path], db)
    assert [s["seat"] for s in fails["seats"]] == ["RB:executor"]
    assert fails["counts"]["seats"] == 1
    assert fails["counts"]["jobs"] == 1
    assert fails["tasks"][0]["task_id"] == "T-1"
    assert fails["tasks"][0]["repairs"] == 2

    md = store.run_summary(run_dir, "RB", "proj-x")
    for needle in ("# RB", "Projeto: proj-x", "missao teste", "T-1 [FAILED]",
                   "broken-1", "7.0", "DELIVERY_EXPIRED"):
        assert needle in md

    label = tmp_path.name  # filho direto: rótulo = nome do root
    pmd = store.project_summary([tmp_path], label)
    assert "## RB [FAILED]" in pmd and "chats quebrados: 1" in pmd
    assert "nenhuma run" in store.project_summary([tmp_path], "zz-nope")


def test_server_v2_endpoints(tmp_path):
    from dashboard.server import Handler
    from http.server import ThreadingHTTPServer
    _seed_broken_run(tmp_path)
    Handler.roots = [tmp_path]
    Handler.relay_base = "http://127.0.0.1:19999"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def get(path):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                            timeout=10) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

        status, body = get("/api/conversations")
        assert status == 200 and len(body["conversations"]) == 2
        status, body = get("/api/conversations?state=UNCERTAIN")
        assert status == 200 and len(body["conversations"]) == 1
        status, body = get("/api/failures")
        assert status == 200 and body["counts"]["seats"] == 1
        status, body = get("/api/summary?run_id=RB")
        assert status == 200 and "# RB" in body["markdown"]
        status, _ = get("/api/summary?run_id=NOPE")
        assert status == 404
        label = tmp_path.name  # filho direto: rótulo = nome do root
        status, body = get("/api/summary?project=" + label)
        assert status == 200 and "## RB [FAILED]" in body["markdown"]
    finally:
        server.shutdown()
        server.server_close()
