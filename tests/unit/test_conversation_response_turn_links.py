"""Response-to-turn associations are additive journal metadata, not receipts."""
import os
import sqlite3
import sys

import pytest

from sentra_core.conversations import ConversationStore


@pytest.fixture(autouse=True)
def local_keyring(monkeypatch):
    if os.name != 'nt':
        from types import SimpleNamespace
        values = {}
        monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(
            set_password=lambda service, key, value: values.__setitem__((service, key), value),
            get_password=lambda service, key: values.get((service, key))))


def test_multiple_provider_rounds_and_turns_survive_reopen(tmp_path):
    store = ConversationStore(tmp_path / 'state', principal='alice')
    ident = store.open(tmp_path)
    first, _ = store.begin_turn(ident, 'first')
    a = store.finish_response(ident, first, 'calling a tool')
    b = store.finish_response(ident, first, 'final response')
    store.end_turn(ident, first)
    second, _ = store.begin_turn(ident, 'second')
    c = store.finish_response(ident, second, 'second response')
    reopened = ConversationStore(tmp_path / 'state', principal='alice')
    assert reopened.response_messages_for_turn(ident, first) == [a, b]
    assert reopened.response_messages_for_turn(ident, second) == [c]
    assert reopened.messages(ident)[1:3] == [a, b]
    with pytest.raises(PermissionError):
        ConversationStore(tmp_path / 'state', principal='bob').response_messages_for_turn(ident, first)
    other = store.open(tmp_path)
    with pytest.raises(PermissionError):
        store.finish_response(other, first, 'wrong conversation')
    assert store.messages(other) == []


def test_legacy_messages_are_not_guessed_into_a_turn(tmp_path):
    store = ConversationStore(tmp_path / 'state')
    ident = store.open(tmp_path)
    turn, _ = store.begin_turn(ident, 'old prompt')
    legacy = store.append(ident, 'assistant', 'legacy', kind='assistant_response')
    with store._tx() as db:
        db.execute('DROP TABLE response_message_turns')
    reopened = ConversationStore(tmp_path / 'state')
    assert reopened.response_messages_for_turn(ident, turn) == []
    assert reopened.messages(ident)[-1] == legacy
    fresh = reopened.finish_response(ident, turn, 'new linked response')
    assert reopened.response_messages_for_turn(ident, turn) == [fresh]
    with reopened._connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2


def test_failed_link_rolls_back_response_and_draft(tmp_path):
    store = ConversationStore(tmp_path / 'state')
    ident = store.open(tmp_path)
    turn, _ = store.begin_turn(ident, 'prompt')
    store.checkpoint_response(ident, turn, 'draft')
    with store._tx() as db:
        db.execute("CREATE TRIGGER reject_response_link BEFORE INSERT ON response_message_turns "
                   "BEGIN SELECT RAISE(ABORT,'test link failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='test link failure'):
        store.finish_response(ident, turn, 'not committed')
    assert store.response_draft(ident)['content'] == 'draft'
    assert [m['content'] for m in store.messages(ident)] == ['prompt']
    assert store.response_messages_for_turn(ident, turn) == []


@pytest.mark.parametrize('state', ['completed', 'interrupted', 'provider_error', 'uncertain', 'limit_reached'])
def test_late_response_cannot_change_closed_turn_or_discard_draft(tmp_path, state):
    store = ConversationStore(tmp_path / 'state')
    ident = store.open(tmp_path)
    turn, _ = store.begin_turn(ident, 'prompt')
    store.checkpoint_response(ident, turn, 'partial draft')
    store.end_turn(ident, turn, state)
    with pytest.raises(PermissionError, match='active owned turn'):
        store.finish_response(ident, turn, 'late response')
    assert [message['content'] for message in store.messages(ident)] == ['prompt']
    assert store.response_messages_for_turn(ident, turn) == []
    with store._connect() as db:
        assert db.execute('SELECT 1 FROM response_drafts WHERE turn_id=?', (turn,)).fetchone()
