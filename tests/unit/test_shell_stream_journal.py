"""Protected replay/compaction and real Canvas SSE, without model/account I/O."""
from concurrent.futures import ThreadPoolExecutor
import json
import queue
import time
import threading
import subprocess
import sys
import urllib.request
import uuid
import pytest

from sentra_canvas.shell_stream import ShellStreamJournal
from sentra_mcp.services.control_store import create_control_plane_store
from test_sentra_runtime_canvas_center_http import running_canvas, request


def preview(text, **extra):
    return {"status": "generating", "operation_id": "op-one", "content_revision": 0,
            "content": text, "activity": "Recebendo resposta", **extra}


def test_reopen_replays_protected_deltas_without_granting_authority(tmp_path):
    store = create_control_plane_store(tmp_path)
    journal = ShellStreamJournal(store, "owner")
    first = journal.publish("p", "s", "c", preview("Olá 🪐"))
    second = journal.publish("p", "s", "c", preview("Olá 🪐 haha"))
    assert journal.publish("p", "s", "c", preview("Olá 🪐 haha")) == second
    reopened = ShellStreamJournal(store, "owner")
    batch = reopened.read("p", first)
    assert len(batch["items"]) == 1
    event = batch["items"][0]
    assert event["kind"] == "delta" and event["text"] == " haha"
    assert event["base_sequence"] == first
    assert event["preview"]["authoritative"] is False
    assert event["preview"]["automatic_retry"] is False
    assert reopened.head("p", "c")["content"] == "Olá 🪐 haha"
    with store.connect("shell") as db:
        row = db.execute("SELECT protected_event FROM shell_stream_events ORDER BY seq DESC LIMIT 1").fetchone()
        assert row["protected_event"].startswith(("dpapi:", "keyring:"))
        assert "haha" not in row["protected_event"]
    assert ShellStreamJournal(store, "another").read("p")["items"] == []
    assert reopened.read("different")["items"] == []


def test_zero_is_a_live_cursor_and_stale_cursors_reset_to_current_snapshot(tmp_path, monkeypatch):
    import sentra_canvas.shell_stream as module
    monkeypatch.setattr(module, "MAX_EVENTS", 8)
    journal = ShellStreamJournal(create_control_plane_store(tmp_path), "owner")
    assert journal.read("p")["reset"] is True
    assert journal.read("p", 0)["reset"] is False
    for index in range(520):
        journal.publish("p", "s", "c", preview("🪐" * (index + 1)))
    assert journal.read("p", 1)["reset"] is True
    assert journal.read("p", 10**9)["reset"] is True
    assert journal.head("p", "c")["content"] == "🪐" * 520
    assert len(journal.read("p", 513)["items"]) == 7
    with journal.store.connect("shell") as db:
        assert db.execute("SELECT COUNT(*) AS n FROM shell_stream_events").fetchone()["n"] == 8


def test_new_round_and_confirmation_cannot_be_confused_with_duplicate_data(tmp_path):
    journal = ShellStreamJournal(create_control_plane_store(tmp_path), "owner")
    first = journal.publish("p", "s", "c", preview("resposta anterior longa"))
    journal.publish("p", "s", "c", preview("nova", content_revision=1))
    event = journal.read("p", first)["items"][0]
    assert event["kind"] == "snapshot" and event["text"] == "nova"
    final = journal.publish("p", "s", "c", preview("nova", status="committed", content_revision=1))
    assert journal.publish("p", "s", "c", preview("texto atrasado", status="interrupted")) == final
    assert journal.head("p", "c")["status"] == "committed"
    journal.publish("p", "s", "c", preview("próximo turno", operation_id="op-two"))
    assert journal.head("p", "c")["operation_id"] == "op-two"
    journal.publish("p", "s", "c", preview("resposta antiga atrasada", operation_id="op-one"))
    assert journal.head("p", "c")["operation_id"] == "op-two"


def test_native_ingestion_persists_without_a_renderer(tmp_path, monkeypatch):
    from sentra_canvas.shell_live import ShellLivePreviews
    from sentra_cli.shell_live_preview import LivePreviewWriter
    journal = ShellStreamJournal(create_control_plane_store(tmp_path), "owner")
    def persist(record, view):
        journal.publish(record["project_id"], record["space_id"], record["conversation_id"], view)
    live = ShellLivePreviews(tmp_path, on_change=persist)
    record = live.begin(project_id="p", space_id="s", conversation_id="c", operation_id="op-one")
    for key, value in live.environment(record).items():
        monkeypatch.setenv(key, value)
    writer = LivePreviewWriter()
    writer.send("persistido sem janela [[READ|nao-exibir]]")
    live.pump()
    assert journal.head("p", "c")["content"] == "persistido sem janela "
    live.close(record)
    assert journal.head("p", "c")["status"] == "interrupted"


