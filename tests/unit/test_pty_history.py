import base64
import json
import os
import sqlite3
import threading

import pytest
from sentra_canvas.pty_history import PtyHistory,OUTPUT_CHARS
from sentra_canvas.pty_daemon import OutputCache


def protected(value):return 'dpapi:'+base64.b64encode(value.encode()).decode()
def unprotected(value):return base64.b64decode(value[6:]).decode()
def history(path,**kwargs):return PtyHistory(path,protect=protected,unprotect=unprotected,snapshots_enabled=False,**kwargs)


def test_protected_ansi_history_reopens_read_only_with_exact_cursor_and_scope(tmp_path):
    text='\x1b[31mOlá 🐋\x1b[0m\r\n'
    host=history(tmp_path)
    try:
        host.register('workspace','terminal','old-runtime');host.bind('terminal',123)
        host.append('terminal',0,text);assert host.flush()
        assert host.status('terminal',0,len(text))['persisted']
    finally:assert host.close()
    host=history(tmp_path)
    try:
        row=host.inventory()[0];assert row['state']=='history_restored'
        value=host.read('workspace','terminal')
        assert value['text']==text and value['cursor']==len(text)
        assert not value['process_live'] and not value['restoration_creates_process']
        assert value['origin_runtime_id']=='old-runtime' and value['tail_uncertain']
        with pytest.raises(PermissionError):host.read('other-workspace','terminal')
        assert host.read('workspace','terminal',len(text))['text']==''
    finally:host.close()


def test_slow_crypto_is_bounded_fair_and_pending_output_is_not_skipped(tmp_path):
    entered=threading.Event();release=threading.Event()
    def slow(value):entered.set();assert release.wait(5);return protected(value)
    host=PtyHistory(tmp_path,protect=slow,unprotect=unprotected,snapshots_enabled=False,
        queue_limit=2048,session_queue_limit=1024)
    try:
        host.register('w','flood','r');host.register('w','quiet','r')
        host.append('flood',0,'x'*650);assert entered.wait(2)
        host.append('quiet',0,'quiet')
        for i in range(50):host.append('flood',650*(i+1),'x'*650)
        state=host.status('flood')
        assert state['buffered_bytes']<=2048 and state['dropped_chars']>0
        with host.condition:
            assert host.sizes.get('flood',0)+host.inflight_bytes<=1024
        assert host.read('w','flood')['cursor']==0
        release.set();assert host.flush()
        assert host.read('w','quiet')['text']=='quiet'
        assert host.read('w','flood')['truncated']
    finally:release.set();host.close()


def test_disk_quota_prunes_old_records_and_reports_gap(tmp_path):
    host=history(tmp_path,disk_limit=1024)
    try:
        host.register('w','t','r')
        for i in range(4):host.append('t',i*400,str(i)*400);assert host.flush()
        with host.db_lock:
            assert host.db.execute('SELECT SUM(bytes) FROM chunks').fetchone()[0]<=1024
        value=host.read('w','t')
        assert value['truncated'] and value['base']>0 and value['gaps']
        assert value['text']=='3'*400
    finally:host.close()


def test_tiny_frames_account_for_rows_and_budget_updates_roll_back(tmp_path):
    host=history(tmp_path,disk_limit=16*1024)
    try:
        host.register('w','t','r')
        for i in range(600):
            host.append('t',i,'x')
            if i%40==39:assert host.flush()
        assert host.flush()
        with host.db_lock:
            actual=host.db.execute('SELECT COALESCE(SUM(bytes+256),0) FROM chunks').fetchone()[0]
            assert actual==host.db.execute('SELECT used FROM history_budget').fetchone()[0]
            assert actual<=host.disk_limit
            try:
                with host.db:
                    host.db.execute('DELETE FROM chunks')
                    raise RuntimeError('rollback')
            except RuntimeError:pass
            assert host.db.execute('SELECT used FROM history_budget').fetchone()[0]==actual
        assert host.read('w','t')['truncated']
        assert host.error is None
    finally:host.close()
    host=history(tmp_path,disk_limit=16*1024)
    try:
        assert host.db.execute('SELECT used FROM history_budget').fetchone()[0]<=host.disk_limit
    finally:host.close()


def test_resize_flood_respects_per_session_budget_including_inflight_output(tmp_path):
    entered=threading.Event();release=threading.Event()
    def slow(value):entered.set();assert release.wait(5);return protected(value)
    host=PtyHistory(tmp_path,protect=slow,unprotect=unprotected,snapshots_enabled=False,
        queue_limit=4096,session_queue_limit=1024)
    try:
        host.register('w','t','r');host.append('t',0,'x'*650);assert entered.wait(2)
        for _ in range(200):host.resize('t',100,28)
        with host.condition:
            assert host.sizes.get('t',0)+host.inflight_bytes<=1024
            assert 't' in host.snapshot_invalid
        release.set();assert host.flush()
    finally:release.set();host.close()


