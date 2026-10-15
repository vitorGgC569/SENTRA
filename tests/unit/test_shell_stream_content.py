"""Immutable, paginated protected previews; no model/provider or installed state."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import subprocess
import sys
import threading
from urllib.parse import urlencode
import urllib.error
import urllib.request

import pytest

import sentra_canvas.shell_stream as stream_module
from sentra_canvas.shell_stream import ShellStreamJournal, CONTENT_CHUNK_CHARS, CONTENT_PAGE_UTF8_BYTES
from sentra_core.conversations import _encode, _decode
from sentra_mcp.services.control_store import create_control_plane_store
from test_sentra_runtime_canvas_center_http import running_canvas, request
from test_shell_stream_journal import _scope, preview


def full_text():
    return 'A'*65536+'B'*65536+('Unicode 🪐 [[wiki]] repetido [[ação]]\n'*5000)


def read_all(journal, reference, *, project='p', space='s', conversation='c', limit=65536):
    parts=[];offset=0
    while offset is not None:
        page=journal.content(project,space,conversation,reference['reference_id'],offset=offset,limit=limit)
        assert page['offset']==offset and page['sha256']==reference['sha256']
        assert page['page_sha256']==hashlib.sha256(page['content'].encode()).hexdigest()
        assert len(page['content'].encode())<=CONTENT_PAGE_UTF8_BYTES
        assert page['persisted'] and not page['authoritative'] and not page['automatic_retry']
        parts.append(page['content']);offset=page['next_offset']
    text=''.join(parts)
    assert len(text)==reference['total_chars']
    assert hashlib.sha256(text.encode()).hexdigest()==reference['sha256']
    return text


def test_long_unicode_preview_reopens_and_recovers_every_character_by_immutable_reference(tmp_path):
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    text=full_text();sequence=journal.publish('p','s','c',preview(text))
    head=journal.head('p','c');reference=head['content_ref']
    assert head['sequence']==sequence and head['truncated']
    assert len(head['content'].encode('utf-16-le'))<=131072*2
    assert text[head['content_offset']:]==head['content']
    reopened=ShellStreamJournal(journal.store,'owner')
    assert read_all(reopened,reference,limit=65001)==text
    boundary=reopened.content('p','s','c',reference['reference_id'],offset=65530,limit=20)
    assert boundary['content']==text[65530:65550]
    with journal.store.connect('shell') as db:
        chunks=db.execute('SELECT protected_content FROM shell_stream_content_chunks').fetchall()
    assert chunks and all(row['protected_content'].startswith(('dpapi:','keyring:')) for row in chunks)
    wire=json.dumps(journal.read('p',0)['items'][0],ensure_ascii=False).encode()
    assert len(wire)<2_000_000 and b'content_ref' in wire


def test_growing_previews_reuse_immutable_chunks_instead_of_persisting_full_copies(tmp_path):
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    prefix='A'*65536+'B'*65536
    references=[]
    for revision in range(20):
        journal.publish('p','s','c',preview(prefix+'tail-'+str(revision)))
        references.append(journal.head('p','c')['content_ref'])
    with journal.store.connect('shell') as db:
        count=db.execute('SELECT COUNT(*) AS n FROM shell_stream_content_chunks').fetchone()['n']
        chunks=db.execute('SELECT protected_content FROM shell_stream_content_chunks').fetchall()
    assert count==22 # two stable prefix chunks and twenty short tails
    assert sum(len(stream_module._decode(row['protected_content'])) for row in chunks)<len(prefix)+200
    assert read_all(journal,references[0])==prefix+'tail-0'
    assert read_all(journal,references[-1])==prefix+'tail-19'
    assert references[0]['reference_id']!=references[-1]['reference_id']


def test_content_gc_retains_inactive_heads_and_replayable_revisions_without_crossing_owner(tmp_path,monkeypatch):
    monkeypatch.setattr(stream_module,'MAX_EVENTS',3)
    store=create_control_plane_store(tmp_path)
    journal=ShellStreamJournal(store,'owner')
    text=full_text()
    journal.publish('p','s','inactive',preview(text,operation_id='op-inactive'))
    inactive=journal.head('p','inactive')['content_ref']
    journal.publish('p','s','c',preview(text+'old'))
    old=journal.head('p','c')['content_ref']
    for index in range(5):journal.publish('p','s','c',preview(text+str(index)))
    latest=journal.head('p','c')['content_ref']
    with pytest.raises(FileNotFoundError):read_all(journal,old)
    assert read_all(journal,inactive,conversation='inactive')==text
    assert read_all(journal,latest)==text+'4'
    with pytest.raises(FileNotFoundError):read_all(ShellStreamJournal(store,'other-owner'),latest)
    for fields in [{'project':'other'},{'space':'other'},{'conversation':'other'}]:
        with pytest.raises(FileNotFoundError):read_all(journal,latest,**fields)
    assert journal.read('p',0)['reset']


def test_failed_long_publish_rolls_back_chunks_manifests_events_and_head_together(tmp_path,monkeypatch):
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    before=journal.publish('p','s','c',preview('before'))
    encode=stream_module._encode;calls=0
    def fail(value):
        nonlocal calls
        calls+=1
        if calls==3:raise OSError('induced overflow write failure')
        return encode(value)
    with monkeypatch.context() as patch:
        patch.setattr(stream_module,'_encode',fail)
        with pytest.raises(OSError,match='induced overflow'):journal.publish('p','s','c',preview(full_text()))
    assert journal.head('p','c')['content']=='before'
    assert journal.read('p',before)['items']==[]
    with journal.store.connect('shell') as db:
        for table in ('contents','content_chunks','content_pages','content_references'):
            assert db.execute('SELECT COUNT(*) AS n FROM shell_stream_'+table).fetchone()['n']==0


def test_long_reference_remains_consistent_during_concurrent_new_revision(tmp_path,monkeypatch):
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    text=full_text();journal.publish('p','s','c',preview(text))
    old=journal.head('p','c')['content_ref']
    entered=threading.Event();release=threading.Event();decode=stream_module._decode
    def pause(value):
        if threading.current_thread().name.startswith('slow-content'):
            entered.set();assert release.wait(5)
        return decode(value)
    monkeypatch.setattr(stream_module,'_decode',pause)
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='slow-content') as pool:
        future=pool.submit(journal.content,'p','s','c',old['reference_id'],offset=65530,limit=40)
        assert entered.wait(3)
        try:journal.publish('p','s','c',preview(text+'new revision'))
        finally:release.set()
        assert future.result(timeout=5)['content']==text[65530:65570]
    assert read_all(journal,old)==text


def test_content_pages_reject_bad_parameters_missing_chunks_and_corruption(tmp_path):
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    journal.publish('p','s','c',preview(full_text()));reference=journal.head('p','c')['content_ref']
    for fields in ({'offset':True},{'offset':-1},{'offset':reference['total_chars']+1},{'limit':True},{'limit':65537},{'limit':0}):
        with pytest.raises(ValueError):journal.content('p','s','c',reference['reference_id'],**fields)
    with journal.store.connect('shell') as db,db:
        db.execute('UPDATE shell_stream_content_chunks SET protected_content=?',(_encode('corrupted'),))
    with pytest.raises(RuntimeError,match='integrity'):journal.content('p','s','c',reference['reference_id'])
    with journal.store.connect('shell') as db,db:db.execute('DELETE FROM shell_stream_content_chunks')
    with pytest.raises(RuntimeError,match='incomplete'):journal.content('p','s','c',reference['reference_id'])


def test_budget_failure_is_visible_and_never_claims_recoverable_or_committed_content(tmp_path,monkeypatch):
    monkeypatch.setattr(stream_module,'MAX_FULL_CONTENT_BYTES',140000)
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    journal.publish('p','s','c',preview('A'*150000,status='committed'))
    head=journal.head('p','c')
    assert head['status']=='preview_unavailable' and head['truncated']
    assert head['content_error']['code']=='stream_content_budget_exceeded'
    assert head['content_error']['observed_utf8_bytes']==150000
    assert 'content_ref' not in head and not head['authoritative'] and not head['closes_trio']


def test_live_native_round_reaches_protected_reference_without_losing_prefix(tmp_path,monkeypatch):
    from sentra_canvas.shell_live import ShellLivePreviews
    from sentra_cli.shell_live_preview import LivePreviewWriter
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    live=ShellLivePreviews(tmp_path,on_change=lambda record,view:journal.publish('p','s','c',view))
    record=live.begin(project_id='p',space_id='s',conversation_id='c',operation_id='op-one')
    for key,value in live.environment(record).items():monkeypatch.setenv(key,value)
    text=full_text();LivePreviewWriter().send(text)
    while record['offset']<record['path'].stat().st_size:live.update(record)
    try:
        head=journal.head('p','c');assert read_all(journal,head['content_ref'])==text
        public=live.view('p','c');assert public['truncated'] and len(public['content'])<len(text)
    finally:live.close(record)
    assert read_all(journal,journal.head('p','c')['content_ref'])==text


def test_content_service_checks_current_space_conversation_and_owner_without_dispatch(tmp_path,monkeypatch):
    with running_canvas(tmp_path) as (app,server):
        project,space,conversation,operation=_scope(app,monkeypatch)
        runtime=app._shell_runtime
        # Stop this fixture's staged synthetic queue before asserting reads.
        # Its no-op executor deliberately leaves it queued; a worker polling
        # that row is independent of a content read and must not taint proof.
        with runtime.control.store.connect('shell') as db,db:
            db.execute("UPDATE canvas_shell_queue SET state='completed' WHERE operation_id=?",(operation,))
        runtime._stop.set()
        for thread in runtime._threads:thread.join(timeout=3)
        runtime.stream.publish(project,space,conversation,preview(full_text(),operation_id=operation))
        reference=runtime.stream.head(project,conversation)['content_ref']
        monkeypatch.setattr(runtime,'_execute',lambda *_:pytest.fail('content read must never execute'))
        page=app.shell_stream_content(project,space,conversation,reference['reference_id'],limit=31)
        assert page['content']==full_text()[:31]
        for fields in [('missing',space,conversation),(project,'missing',conversation),(project,space,'missing')]:
            with pytest.raises((ValueError,FileNotFoundError,PermissionError)):
                app.shell_stream_content(*fields,reference['reference_id'])
        with runtime.control.store.connect('shell') as db,db:
            db.execute("DELETE FROM shell_entities WHERE kind='space' AND entity_id=?",(space,))
        with pytest.raises(FileNotFoundError):app.shell_stream_content(project,space,conversation,reference['reference_id'])


def test_runtime_final_preserves_full_protected_body_in_canonical_and_preview_paths(tmp_path,monkeypatch):
    with running_canvas(tmp_path) as (app,server):
        project,space,conversation,operation=_scope(app,monkeypatch)
        runtime=app._shell_runtime
        runtime._stop.set()
        for thread in runtime._threads:thread.join(timeout=3)
        with runtime.control.store.connect('shell') as db:
            row=db.execute('SELECT protected_input FROM canvas_shell_queue WHERE operation_id=?',(operation,)).fetchone()
        message=_decode(row['protected_input'])['message']
        workspace=app.store.workspace(project)['path']
        runtime.conversations.open(workspace,session_id=conversation)
        turn,_=runtime.conversations.begin_turn(conversation,message['content'])
        text=full_text()
        runtime.conversations.finish_response(conversation,turn,text)
        runtime.conversations.end_turn(conversation,turn,'completed')
        runtime.control.durable.update_operation(operation,runtime.owner,state='STARTING')
        runtime.control.durable.update_operation(operation,runtime.owner,state='RUNNING')
        runtime._publish_answer(message,text,'synthetic-test-receipt',evidence={'synthetic_test':True})
        head=runtime.stream.head(project,conversation)
        assert head['status']=='committed' and head['receipt_id']=='synthetic-test-receipt'
        assert read_all(runtime.stream,head['content_ref'],project=project,space=space,conversation=conversation)==text
        result=app.shell_bridge({'action':'message_content','project_id':project,'space_id':space,
            'conversation_id':conversation,'message_id':head['message_id'],'offset':0,'limit':65536})['value']
        assert result['total_chars']==len(text) and result['sha256']==head['content_ref']['sha256']


def test_tampered_unprotected_manifest_metadata_is_detected_against_dpapi_manifest(tmp_path):
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    journal.publish('p','s','c',preview(full_text()));reference=journal.head('p','c')['content_ref']
    with journal.store.connect('shell') as db,db:
        db.execute("UPDATE shell_stream_contents SET sha256=?",('0'*64,))
    with pytest.raises(RuntimeError,match='manifest failed integrity'):
        journal.content('p','s','c',reference['reference_id'])


def test_swapping_valid_protected_chunks_cannot_bypass_the_protected_ordering_manifest(tmp_path):
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    journal.publish('p','s','c',preview(full_text()));reference=journal.head('p','c')['content_ref']
    with journal.store.connect('shell') as db,db:
        second=db.execute('SELECT chunk_sha256 FROM shell_stream_content_pages WHERE chunk_offset=?',(65536,)).fetchone()
        db.execute('UPDATE shell_stream_content_pages SET chunk_sha256=? WHERE chunk_offset=0',(second['chunk_sha256'],))
    with pytest.raises(RuntimeError,match='page failed integrity'):
        journal.content('p','s','c',reference['reference_id'])


def test_content_gc_root_lookups_use_indexes_instead_of_quadratic_chunk_scans(tmp_path):
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    with journal.store.connect('shell') as db:
        chunks=db.execute('EXPLAIN QUERY PLAN SELECT 1 FROM shell_stream_content_pages WHERE owner=? AND project_id=? AND chunk_sha256=?',
            ('owner','p','digest')).fetchall()
        references=db.execute('EXPLAIN QUERY PLAN SELECT 1 FROM shell_stream_content_references WHERE owner=? AND project_id=? AND conversation_id=? AND reference_id=?',
            ('owner','p','c','reference')).fetchall()
    assert any('shell_stream_content_chunk_roots' in row['detail'] for row in chunks)
    assert any('shell_stream_content_reference_roots' in row['detail'] for row in references)


def test_interruption_retains_only_the_current_protected_head_reference_without_body_rewrite(tmp_path,monkeypatch):
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    text=full_text();journal.publish('p','s','c',preview(text))
    head=journal.head('p','c');candidate={**head,'status':'interrupted','activity':'Interrupted; no resend'}
    def counts():
        with journal.store.connect('shell') as db:
            return [db.execute('SELECT COUNT(*) AS n FROM shell_stream_'+table).fetchone()['n']
                    for table in ('contents','content_chunks','content_pages')]
    before=counts()
    monkeypatch.setattr(journal,'_persist_content',lambda *_:pytest.fail('metadata transition must not rewrite full content'))
    sequence=journal.publish('p','s','c',candidate,_retain_reference=True)
    fresh=journal.head('p','c')
    assert sequence>head['sequence'] and fresh['status']=='interrupted'
    assert fresh['content_ref']==head['content_ref'] and counts()==before
    assert read_all(journal,fresh['content_ref'])==text
    assert journal.publish('p','s','c',candidate,_retain_reference=True)==sequence


def test_upstream_or_changed_round_window_scope_and_missing_root_cannot_select_retained_reference(tmp_path):
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    journal.publish('p','s','c',preview(full_text()))
    old=journal.head('p','c');candidate={**old,'status':'interrupted'}
    with pytest.raises(ValueError,match='upstream'):journal.publish('p','s','c',candidate)
    for change in ({'content_offset':old['content_offset']+1},{'content':old['content']+'changed'},
                   {'content_revision':3},{'operation_id':'another-op'},
                   {'content_ref':{**old['content_ref'],'reference_id':'stream-fabricated'}},{'status':'committed'}):
        with pytest.raises(ValueError):journal.publish('p','s','c',{**candidate,**change},_retain_reference=True)
    with pytest.raises(ValueError):journal.publish('p','another-space','c',candidate,_retain_reference=True)
    assert journal.head('p','c')['sequence']==old['sequence']
    journal.publish('p','s','c',preview(full_text(),content_revision=1))
    with pytest.raises(ValueError):journal.publish('p','s','c',candidate,_retain_reference=True)
    latest=journal.head('p','c')
    with journal.store.connect('shell') as db,db:
        db.execute('DELETE FROM shell_stream_content_references WHERE sequence=?',(latest['sequence'],))
    with pytest.raises(ValueError,match='head root'):
        journal.publish('p','s','c',{**latest,'status':'interrupted'},_retain_reference=True)


@pytest.mark.parametrize('stage',['during_content','after_commit'])
def test_abrupt_process_exit_exposes_only_complete_committed_content_references(tmp_path,stage):
    code="""
