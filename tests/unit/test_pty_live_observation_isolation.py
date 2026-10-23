"""A slow protected transcript must not block live producer/geometry reads."""
import threading
import json
import sqlite3

import pytest

from test_terminal_checkpoints import open_history


def test_committed_geometry_survives_reopen_and_never_waits_for_disk_writer(tmp_path):
    host = open_history(tmp_path, snapshots_enabled=False)
    try:
        host.register('w', 't', 'runtime')
        host.bind('t', 123)
        host.resize('t', 72, 18)
        assert host.flush()
        result = []
        done = threading.Event()
        def observe():
            result.append(host.geometry('t'))
            done.set()
        with host.db_lock:
            thread = threading.Thread(target=observe)
            thread.start()
            responsive = done.wait(2)
        thread.join(3)
        assert responsive, 'Live geometry waited on the transcript writer'
        assert result == [{'cols':72, 'rows':18, 'geometry_sequence':1}]
        assert host.geometry('unknown') == {}
    finally:
        assert host.close()
    restored = open_history(tmp_path, snapshots_enabled=False)
    try:
        assert restored.geometry('t') == result[0]
        assert restored.inventory()[0]['state'] == 'history_restored'
    finally:
        assert restored.close()


def test_archived_read_waiting_for_disk_never_holds_live_producer_condition(tmp_path):
    host = open_history(tmp_path, snapshots_enabled=False)
    waiting = threading.Event()
    appended = threading.Event()
    results = []
    lock = host.db_lock
    class TracedLock:
        def __enter__(self):
            if threading.current_thread().name == 'archived-reader':
                waiting.set()
            lock.acquire()
            return self
        def __exit__(self, *args):
            lock.release()
    try:
        host.register('w', 't', 'runtime')
        host.append('t', 0, 'first')
        assert host.flush()
        host.db_lock = TracedLock()
        with lock:
            reader = threading.Thread(name='archived-reader', target=lambda: results.append(host.read('w','t')))
            reader.start()
            assert waiting.wait(2)
            def produce():
                host.append('t', 5, 'second')
                appended.set()
            producer = threading.Thread(target=produce)
            producer.start()
            responsive = appended.wait(2)
        reader.join(3)
        producer.join(3)
        assert responsive, 'A disk reader blocked the live producer condition'
        assert host.flush()
        assert results and host.read('w','t')['text'] == 'firstsecond'
    finally:
        assert host.close()


def test_failed_geometry_transaction_never_publishes_uncommitted_projection(tmp_path):
    host = open_history(tmp_path, snapshots_enabled=False)
    try:
        host.register('w', 't', 'runtime')
        with host.db_lock, host.db:
            host.db.execute("""CREATE TRIGGER refuse_geometry BEFORE UPDATE OF geometry_sequence
                ON sessions BEGIN SELECT RAISE(ABORT, 'test disk failure'); END""")
        host.resize('t', 72, 18)
        assert host.flush() is False
        assert host.geometry('t') == {'cols':100, 'rows':28, 'geometry_sequence':0}
        assert host.status('t')['persistence_error'] is not None
    finally:
        assert host.close()


def test_live_checkpoint_does_not_wait_on_writer_or_archived_reconstruction(tmp_path):
    host = open_history(tmp_path)
    done = threading.Event()
    results = []
    try:
        host.register('w', 't', 'runtime')
        host.append('t', 0, 'committed 🦊')
        assert host.flush()
        expected = host.checkpoint('w', 't')
        assert expected['available']
        def observe():
            try:results.append(host.checkpoint('w', 't'))
            finally:done.set()
        with host.db_lock, host.restore_lock:
            reader = threading.Thread(target=observe)
            reader.start()
            responsive = done.wait(2)
        reader.join(3)
        assert responsive, 'Live checkpoint waited on persistence/reconstruction'
        assert results == [expected]
        with pytest.raises(PermissionError):host.checkpoint('another-workspace', 't')
    finally:
        assert host.close()


def test_failed_checkpoint_commit_keeps_only_previously_committed_frame(tmp_path):
    host = open_history(tmp_path)
    try:
        host.register('w', 't', 'runtime')
        host.append('t', 0, 'committed')
        assert host.flush()
        original = host.live_checkpoints['t']
        frame = json.loads(host.unprotect(original[1]))
        with host.db_lock, host.db:
            host.db.execute("""CREATE TRIGGER refuse_checkpoint BEFORE UPDATE ON checkpoints
                BEGIN SELECT RAISE(ABORT, 'test checkpoint commit failure'); END""")
        frame['sequence'] += 1
        frame['cursor'] += 1
        with pytest.raises(sqlite3.IntegrityError, match='test checkpoint commit failure'):
            host._save_checkpoint('t', frame)
        assert host.live_checkpoints['t'] == original
        assert host.checkpoint('w', 't')['checkpoint']['sequence'] == original[0]
    finally:
        assert host.close()


def test_live_checkpoint_ciphertext_cache_follows_committed_disk_pruning(tmp_path):
    host = open_history(tmp_path, disk_limit=4096)
    try:
        for terminal in ('one', 'two', 'three'):
            host.register('w', terminal, 'runtime')
            host.append(terminal, 0, terminal + ' 🦊' * 16)
            assert host.flush()
        with host.db_lock:
            retained = {row['terminal_id']: row['protected']
                for row in host.db.execute('SELECT terminal_id,protected FROM checkpoints')}
        assert retained and len(retained) < 3, 'The test must actually evict a frame'
        assert {key: value[1] for key, value in host.live_checkpoints.items()} == retained
        assert sum(len(value[1].encode('utf-8')) for value in host.live_checkpoints.values()) <= host.disk_limit
        assert host.checkpoint_known == set(retained)
        for terminal in {'one', 'two', 'three'} - set(retained):
            assert not host.checkpoint('w', terminal)['available']
    finally:
        assert host.close()