def test_plaintext_protection_failure_cannot_claim_saved_output(tmp_path):
    host=PtyHistory(tmp_path,protect=lambda value:value,unprotect=lambda value:value)
    try:
        host.register('w','t','r');host.append('t',0,'not safely stored')
        assert not host.flush()
        state=host.status('t',0,17)
        assert not state['persisted'] and state['persistence_error']=='RuntimeError'
        assert host.db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]==0
    finally:host.close()


@pytest.mark.skipif(os.name!='nt',reason='real OS secret protection')
def test_real_dpapi_history_does_not_store_plaintext(tmp_path):
    host=PtyHistory(tmp_path)
    try:
        host.register('w','t','r');host.append('t',0,'PRIVATE_TRANSCRIPT_95872')
        assert host.flush()
        assert 'PRIVATE_TRANSCRIPT_95872'==host.read('w','t')['text']
        assert b'PRIVATE_TRANSCRIPT_95872' not in host.path.read_bytes()
    finally:host.close()


def test_future_history_schema_refuses_downgrade(tmp_path):
    with sqlite3.connect(tmp_path/'pty-history.sqlite3') as db:db.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError,match='newer'):history(tmp_path)


def test_live_checkpoint_does_not_skip_an_inflight_chunk(tmp_path):
    entered=threading.Event();release=threading.Event();calls=0
    def protect(value):
        nonlocal calls
        calls+=1
        if calls==2:entered.set();assert release.wait(5)
        return protected(value)
    host=PtyHistory(tmp_path,protect=protect,unprotect=unprotected,snapshots_enabled=False)
    try:
        host.register('w','t','r');host.append('t',0,'first');assert host.flush()
        host.append('t',5,'second');assert entered.wait(2)
        # The observed head may have been persisted by a different queue turn.
        with host.db_lock,host.db:host.db.execute('UPDATE sessions SET head=11')
        assert host.read('w','t')['cursor']==5
        release.set();assert host.flush()
        assert host.read('w','t',5)['text']=='second'
    finally:release.set();host.close()


def test_unicode_http_frame_limit_and_future_cursor_gap():
    cache=OutputCache();cache.append('t','🐋'*(OUTPUT_CHARS+1))
    value=cache.read('t')
    assert len(value['text'])==OUTPUT_CHARS
    assert len(json.dumps({'ok':True,'value':value}).encode())<256*1024
    assert cache.read('t',OUTPUT_CHARS+2)['truncated']


def test_daemon_refuses_safe_stop_while_the_output_reader_is_not_drained(tmp_path):
    from sentra_canvas.pty_daemon import PtyHost
    class EndingPTY:
        def __init__(self,*args,**kwargs):self.pid=125;self.ended=False;self.drained=False
        def poll(self):return 0 if self.ended else None
        def close(self,**kwargs):self.ended=True
        def wait_output(self,timeout):return self.drained
    host=PtyHost(tmp_path,EndingPTY)
    try:
        host.dispatch('create',{'workspace_id':'w','terminal_id':'t','argv':['x'],'cwd':str(tmp_path)},'create:drain-reader')
        host.sessions['t']['pty'].ended=True
        host.dispatch('drain',{})
        with pytest.raises(RuntimeError,match='reader'):host.dispatch('stop_when_idle',{})
        host.sessions['t']['pty'].drained=True
        assert host.dispatch('stop_when_idle',{})['safe_to_stop']
    finally:host.close()


def test_failed_observation_cannot_start_a_replacement_for_an_owned_daemon(tmp_path,monkeypatch):
    from sentra_canvas.instance_lock import InstanceLock
    from sentra_canvas.pty_client import PtyDaemonClient
    from sentra_canvas.terminal import TerminalError
    lease=InstanceLock(tmp_path/'pty-owner.lock')
    def unavailable(self,state):raise OSError('observation temporarily unavailable')
    def forbidden_spawn(*args,**kwargs):pytest.fail('observation failure spawned a replacement')
    monkeypatch.setattr(PtyDaemonClient,'__init__',unavailable)
    monkeypatch.setattr('sentra_canvas.pty_client.subprocess.Popen',forbidden_spawn)
    try:
        with pytest.raises(TerminalError,match='no replacement'):PtyDaemonClient.connect_or_start(tmp_path)
    finally:lease.close()