import os,sys
import sentra_canvas.shell_stream as module
from sentra_mcp.services.control_store import create_control_plane_store
journal=module.ShellStreamJournal(create_control_plane_store(sys.argv[1]),'owner')
def view(text):return {'status':'generating','operation_id':'op','content':text,'content_revision':0}
journal.publish('p','s','c',view('before'))
encode=module._encode
count=0
def interrupt(value):
    global count
    count+=1
    if count==3 and sys.argv[2]=='during_content':os._exit(38)
    return encode(value)
module._encode=interrupt
body=('persisted '+chr(0x1fa90)+' Unicode\\n')*14000
journal.publish('p','s','c',view(body))
os._exit(37)
"""
    child=subprocess.run([sys.executable,'-B','-c',code,str(tmp_path),stage],capture_output=True,timeout=30)
    assert child.returncode==(38 if stage=='during_content' else 37),child.stderr.decode(errors='replace')
    journal=ShellStreamJournal(create_control_plane_store(tmp_path),'owner')
    head=journal.head('p','c')
    if stage=='after_commit':
        assert read_all(journal,head['content_ref'])==('persisted 🪐 Unicode\n')*14000
        assert len(journal.read('p',0)['items'])==2
    else:
        assert head['content']=='before' and 'content_ref' not in head
        assert len(journal.read('p',0)['items'])==1
        with journal.store.connect('shell') as db:
            for table in ('contents','content_chunks','content_pages','content_references'):
                assert db.execute('SELECT COUNT(*) AS n FROM shell_stream_'+table).fetchone()['n']==0


def test_real_http_content_auth_exact_queries_unicode_pages_revocation_and_no_mutations(tmp_path,monkeypatch):
    with running_canvas(tmp_path) as (app,server):
        project,space,conversation,operation=_scope(app,monkeypatch)
        runtime=app._shell_runtime
        runtime._stop.set()
        for thread in runtime._threads:thread.join(timeout=3)
        runtime._stream_thread.join(timeout=3)
        text=full_text();runtime.stream.publish(project,space,conversation,preview(text,operation_id=operation))
        reference=runtime.stream.head(project,conversation)['content_ref']
        other_space=app.shell_bridge({'action':'space_create','project_id':project,'space_id':space,
            'request_key':'stream-content-other-space','name':'Other content Space'})['value']['space_id']
        foreign=ShellStreamJournal(runtime.control.store,'foreign-owner')
        foreign.publish(project,space,conversation,preview(text+'private foreign owner',operation_id='foreign-op'))
        foreign_reference=foreign.head(project,conversation)['content_ref']
        scope={'project_id':project,'space_id':space,'conversation_id':conversation,'reference_id':reference['reference_id']}
        path='/api/shell/stream/content?'+urlencode(scope)
        def snapshot():
            with runtime.control.store.connect('shell') as db:return '\n'.join(db.iterdump())
        before=snapshot()
        assert request(server,path,authorized=False)[0]==401
        pieces=[];offset=0
        while offset is not None:
            code,page=request(server,path+'&'+urlencode({'offset':offset,'limit':65001}))
            assert code==200 and page['offset']==offset and page['sha256']==reference['sha256']
            pieces.append(page['content']);offset=page['next_offset']
        assert ''.join(pieces)==text
        for suffix in ('&owner=forged','&space_id=duplicate','&limit=0','&limit=65537','&limit=',
                       '&offset=-1','&offset=1.0','&offset=%EF%BC%91','&offset=99999999999','&offset=1&offset=2'):
            assert request(server,path+suffix)[0]==400,suffix
        assert request(server,path.replace('reference_id='+reference['reference_id'],'reference_id='))[0]==400
        assert request(server,path.replace('reference_id='+reference['reference_id'],'reference_id=stream-missing'))[0]==404
        assert request(server,path.replace('reference_id='+reference['reference_id'],'reference_id='+foreign_reference['reference_id']))[0]==404
        assert request(server,path.replace('conversation_id='+conversation,'conversation_id=conversation-missing'))[0]==404
        assert request(server,path.replace('space_id='+space,'space_id=space-missing'))[0]==404
        assert request(server,path.replace('space_id='+space,'space_id='+other_space))[0]==403
        req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,headers={'Authorization':'Bearer '+server.secret})
        with urllib.request.urlopen(req,timeout=10) as response:assert response.headers['Cache-Control']=='no-store'
        assert snapshot()==before # no requests, messages, queue, events, refs or receipts inserted
        old_secret=server.secret;server.secret='synthetic-rotated-session'
        stale=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,headers={'Authorization':'Bearer '+old_secret})
        with pytest.raises(urllib.error.HTTPError) as expired:urllib.request.urlopen(stale,timeout=10)
        assert expired.value.code==401
        with runtime.control.store.connect('shell') as db,db:
            db.execute("DELETE FROM shell_entities WHERE kind='conversation' AND entity_id=?",(conversation,))
        assert request(server,path)[0]==404
