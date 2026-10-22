"""A slow protected transcript must not block live producer/geometry reads."""
import threading

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