def test_failed_snapshot_transaction_rolls_back_the_event_as_well(tmp_path, monkeypatch):
    import sentra_canvas.shell_stream as module
    journal = ShellStreamJournal(create_control_plane_store(tmp_path), "owner")
    before = journal.publish("p", "s", "c", preview("antes"))
    encode = module._encode
    calls = 0
    def fail_second(value):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated storage failure")
        return encode(value)
    with monkeypatch.context() as patch:
        patch.setattr(module, "_encode", fail_second)
        with pytest.raises(OSError):
            journal.publish("p", "s", "c", preview("antes depois"))
    assert journal.read("p", before)["items"] == []
    assert journal.head("p", "c")["content"] == "antes"
    journal.publish("p", "s", "c", preview("antes depois"))
    assert journal.head("p", "c")["content"] == "antes depois"


def test_a_slow_reader_connection_cannot_hold_the_publisher_condition_lock(tmp_path, monkeypatch):
    journal = ShellStreamJournal(create_control_plane_store(tmp_path), "owner")
    sequence = journal.publish("p", "s", "c", preview("primeiro"))
    entered, release = threading.Event(), threading.Event()
    connect = journal.store.connect
    def slow_connect(namespace, **kwargs):
        if threading.current_thread().name == "slow-stream-reader":
            entered.set()
            assert release.wait(5)
        return connect(namespace, **kwargs)
    monkeypatch.setattr(journal.store, "connect", slow_connect)
    reader = threading.Thread(target=lambda: journal.read("p", sequence), name="slow-stream-reader")
    reader.start()
    assert entered.wait(3)
    with ThreadPoolExecutor(max_workers=1) as pool:
        published = pool.submit(journal.publish, "p", "s", "c", preview("primeiro segundo"))
        try:
            assert published.result(timeout=2) > sequence
        finally:
            release.set()
            reader.join(timeout=5)
    assert journal.head("p", "c")["content"] == "primeiro segundo"


def test_ingestion_batch_commits_ten_heads_on_one_connection_and_rolls_back_together(tmp_path, monkeypatch):
    import sentra_canvas.shell_stream as module
    journal = ShellStreamJournal(create_control_plane_store(tmp_path), "owner")
    connect = journal.store.connect
    connections = []
    def counted(namespace, **kwargs):
        connections.append(namespace)
        return connect(namespace, **kwargs)
    monkeypatch.setattr(journal.store, "connect", counted)
    observations = [("p", "s", f"c-{index}", preview(f"batch-{index}")) for index in range(10)]
    sequences = journal.publish_many(observations)
    assert len(sequences) == 10 and len(set(sequences)) == 10
    assert connections == ["shell"]
    encode = module._encode
    calls = 0
    def fail_next_conversation(value):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("batch persist interrupted")
        return encode(value)
    with monkeypatch.context() as patch:
        patch.setattr(module, "_encode", fail_next_conversation)
        with pytest.raises(OSError, match="batch persist interrupted"):
            journal.publish_many([("p", "s", f"c-{index}", preview(f"new-{index}")) for index in range(10)])
    assert journal.read("p", sequences[-1])["items"] == []
    assert all(journal.head("p", f"c-{index}")["content"] == f"batch-{index}" for index in range(10))


def test_coalesced_reads_are_scope_isolated_immutable_and_invalidated_by_commit(tmp_path, monkeypatch):
    journal = ShellStreamJournal(create_control_plane_store(tmp_path), "owner")
    seq = journal.publish("p", "s", "c", preview("one"))
    connect, count = journal.store.connect, []
    def counted(namespace, **kwargs):
        count.append(namespace)
        return connect(namespace, **kwargs)
    monkeypatch.setattr(journal.store, "connect", counted)
    first = journal.read("p", 0)
    first["items"][0]["text"] = "caller mutation"
    assert journal.read("p", 0)["items"][0]["text"] == "one"
    assert len(count) == 1
    assert journal.read("other", 0)["items"] == []
    journal.publish("p", "s", "c", preview("one two"))
    assert journal.read("p", seq)["items"][0]["text"] == " two"
    assert len(journal.read("p", 0)["items"]) == 2
    def cutover():
        raise RuntimeError("SQLite authority was replaced")
    monkeypatch.setattr(journal.store, "assert_active", cutover)
    with pytest.raises(RuntimeError, match="authority was replaced"):
        journal.read("p", 0)


