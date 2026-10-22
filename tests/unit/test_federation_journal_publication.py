"""Only local snapshot publication may retry; peer effects never do."""
import json
from pathlib import Path

import pytest

from sentra_federation.journal import Journal


def fixture_journal(tmp_path):
    return Journal(tmp_path / 'journal', owner='test-owner', node_id='test-node')


def test_transient_windows_share_denial_publishes_the_same_protected_snapshot(tmp_path, monkeypatch):
    journal = fixture_journal(tmp_path)
    original = journal._path.read_bytes()
    replace = Path.replace
    attempts = []

    def sharing_once(source, destination):
        if destination == journal._path:
            attempts.append((source, source.read_bytes()))
            if len(attempts) == 1:
                assert destination.read_bytes() == original
                error = PermissionError('temporary Windows sharing denial')
                error.winerror = 32
                raise error
        return replace(source, destination)

    monkeypatch.setattr(Path, 'replace', sharing_once)
    journal.save_peer({'node_id': 'peer-a', 'state': 'paired'})
    assert journal.peers()['peer-a']['state'] == 'paired'
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert json.loads(attempts[0][1])['schema'] == 2
    assert b'peer-a' not in attempts[0][1]
    assert not list(journal._path.parent.glob('.journal-*.tmp'))


@pytest.mark.parametrize('windows_code', [None, 5, 32, 33])
def test_permanent_denial_preserves_last_journal_and_cleans_only_own_staging(tmp_path, monkeypatch, windows_code):
    import sentra_federation.journal as module
    journal = fixture_journal(tmp_path)
    original = journal._path.read_bytes()
    unrelated = journal._path.parent / '.journal-other.tmp'
    unrelated.write_bytes(b'other writer')
    clock = [0.0]
    attempts = []

    def deny(source, destination):
        attempts.append(source)
        error = PermissionError('permanent denial')
        if windows_code is not None:
            error.winerror = windows_code
        raise error

    monkeypatch.setattr(Path, 'replace', deny)
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(module.time, 'sleep', lambda duration: clock.__setitem__(0, clock[0] + duration))
    with pytest.raises(PermissionError, match='permanent denial'):
        journal.save_peer({'node_id': 'uncommitted'})
    assert journal._path.read_bytes() == original
    assert journal.peers() == {}
    assert unrelated.read_bytes() == b'other writer'
    assert list(journal._path.parent.glob('.journal-*.tmp')) == [unrelated]
    assert len(attempts) == 1 if windows_code is None else 1 < len(attempts) <= 32
