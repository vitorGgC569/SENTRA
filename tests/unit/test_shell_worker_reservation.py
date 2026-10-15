"""Duplicate durable discovery must not exhaust workers or repeat an effect."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing,contextmanager
import threading
import uuid

import pytest

from test_sentra_runtime_canvas_center_http import running_canvas


@contextmanager
def staged(tmp_path,monkeypatch,*,count=10,same_conversation=False):
    with running_canvas(tmp_path) as (app,_server):
        app.model_catalog=lambda:{'models':['sentra/test-one']}
        project=app.create_workspace('worker_reservation')['id']
        def call(action,**fields):
            return app.shell_bridge({'action':action,'project_id':project,
                'request_key':'reserve-'+uuid.uuid4().hex,**fields})['value']
        space=call('home')['space']['space_id']
        runtime=app._shell_runtime
        execute=runtime._execute
        monkeypatch.setattr(runtime,'_execute',lambda _oid:None)
        dot=call('dot_create',space_id=space,name='Reservation QA',role='specialist',model='sentra/test-one')
        ids=[];conversation=None
        for _ in range(count):
            if conversation is None or not same_conversation:
                conversation=call('conversation_create',space_id=space,dot_id=dot['dot_id'])['conversation_id']
            sent=call('message_send',space_id=space,conversation_id=conversation,content='Synthetic reservation regression')
            ids.append(sent['operation_id'])
        runtime._stop.set()
        for thread in runtime._threads:thread.join(timeout=3)
        runtime._stream_thread.join(timeout=3)
        assert all(not thread.is_alive() for thread in runtime._threads)
        yield runtime,execute,ids


def test_duplicate_discovery_does_not_starve_ten_distinct_conversations(tmp_path,monkeypatch):
    with staged(tmp_path,monkeypatch) as (runtime,execute,ids):
        entered=[];guard=threading.Lock();first=threading.Event();all_started=threading.Event();release=threading.Event()
        def slow_admission(oid,_message,_dot):
            with guard:
                entered.append(oid)
                if oid==ids[0]:first.set()
                if len(set(entered))==10:all_started.set()
            assert release.wait(8)
            with closing(runtime.control.store.connect('shell')) as db,db:
                assert db.execute("UPDATE canvas_shell_queue SET state='running' WHERE operation_id=? AND state='queued'",(oid,)).rowcount==1
        monkeypatch.setattr(runtime,'_execute_locked',slow_admission)
        with ThreadPoolExecutor(max_workers=10) as pool:
            original=pool.submit(execute,ids[0]);assert first.wait(3)
            duplicates=[pool.submit(execute,ids[0]) for _ in range(9)]
            others=[pool.submit(execute,oid) for oid in ids[1:]]
            try:
                assert all_started.wait(3),'Duplicate work occupied slots needed by other conversations'
                assert len(entered)==10 and len(set(entered))==10
                assert runtime._executing_operations==set(ids)
            finally:release.set()
            for future in [original,*duplicates,*others]:future.result(timeout=5)
        assert not runtime._executing_operations
        assert all(not lock.locked() for lock in runtime._conversation_locks.values())


def test_next_turn_in_same_conversation_stays_queued_without_waiting_for_worker_slot(tmp_path,monkeypatch):
    with staged(tmp_path,monkeypatch,count=2,same_conversation=True) as (runtime,execute,ids):
        first=threading.Event();release=threading.Event();entered=[]
        def hold_first(oid,_message,_dot):
            entered.append(oid)
            if oid==ids[0]:first.set();assert release.wait(8)
            with closing(runtime.control.store.connect('shell')) as db,db:
                db.execute("UPDATE canvas_shell_queue SET state='running' WHERE operation_id=?",(oid,))
        monkeypatch.setattr(runtime,'_execute_locked',hold_first)
        with ThreadPoolExecutor(max_workers=2) as pool:
            original=pool.submit(execute,ids[0]);assert first.wait(3)
            later=pool.submit(execute,ids[1])
            try:
                later.result(timeout=2)
                assert entered==[ids[0]]
                with closing(runtime.control.store.connect('shell')) as db:
                    assert db.execute('SELECT state FROM canvas_shell_queue WHERE operation_id=?',(ids[1],)).fetchone()['state']=='queued'
                assert runtime._executing_operations=={ids[0]}
            finally:release.set()
            original.result(timeout=5)
        # Represents the existing durable idle discovery, not prompt replay.
        execute(ids[1]);assert entered==ids
        assert not runtime._executing_operations


def test_reservation_and_conversation_lock_released_after_failure_and_missing_row(tmp_path,monkeypatch):
    with staged(tmp_path,monkeypatch,count=1) as (runtime,execute,ids):
        def broken(*_):raise RuntimeError('synthetic admission failure')
        monkeypatch.setattr(runtime,'_execute_locked',broken)
        with pytest.raises(RuntimeError,match='synthetic admission'):execute(ids[0])
        assert not runtime._executing_operations
        assert all(not lock.locked() for lock in runtime._conversation_locks.values())
        entered=[];monkeypatch.setattr(runtime,'_execute_locked',lambda oid,*_:entered.append(oid))
        execute(ids[0]);execute('missing-owned-operation')
        assert entered==ids and not runtime._executing_operations
