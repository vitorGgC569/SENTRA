import base64
import json
import sqlite3
import zlib

import pytest
from sentra_canvas.pty_history import PtyHistory

def protect(value):return 'dpapi:'+base64.b64encode(value.encode()).decode()
def unprotect(value):return base64.b64decode(value[6:]).decode()
def open_history(path,**kwargs):return PtyHistory(path,protect=protect,unprotect=unprotect,**kwargs)
def decode(value):return json.loads(zlib.decompress(base64.b64decode(value['checkpoint']['data'])))

def test_live_checkpoint_retains_alternate_screen_geometry_unicode_and_parser_tail(tmp_path):
    host=open_history(tmp_path)
    try:
        assert host.snapshots.available
        host.register('w','t','runtime');host.bind('t',123);host.append('t',0,'normal 🐋\r\n')
        host.resize('t',70,12)
        text='\x1b[?1049h\x1b[2J\x1b[3;4HTUI\x1b[?2004h\x1b[31'
        host.append('t',len('normal 🐋\r\n'),text);assert host.flush()
        value=host.checkpoint('w','t');assert value['available']
        frame=decode(value)
        assert frame['cols']==70 and frame['rows']==12
        assert frame['modes']['alternateScreen'] and frame['modes']['bracketedPaste']
        assert frame['pendingEscapeTailAnsi']=='\x1b[31'
        assert 'TUI' in frame['snapshotAnsi'] and 'normal 🐋' in frame['scrollbackAnsi']
        assert frame['cursor']==len('normal 🐋\r\n')+len(text)
        with pytest.raises(PermissionError):host.checkpoint('other','t')
    finally:host.close()
    host=open_history(tmp_path)
    try:
        value=host.checkpoint('w','t')
        assert value['available'] and value['restoration_creates_process'] is False
        assert decode(value)['snapshotAnsi']==frame['snapshotAnsi']
        assert host.inventory()[0]['state']=='history_restored'
    finally:host.close()

def test_empty_terminal_has_a_restorable_initial_frame(tmp_path):
    host=open_history(tmp_path)
    try:
        host.register('w','t','runtime');assert host.flush()
        value=host.checkpoint('w','t')
        assert value['available'] and decode(value)['cursor']==0
    finally:host.close()


def test_drained_terminal_releases_its_mirror_after_an_already_saved_frame(tmp_path):
    host=open_history(tmp_path)
    try:
        host.register('w','t','runtime');host.append('t',0,'done');assert host.flush()
        assert 't' in host.mirrors
        host.ended('t',0,drained=True);assert host.flush()
        assert 't' not in host.mirrors and 't' in host.retired_mirrors
        assert host.checkpoint('w','t')['available']
    finally:host.close()

@pytest.mark.parametrize('lose_geometry',[False,True])
def test_archived_checkpoint_rebuilds_committed_tail_or_refuses_a_gap(tmp_path,lose_geometry):
    host=open_history(tmp_path)
    try:
        host.register('w','t','runtime');host.append('t',0,'before');assert host.flush()
        assert host.checkpoint('w','t')['available']
    finally:host.close()
    # Commit events as if the daemon stopped between the durable log and its next snapshot.
    with sqlite3.connect(tmp_path/'pty-history.sqlite3') as db:
        if not lose_geometry:db.execute('INSERT INTO geometry VALUES(?,?,?,?,?)',('t',2,6,50,8))
        protected=protect(' after')
        db.execute('INSERT INTO chunks(terminal_id,start,end,protected,bytes,created,sequence) VALUES(?,?,?,?,?,?,?)',
            ('t',6,12,protected,len(protected),2,3))
        db.execute('UPDATE sessions SET head=12,sequence=3,geometry_sequence=2,cols=50,rows=8')
    host=open_history(tmp_path)
    try:
        value=host.checkpoint('w','t')
        if lose_geometry:assert value['available'] is False
        else:
            frame=decode(value);assert frame['cols']==50 and frame['rows']==8 and frame['cursor']==12
            assert 'before after' in frame['snapshotAnsi']
    finally:host.close()

def test_oversized_checkpoint_keeps_the_transcript_instead_of_erasing_it(tmp_path):
    host=open_history(tmp_path,disk_limit=1024)
    try:
        host.register('w','t','runtime');host.append('t',0,'x'*400);assert host.flush()
        assert host.read('w','t')['text']=='x'*400
        with host.db_lock:
            used=host.db.execute('SELECT (SELECT COALESCE(SUM(bytes),0) FROM chunks)+(SELECT COALESCE(SUM(bytes),0) FROM checkpoints)').fetchone()[0]
        assert used<=1024 and not host.checkpoint('w','t')['available']
    finally:host.close()

def test_schema_one_transcript_is_preserved_without_claiming_unknown_geometry(tmp_path):
    host=open_history(tmp_path,snapshots_enabled=False)
    try:
        host.register('w','t','old');host.append('t',0,'legacy');assert host.flush()
    finally:host.close()
    with sqlite3.connect(tmp_path/'pty-history.sqlite3') as db:
        db.execute('UPDATE sessions SET snapshot_supported=0')
        db.execute('PRAGMA user_version=1')
    host=open_history(tmp_path)
    try:
        assert host.read('w','t')['text']=='legacy'
        assert host.checkpoint('w','t')['reason']=='legacy_history_without_ordered_geometry'
        assert host.db.execute('PRAGMA user_version').fetchone()[0]==2
    finally:host.close()