def test_native_batch_failure_retries_all_consumed_fragments_without_replaying_producer(tmp_path, monkeypatch):
    from sentra_canvas.shell_live import ShellLivePreviews
    from sentra_cli.shell_live_preview import LivePreviewWriter
    attempts = []
    def persist(pairs):
        attempts.append([view["content"] for _, view in pairs])
        return [len(attempts) > 1] * len(pairs)
    live = ShellLivePreviews(tmp_path, on_change=lambda *_: pytest.fail("pump must batch"), on_batch=persist)
    records = []
    for index in range(10):
        record = live.begin(project_id="p", space_id="s", conversation_id=f"c-{index}", operation_id=f"op-{index}")
        records.append(record)
        for key, value in live.environment(record).items():monkeypatch.setenv(key, value)
        LivePreviewWriter().send(f"batch-{index}")
    live.pump()
    assert all("published" not in record for record in records)
    live.pump()
    assert attempts == [[f"batch-{index}" for index in range(10)]] * 2
    assert all(record["published"]["content"] == f"batch-{index}" for index, record in enumerate(records))


def test_abrupt_producer_process_exit_loses_no_committed_event(tmp_path):
    script = """
import os, sys
from sentra_canvas.shell_stream import ShellStreamJournal
from sentra_mcp.services.control_store import create_control_plane_store
journal = ShellStreamJournal(create_control_plane_store(sys.argv[1]), 'owner')
journal.publish_many([('p','s','c-'+str(i),{'status':'generating','operation_id':'op-'+str(i),
    'content':'persisted before abrupt process exit '+str(i)}) for i in range(10)])
os._exit(37)
"""
    result = subprocess.run([sys.executable, "-B", "-c", script, str(tmp_path)], capture_output=True, timeout=30)
    assert result.returncode == 37, result.stderr.decode(errors="replace")
    reopened = ShellStreamJournal(create_control_plane_store(tmp_path), "owner")
    events = reopened.read("p", 0)["items"]
    assert len(events) == 10
    assert [event["sequence"] for event in events] == sorted(event["sequence"] for event in events)
    for index in range(10):
        head = reopened.head("p", f"c-{index}")
        assert head["content"] == "persisted before abrupt process exit " + str(index)
        assert head["automatic_retry"] is False and head["authoritative"] is False


def test_web_observation_ledger_survives_more_than_512_revisions(tmp_path):
    from browser.streaming import StreamingLedger, MAX_FRAMES_PER_MESSAGE
    store = create_control_plane_store(tmp_path)
    ledger = StreamingLedger(store)
    scope = {"principal": "principal-stream-one", "conversation_id": "conversation-stream-one",
             "message_id": "message-stream-one"}
    for revision in range(600):
        ledger.record_frame(**scope, revision=revision, text="conteúdo 🪐 " + str(revision))
    assert ledger.latest(**scope)["revision"] == 599
    assert ledger.read_content(**scope, revision=599)["content"] == "conteúdo 🪐 599"
    assert len(ledger.history(**scope, limit=MAX_FRAMES_PER_MESSAGE)["frames"]) == MAX_FRAMES_PER_MESSAGE
    with pytest.raises(FileNotFoundError):
        ledger.read_content(**scope, revision=0)
    with pytest.raises(ValueError):
        ledger.record_frame(**scope, revision=599, text="conflito")
    with pytest.raises(ValueError):
        ledger.record_frame(**scope, revision=1, text="reordenação")


def test_a_failed_presentation_write_is_retried_without_rereading_or_resending_the_producer(tmp_path, monkeypatch):
    from sentra_canvas.shell_live import ShellLivePreviews
    from sentra_cli.shell_live_preview import LivePreviewWriter
    seen = []
    def persist(record, snapshot):
        seen.append(snapshot["content"])
        return len(seen) != 1
    live = ShellLivePreviews(tmp_path, on_change=persist)
    record = live.begin(project_id="p", space_id="s", conversation_id="c", operation_id="op")
    for key, value in live.environment(record).items():
        monkeypatch.setenv(key, value)
    LivePreviewWriter().send("apenas uma geração")
    live.pump()
    live.pump()
    assert seen == ["apenas uma geração", "apenas uma geração"]
    live.close(record)


