"""Host-side Web revision history with central protected SQLite and opt-in ACL index."""
import sqlite3

import pytest

from sentra_mcp.services.web_history_store import WebHistoryStore, WebHistoryConflict


def test_streaming_revisions_encrypt_search_export_purge_and_restart(tmp_path):
    history = WebHistoryStore(tmp_path)
    scope = ("history-owner", "workspace-A")
    chat = "chat-12345"
    msg = "message-12345"
    assert history.record_frame(*scope, conversation_id=chat, message_id=msg,
                                revision=1, role="assistant", state="partial",
                                body="provisional alpha")["revision"] == 1
    assert history.record_frame(*scope, conversation_id=chat, message_id=msg,
                                revision=1, role="assistant", state="partial",
                                body="provisional alpha")["idempotent_replay"]
    with pytest.raises(WebHistoryConflict):
        history.record_frame(*scope, conversation_id=chat, message_id=msg,
                             revision=1, role="assistant", state="partial",
                             body="different")
    history.record_frame(*scope, conversation_id=chat, message_id=msg,
                         revision=2, role="assistant", state="complete",
                         body="final beta answer")
    with pytest.raises(WebHistoryConflict):
        history.record_frame(*scope, conversation_id=chat, message_id=msg,
                             revision=3, role="assistant", state="partial",
                             body="cannot reopen")
    with pytest.raises(PermissionError):
        history.search(*scope, "beta")
    with pytest.raises(PermissionError):
        history.set_index(*scope, enabled=True)
    history.set_index(*scope, enabled=True, operator_approved=True)
    restarted = WebHistoryStore(tmp_path)
    matches = restarted.search(*scope, "beta answer")
    assert len(matches) == 1 and matches[0]["message_id"] == msg
    assert restarted.search(*scope, "provisional") == []
    with pytest.raises(PermissionError):
        restarted.search("other-owner", scope[1], "beta")
    assert restarted.messages(*scope, chat)[0]["body"] == "final beta answer"
    text = restarted.export_markdown(*scope, chat)
    assert "final beta answer" in text and "message-12345" in text
    assert "final beta answer" not in restarted.export_markdown(
        *scope, chat, redact_body=True)
    with sqlite3.connect(str(restarted.store.path_for("provider_content"))) as db:
        blob = db.execute("SELECT protected_body FROM web_history_messages").fetchone()[0]
        assert blob.startswith(("dpapi:", "keyring:"))
        assert "final beta answer" not in blob
        assert db.execute("SELECT count(*) FROM web_history_messages").fetchone()[0] == 1
    restarted.set_index(*scope, enabled=False, operator_approved=True)
    with pytest.raises(PermissionError):
        restarted.search(*scope, "beta")
    with pytest.raises(PermissionError):
        restarted.purge(*scope, chat)
    assert restarted.purge(*scope, chat, operator_approved=True) == 1
    assert restarted.messages(*scope, chat) == []
    with sqlite3.connect(str(restarted.store.path_for("provider_content"))) as db:
        assert db.execute("SELECT count(*) FROM web_history_terms").fetchone()[0] == 0


def test_history_workspace_acl_byte_quota_and_fail_closed(tmp_path):
    history = WebHistoryStore(tmp_path)
    hist = dict(conversation_id="chat-abc123", message_id="msg-abc123",
                revision=0, role="user", state="complete")
    with pytest.raises(ValueError):
        history.record_frame("owner", "ws", **hist, body="x" * 800001)
    with pytest.raises(ValueError):
        history.record_frame("owner", "ws", **{**hist, "revision": -1}, body="x")
    history.record_frame("owner", "ws", **hist, body="private content")
    assert history.messages("owner", "other-workspace", hist["conversation_id"]) == []
    assert history.messages("foreign-owner", "ws", hist["conversation_id"]) == []
    with pytest.raises(WebHistoryConflict):
        history.record_frame("owner", "ws", **{**hist, "role": "assistant",
                                               "revision": 1}, body="changed role")
    with pytest.raises(ValueError):
        history.search("owner", "ws", "b" * 201)
    with pytest.raises(ValueError):
        history.messages("owner", "ws", hist["conversation_id"], limit=600)


def test_index_incremental_revision_updates_without_plaintext_and_opt_out(tmp_path):
    h = WebHistoryStore(tmp_path)
    h.set_index("owner", "ws", enabled=True, operator_approved=True)
    msg = dict(conversation_id="conv-abcdefgh", message_id="message-abcdefgh",
               role="assistant")
    h.record_frame("owner", "ws", **msg, revision=1, state="partial",
                   body="temporary expression")
    assert len(h.search("owner", "ws", "temporary")) == 1
    h.record_frame("owner", "ws", **msg, revision=2, state="complete",
                   body="durable expression")
    assert not h.search("owner", "ws", "temporary")
    assert len(h.search("owner", "ws", "durable")) == 1
    h.set_index("owner", "ws", enabled=False, operator_approved=True)
    with sqlite3.connect(str(h.store.path_for("provider_content"))) as db:
        assert db.execute("SELECT count(*) FROM web_history_terms").fetchone()[0] == 0
        row = db.execute("SELECT index_key FROM web_history_prefs").fetchone()
        assert row[0] is None
    h.set_index("owner", "ws", enabled=True, operator_approved=True)
    assert len(h.search("owner", "ws", "durable")) == 1
