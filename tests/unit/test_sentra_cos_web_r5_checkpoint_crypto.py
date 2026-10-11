"""R5: actual central SQLite checkpoint/cursor encryption, migration and rollback."""
import json
import sqlite3

import pytest

from sentra_mcp.services.session_checkpoint import SessionCheckpointService
from test_governance_coordination import _services
from test_sentra_cos_web_continuation_receipts import setup


def _rows(control):
    with control.store.connect("session_checkpoint") as db:
        return [dict(r) for r in db.execute(
            "SELECT checkpoint_id,owner,run_id,cursor_json,checkpoint_json,payload_sha256 "
            "FROM session_checkpoints ORDER BY source_seq").fetchall()]


def test_r5_existing_run_checkpoint_summary_ciphertext_persists_restart(tmp_path):
    d,c,control,relay,adapter,p=setup(tmp_path)
    try:
        original=control.latest_session_checkpoint(
            p["owner"],run_id=p["run_id"],chat_id=p["chat_id"])
        assert original["checkpoint"]["summary"]==p["summary"]
        rows=_rows(control)
        assert len(rows)==1
        assert rows[0]["checkpoint_json"].startswith(("dpapi:","keyring:"))
        assert rows[0]["cursor_json"].startswith(("dpapi:","keyring:"))
        assert p["summary"] not in rows[0]["checkpoint_json"]
        path=control.store.path_for("session_checkpoint")
        assert p["summary"].encode() not in path.read_bytes()
        digest=rows[0]["payload_sha256"]
    finally:
        relay.close();c.close();d.close()

    d2,c2,control2=_services(tmp_path)
    try:
        reopened=control2.latest_session_checkpoint(
            p["owner"],run_id=p["run_id"],chat_id=p["chat_id"])
        assert reopened["checkpoint"]["summary"]==p["summary"]
        assert reopened["cursor"]["last_message_id"]=="msg-old-123"
        assert _rows(control2)[0]["payload_sha256"]==digest
    finally:
        c2.close();d2.close()


def test_r5_legacy_checkpoint_migrates_atomically_without_losing_cas(tmp_path):
    d,c,control,relay,adapter,p=setup(tmp_path)
    try:
        source=control.latest_session_checkpoint(p["owner"],run_id=p["run_id"],
                                                 chat_id=p["chat_id"])
        original_sha=source["payload_sha256"]
        # Controlled legacy SQLite fixture only. No production database touched.
        with control.store.connect("session_checkpoint") as db:
            db.execute("UPDATE session_checkpoints SET cursor_json=?,checkpoint_json=? "
                       "WHERE checkpoint_id=?",(
                           json.dumps(source["cursor"]),json.dumps(source["checkpoint"]),
                           source["checkpoint_id"]))
        row=_rows(control)[0]
        assert row["checkpoint_json"].startswith("{")
        migrated=SessionCheckpointService(tmp_path/".sentra",store=control.store)
        latest=migrated.latest(p["owner"],chat_id=p["chat_id"])
        assert latest["checkpoint"]==source["checkpoint"]
        assert latest["cursor"]==source["cursor"]
        assert latest["payload_sha256"]==original_sha
        assert _rows(control)[0]["checkpoint_json"].startswith(("dpapi:","keyring:"))
        with control.store.connect("session_checkpoint") as db:
            assert db.execute("SELECT cleanup_pending FROM session_checkpoint_storage_security "
                              "WHERE key='os_crypto'").fetchone()[0]==0
    finally:
        relay.close();c.close();d.close()


def test_r5_migration_vault_error_rolls_back_all_legacy_rows(tmp_path,monkeypatch):
    import sentra_mcp.services.session_checkpoint as mod
    d,c,control,relay,adapter,p=setup(tmp_path)
    try:
        old=control.latest_session_checkpoint(p["owner"],run_id=p["run_id"],
                                              chat_id=p["chat_id"])
        with control.store.connect("session_checkpoint") as db:
            db.execute("UPDATE session_checkpoints SET cursor_json=?,checkpoint_json=? "
                       "WHERE checkpoint_id=?",(
                           json.dumps(old["cursor"]),json.dumps(old["checkpoint"]),
                           old["checkpoint_id"]))
        with monkeypatch.context() as patch:
            def broken(_):
                raise RuntimeError("simulated OS secret broker unavailable")
            patch.setattr(mod,"protect_secret",broken)
            with pytest.raises(RuntimeError,match="unavailable"):
                mod.SessionCheckpointService(tmp_path/".sentra",store=control.store)
        raw=_rows(control)[0]
        assert raw["cursor_json"].startswith("{")
        assert raw["checkpoint_json"].startswith("{")
        recovered=SessionCheckpointService(tmp_path/".sentra",store=control.store)
        assert recovered.latest(p["owner"],chat_id=p["chat_id"])["checkpoint"]==old["checkpoint"]
        assert _rows(control)[0]["checkpoint_json"].startswith(("dpapi:","keyring:"))
    finally:
        relay.close();c.close();d.close()


def test_r5_ciphertext_row_swap_is_denied_not_silently_defaulted(tmp_path):
    d,c,control,relay,adapter,p=setup(tmp_path)
    try:
        control.write_session_checkpoint(
            p["owner"],run_id=p["run_id"],chat_id=p["chat_id"],
            source_instance_id="web-observer",source_epoch="epoch-1",source_seq=2,
            checkpoint={"summary":"Different source state"},cursor={})
        rows=_rows(control)
        assert len(rows)==2
        with control.store.connect("session_checkpoint") as db:
            db.execute("UPDATE session_checkpoints SET checkpoint_json=? WHERE checkpoint_id=?",
                       (rows[0]["checkpoint_json"],rows[1]["checkpoint_id"]))
        with pytest.raises(RuntimeError,match="binding mismatch"):
            control.latest_session_checkpoint(
                p["owner"],run_id=p["run_id"],chat_id=p["chat_id"])
        with pytest.raises(RuntimeError,match="binding mismatch"):
            SessionCheckpointService(tmp_path/".sentra",store=control.store)
    finally:
        relay.close();c.close();d.close()
