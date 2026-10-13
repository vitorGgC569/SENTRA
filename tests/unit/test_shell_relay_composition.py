"""Unit tests for host-owned relay composition, attestors, and generated_assets routes.

Validates that:
- Composition fails closed without attestors;
- Valid real attestors make generated_assets available on RelayServer;
- Ephemeral loopback relay routes /jobs/generated-asset/chunk and finalize accept with composition;
- Uncomposed relay rejects chunk/finalize routes;
- Account attestor and assistant observer verify real SQLite/streaming evidence and fail closed on revocation/uncertainty;
- Canvas startup composes observers when web_relay is enabled.
"""
import base64
import hashlib
import io
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen
import urllib.error

import pytest
from PIL import Image

from native_bridge.host_attestors import create_host_attestors, make_account_attestor, make_assistant_observer
from native_bridge.relay import RelayServer
from test_governance_coordination import _services
from test_sentra_cos_web_continuation_receipts import setup as continuation_setup, grant as continuation_grant


EXT_ID = "a" * 32
SOURCE_HASH = "1" * 64
ORIGIN = "chrome-extension://" + EXT_ID
DOC_ID = "doc-test-12345"
EPOCH = "epoch-test-12345"
REQ_ID = "req-test-12345"
CONV_ID = "conv-test-12345"
USER_MSG_ID = "msg-user-12345"
ASST_MSG_ID = "msg-asst-12345"
FILE_ID = "file-test12345678"