def _frame(response):
    lines = []
    while True:
        line = response.readline()
        if not line:
            raise EOFError("SSE ended before a complete frame")
        if line.strip():
            lines.append(line.decode().rstrip())
        elif lines:
            fields = dict(line.split(": ", 1) for line in lines)
            fields["data"] = json.loads(fields["data"])
            return fields


def _scope(app, monkeypatch):
    monkeypatch.setattr(app, "model_catalog", lambda: {"models": ["sentra/test-one"]})
    project = app.create_workspace("Stream")['id']
    def call(action, **kw):
        return app.shell_bridge({"action": action, "project_id": project,
            "request_key": "stream-" + uuid.uuid4().hex, **kw})['value']
    home = call("home")
    space = home['space']['space_id']
    dot = call("dot_create", space_id=space, name="StreamDot", role="specialist", model="sentra/test-one")
    conversation = call("conversation_create", space_id=space, dot_id=dot['dot_id'])
    monkeypatch.setattr(app._shell_runtime, "_execute", lambda _oid: None)
    operation = call("message_send", space_id=space, conversation_id=conversation['conversation_id'], content="QA sem inferência")
    return project, space, conversation['conversation_id'], operation['operation_id']


def test_real_sse_authentication_reconnect_and_head_scope(tmp_path, monkeypatch):
    with running_canvas(tmp_path) as (app, server):
        project, space, conversation, operation = _scope(app, monkeypatch)
        path = '/api/shell/stream?project_id=' + project
        assert request(server, path, authorized=False)[0] == 401
        assert request(server, path + '&after=-1')[0] == 400
        assert request(server, '/api/shell/stream?project_id=missing')[0] in {400, 403}
        base = f'http://127.0.0.1:{server.server_port}'
        headers = {'Authorization': 'Bearer ' + server.secret}
        journal = app._shell_runtime.stream
        with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers), timeout=4) as response:
            assert response.headers['Content-Type'].startswith('text/event-stream')
            assert _frame(response)['event'] == 'snapshot'
            first = journal.publish(project, space, conversation, preview('primeiro', operation_id=operation))
            event = _frame(response)
            assert int(event['id']) == first
            assert event['data']['text'] == 'primeiro'
        second = journal.publish(project, space, conversation, preview('primeiro segundo', operation_id=operation))
        with urllib.request.urlopen(urllib.request.Request(base + path, headers={**headers, 'Last-Event-ID': str(first)}), timeout=4) as response:
            event = _frame(response)
            assert event['data']['text'] == ' segundo' and int(event['id']) == second
        code, head = request(server, f'/api/shell/stream/head?project_id={project}&space_id={space}&conversation_id={conversation}')
        assert code == 200 and head['content'] == 'primeiro segundo' and head['persisted'] is True
        assert request(server, f'/api/shell/stream/head?project_id={project}&space_id=wrong&conversation_id={conversation}')[0] in {400, 403}


def test_twenty_consumers_observe_ten_streams_on_one_project_without_model_io(tmp_path, monkeypatch):
    with running_canvas(tmp_path) as (app, server):
        project, space, original_conversation, _ = _scope(app, monkeypatch)
        with app._shell_runtime.control.store.connect('shell') as db:
            dot = app._shell_runtime.control.shell._entity(db, app._shell_runtime.owner, project, 'conversation', original_conversation)['dot_id']
        sources = []
        for i in range(10):
            def call(action, **kw):
                return app.shell_bridge({'action': action, 'project_id': project, 'space_id': space,
                    'request_key': 'load-' + uuid.uuid4().hex, **kw})['value']
            conversation = call('conversation_create', dot_id=dot)['conversation_id']
            operation = call('message_send', conversation_id=conversation, content='QA sintético ' + str(i))['operation_id']
            sources.append((conversation, operation))
        started = queue.Queue()
        url = f'http://127.0.0.1:{server.server_port}/api/shell/stream?project_id={project}'
        def consume():
            req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + server.secret})
            with urllib.request.urlopen(req, timeout=10) as response:
                assert _frame(response)['event'] == 'snapshot'
                started.put(True)
                events = [_frame(response)['data'] for _ in range(10)]
                return [event['conversation_id'] for event in events]
        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(consume) for _ in range(20)]
            for _ in futures:
                started.get(timeout=15)
            for i, (conversation, operation) in enumerate(sources):
                app._shell_runtime.stream.publish(project, space, conversation, preview(f'texto {i}', operation_id=operation))
            for future in futures:
                assert future.result(timeout=15) == [conversation for conversation, _ in sources]