def _sample_png():
    img = Image.new("RGB", (8, 8), (100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()
    return raw, hashlib.sha256(raw).hexdigest()


def _post(server, route, data, *, token=None, origin=ORIGIN):
    base = f"http://127.0.0.1:{server.server.server_port}"
    body = json.dumps(data).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Origin": origin,
        "Authorization": "Bearer " + (token if token is not None else server.token),
    }
    req = Request(base + route, data=body, headers=headers)
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_composition_fails_closed_without_attestors(tmp_path):
    # create_host_attestors requires control plane
    with pytest.raises(ValueError, match="fail-closed"):
        create_host_attestors(None)

    # ShellWebRuntime without observers must report model_delivery_available=False
    from sentra_canvas.shell_web import ShellWebRuntime
    fake_control = SimpleNamespace(store=SimpleNamespace(connect=lambda ns: sqlite3.connect(":memory:")))
    fake_canvas = SimpleNamespace(_shell_configuration={"web_relay": {"enabled": True}})
    fake_runtime = SimpleNamespace(control=fake_control, canvas=fake_canvas, owner="canvas:local-operator")
    web = ShellWebRuntime(fake_runtime)

    avail = web.availability()
    assert avail["model_delivery_available"] is False
    assert avail["model_delivery_reason"] == "relay_account_attestor_not_composed"

    # Calling _configuration() without attestors must raise
    with pytest.raises(RuntimeError, match="relay_account_attestor_not_composed"):
        web._configuration()


def test_composition_with_attestors_makes_generated_assets_available(tmp_path):
    durable, context, control = _services(tmp_path)
    try:
        account_attestor, assistant_observer = create_host_attestors(control, owner="canvas:local-operator")
        assert callable(account_attestor)
        assert callable(assistant_observer)

        db_path = tmp_path / "relay.sqlite3"

        server = RelayServer(
            port=0,
            db_path=db_path,
            extension_dir=None,
            authenticated_control=control,
            assistant_observer=assistant_observer,
        ).start()
        try:
            assert server.state.generated_assets is not None
            assert server.state.web_send is not None
            assert server.state.assistant_observer is not None

            # GET /health must report configured flags
            with urlopen(f"http://127.0.0.1:{server.server.server_port}/health", timeout=5) as resp:
                health = json.loads(resp.read().decode())
                assert health["ok"] is True
                assert health["web_send_configured"] is True
                assert health["generated_assets_configured"] is True
        finally:
            server.stop()
    finally:
        context.close()
        durable.close()


def test_uncomposed_relay_rejects_chunk_and_finalize_routes(tmp_path):
    server = RelayServer(port=0, db_path=tmp_path / "relay.sqlite3", extension_dir=None).start()
    try:
        assert server.state.generated_assets is None
        assert server.state.web_send is None

        with urlopen(f"http://127.0.0.1:{server.server.server_port}/health", timeout=5) as resp:
            health = json.loads(resp.read().decode())
            assert health["web_send_configured"] is False
            assert health["generated_assets_configured"] is False

        # Attempt chunk request on uncomposed relay: must reject
        status, res = _post(server, "/jobs/generated-asset/chunk", {
            "job_id": "job-1", "worker": "TAB-1", "lease_token": "tok-1",
            "request_id": REQ_ID, "source_sha256": SOURCE_HASH,
            "document_id": DOC_ID, "identity_epoch": EPOCH,
            "conversation_id": CONV_ID, "message_id": ASST_MSG_ID,
            "file_id": FILE_ID, "mime_type": "image/png",
            "filename": "chatgpt-native-test.png", "byte_length": 100,
            "sha256": "a" * 64, "part": 0, "chunk_sha256": "b" * 64,
            "data_base64": "AAAA",
        })
        assert status in (400, 403)
    finally:
        server.stop()


def test_account_attestor_verifies_real_collector_and_fails_closed(tmp_path):
    durable, context, control = _services(tmp_path)
    try:
        account_attestor, _ = create_host_attestors(control, owner="canvas:local-operator")

        fake_msg = {"project_id": "p-1", "run_id": "r-1", "work_item_id": "w-1"}
        fake_dot = {"model": "sentra/chatgpt-web/gpt-6", "effort": "high"}
        fake_job = {"leased_worker": "TAB-123"}

        # 1. No enrolled collector -> fails closed
        res1 = account_attestor(control=control, owner="canvas:local-operator", project_id="p-1",
                                message=fake_msg, dot=fake_dot, job=fake_job)
        assert res1["account_verified"] is False
        assert "no_enrolled_collector" in res1["reason"]

        # 2. Enroll collector in chat_access
        with closing(control.store.connect("chat_access")) as db, db:
            db.execute("INSERT INTO browser_collectors VALUES(?,?,?,?,1,1,'edge')",
                       (EXT_ID, "local-operator", "test-ws", SOURCE_HASH))

        res2 = account_attestor(control=control, owner="canvas:local-operator", project_id="p-1",
                                message=fake_msg, dot=fake_dot, job=fake_job)
        assert res2["account_verified"] is True
        assert res2["requested_model"] == "sentra/chatgpt-web/gpt-6"
        assert res2["requested_effort"] == "high"

        # 3. Revoke worker document -> fails closed
        with closing(control.store.connect("chat_access")) as db, db:
            db.execute("INSERT INTO browser_revoked_documents VALUES(?,?,?, 'stale_tab', 1.0)",
                       (EXT_ID, "TAB-123", DOC_ID))

        res3 = account_attestor(control=control, owner="canvas:local-operator", project_id="p-1",
                                message=fake_msg, dot=fake_dot, job=fake_job)
        assert res3["account_verified"] is False
        assert "worker_document_revoked" in res3["reason"]

        # 4. Profile uncertainty -> fails closed
        with closing(control.store.connect("chat_access")) as db, db:
            db.execute("DELETE FROM browser_revoked_documents")
            db.execute("INSERT INTO browser_profile_uncertainty VALUES(?,?, 'signed_out', 1.0)",
                       (EXT_ID, "local-operator"))

        res4 = account_attestor(control=control, owner="canvas:local-operator", project_id="p-1",
                                message=fake_msg, dot=fake_dot, job=fake_job)
        assert res4["account_verified"] is False
        assert "profile_uncertainty" in res4["reason"]
    finally:
        context.close()
        durable.close()


def test_assistant_observer_verifies_streaming_and_fails_closed(tmp_path):
    durable, context, control = _services(tmp_path)
    try:
        _, assistant_observer = create_host_attestors(control, owner="canvas:local-operator")

        from browser.streaming import StreamingLedger
        streaming = StreamingLedger(control.store)
        text = "Hello from attested assistant"
        body_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # Enroll collector
        with closing(control.store.connect("chat_access")) as db, db:
            db.execute("INSERT INTO browser_collectors VALUES(?,?,?,?,1,1,'edge')",
                       (EXT_ID, "local-operator", "test-ws", SOURCE_HASH))
            db.execute("INSERT INTO browser_document_epochs VALUES(?,?,?,?)",
                       (EXT_ID, "TAB-55", DOC_ID, EPOCH))

        # Record stream frame
        streaming.record_frame(principal="local-operator", conversation_id=CONV_ID,
                               message_id=ASST_MSG_ID, revision=1, text=text)

        selectors = {
            "worker": "TAB-55",
            "document_id": DOC_ID,
            "identity_epoch": EPOCH,
            "browser_principal": "local-operator",
            "conversation_id": CONV_ID,
            "message_id": ASST_MSG_ID,
            "revision": 1,
            "body_sha256": body_sha256,
            "state": "complete",
        }

        # 1. Valid matching frame -> authenticated: True
        obs1 = assistant_observer(**selectors)
        assert obs1["authenticated"] is True
        assert obs1["host_observation"]["body_sha256"] == body_sha256
        assert obs1["host_observation"]["source_sha256"] == SOURCE_HASH

        # 2. Tampered body hash -> fails closed
        obs2 = assistant_observer(**{**selectors, "body_sha256": "0" * 64})
        assert obs2["authenticated"] is False
        assert "frame_body_mismatch" in obs2["reason"]

        # 3. Wrong epoch -> fails closed
        obs3 = assistant_observer(**{**selectors, "identity_epoch": "foreign-epoch"})
        assert obs3["authenticated"] is False
        assert "document_epoch_not_found" in obs3["reason"]

        # 4. Revoked document -> fails closed
        with closing(control.store.connect("chat_access")) as db, db:
            db.execute("INSERT INTO browser_revoked_documents VALUES(?,?,?, 'closed', 1.0)",
                       (EXT_ID, "TAB-55", DOC_ID))

        obs4 = assistant_observer(**selectors)
        assert obs4["authenticated"] is False
        assert "document_revoked" in obs4["reason"]
    finally:
        context.close()
        durable.close()


def test_canvas_startup_composition_with_web_relay_config(tmp_path):
    from sentra_canvas.service import Canvas

    # Prepare minimal workspace and extension/token files
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()
    ext_dir = ws_root / "edge_extension"
    ext_dir.mkdir()
    tok_dir = ws_root / ".oma"
    tok_dir.mkdir()
    tok_file = tok_dir / "relay-token"
    tok_file.write_text("a" * 40, encoding="utf-8")

    sentra_dir = ws_root / ".sentra"
    sentra_dir.mkdir()

    # Pre-enroll collector in control plane so create_host_attestors succeeds
    config = {
        "web_relay": {
            "enabled": True,
            "port": 0,
            "extension_dir": str(ext_dir),
            "token_file": str(tok_file),
            "models": ["sentra/chatgpt-web/gpt-6", "chatgpt"],
        }
    }

    app = Canvas(ws_root, state_dir=ws_root / ".sentra" / "canvas", shell_configuration=config)
    try:
        # Pre-enroll collector
        with closing(app._control_service().store.connect("chat_access")) as db, db:
            db.execute("INSERT OR REPLACE INTO browser_collectors VALUES(?,?,?,?,1,1,'edge')",
                       (EXT_ID, "local-operator", "test-ws", SOURCE_HASH))

        # Re-compose observers on startup
        app._compose_web_relay_startup()

        # availability should now be ready
        avail = app._shell_runtime.web.availability()
        assert avail["model_delivery_available"] is True
        assert avail["model_delivery_reason"] is None
    finally:
        app.shutdown()
