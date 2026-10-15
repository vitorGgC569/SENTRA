"""One scoped tail read, compatible offset pages, fresh delivery reconciliation."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid
import pytest

from test_shell_dot_features import shell, dot
from test_sentra_runtime_canvas_center_http import request


def scope_for(shell):
    app,server,scope,call=shell
    actor=dot(call,'Tail QA')
    conversation=call('conversation_create',dot_id=actor['dot_id'])
    return app,server,{**scope,'conversation_id':conversation['conversation_id']},call


def seed_messages(app,scope,count,*,start=0,body=None):
    coordinator,owner=app._shell_runtime.control.shell,app._shell_runtime.owner
    result=[]
    with coordinator.store.connect('shell') as db:
        for index in range(start,start+count):
            mid='message-tail-'+scope['conversation_id'][-12:]+f'-{index:05d}'
            text=body if body is not None else f'Mensagem {index}: Unicode 🪐 ação e\u0301 haha.'
            timestamp=1000+index//3  # deliberate ties test stable message_id ordering
            protected=coordinator._persist_content(db,owner,scope['project_id'],mid,1,text)
            db.execute('INSERT INTO shell_messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (mid,owner,scope['project_id'],scope['space_id'],scope['conversation_id'],'assistant',
                 protected,'dispatched',None,None,'qa-receipt-'+str(index),None,1,timestamp,timestamp))
            result.append((mid,text))
    return result


def read_tail(app,scope,**fields):
    return app.shell_bridge({'action':'message_list',**scope,'tail':True,'limit':50,**fields})['value']


def test_tail_reads_latest_fifty_once_without_migration_and_preserves_unicode_and_older_pages(shell,monkeypatch):
    app,server,scope,call=scope_for(shell)
    seeded=seed_messages(app,scope,123)
    coordinator=app._shell_runtime.control.shell
    with monkeypatch.context() as patch:
        patch.setattr(coordinator,'_migrate',lambda *_:pytest.fail('Tail must not migrate entities'))
        code,envelope=request(server,'/api/shell/bridge',json_body={'action':'message_list',**scope,'tail':True,'limit':50})
    assert code==200
    latest=envelope['value']
    assert [(item['message_id'],item['content']) for item in latest['items']]==seeded[-50:]
    assert latest['page']=={'offset':73,'limit':50,'returned':50,'total':123,'next_offset':None,'tail':True,'previous_offset':23}
    # Older history remains available through the unchanged offset contract.
    collected=list(latest['items']);current_start=latest['page']['offset']
    while current_start:
        offset=max(0,current_start-50)
        older=app.shell_bridge({'action':'message_list',**scope,'offset':offset,'limit':current_start-offset})['value']
        assert 'tail' not in older['page']
        collected=older['items']+collected;current_start=offset
    assert [(item['message_id'],item['content']) for item in collected]==seeded


def test_new_messages_and_revisions_are_fresh_and_legacy_pages_remain_unchanged(shell):
    app,server,scope,call=scope_for(shell)
    original=seed_messages(app,scope,70)
    first=read_tail(app,scope)
    assert [item['message_id'] for item in first['items']]==[mid for mid,_ in original[-50:]]
    added=seed_messages(app,scope,4,start=70)
    latest=read_tail(app,scope)
    assert latest['page']['offset']==24 and latest['page']['total']==74
    assert [(item['message_id'],item['content']) for item in latest['items']]==(original+added)[-50:]
    legacy=app.shell_bridge({'action':'message_list',**scope,'offset':0,'limit':50,'tail':False})['value']
    assert legacy['page']=={'offset':0,'limit':50,'returned':50,'total':74,'next_offset':50}
    assert [item['message_id'] for item in legacy['items']]==[mid for mid,_ in original[:50]]
    from sentra_core.conversations import _encode
    with app._shell_runtime.control.store.connect('shell') as db:
        db.execute('UPDATE shell_messages SET protected_content=?,revision=2 WHERE message_id=?',(_encode('Revisão atual 🪐'),added[-1][0]))
    fresh=read_tail(app,scope)['items'][-1]
    assert fresh['content']=='Revisão atual 🪐' and fresh['revision']==2


def test_empty_short_and_large_content_tail_preserve_original_content_reference(shell):
    app,server,scope,call=scope_for(shell)
    empty=read_tail(app,scope)
    assert empty['items']==[] and empty['page']['total']==0 and empty['page']['previous_offset'] is None
    body='histórico completo 🪐 e\u0301\n'*7000
    seeded=seed_messages(app,scope,1,body=body)
    latest=read_tail(app,scope)
    assert latest['page']['offset']==0 and latest['page']['returned']==1
    message=latest['items'][0]
    assert message['message_id']==seeded[0][0] and message['content_truncated'] is True
    assert message['content_ref']['total_chars']==len(body)
    chunks=[];offset=0
    while offset is not None:
        page=app.shell_bridge({'action':'message_content',**scope,'message_id':message['message_id'],
            'revision':message['revision'],'offset':offset,'limit':65536})['value']
        chunks.append(page['content']);offset=page['next_offset']
    assert ''.join(chunks)==body


def test_tail_enforces_scope_current_session_and_parameter_types(shell):
    app,server,scope,call=scope_for(shell)
    seed_messages(app,scope,2)
    actor=dot(call,'Another tail QA')
    other=call('conversation_create',dot_id=actor['dot_id'])['conversation_id']
    assert read_tail(app,{**scope,'conversation_id':other})['items']==[]
    other_space=call('space_create',name='Tail Space')['space_id']
    with pytest.raises(PermissionError):read_tail(app,{**scope,'space_id':other_space})
    with pytest.raises(FileNotFoundError):read_tail(app,{**scope,'conversation_id':'conversation-missing-tail'})
    with pytest.raises(PermissionError):
        app._shell_runtime.control.shell.dispatch('another-owner',project_id=scope['project_id'],action='message_list',
            payload={'space_id':scope['space_id'],'conversation_id':scope['conversation_id'],'tail':True})
    for extra in ({'tail':'true'},{'tail':1},{'offset':1},{'limit':0},{'limit':201},{'content':'not a send'}):
        with pytest.raises(ValueError):read_tail(app,scope,**extra)
    with pytest.raises(ValueError):read_tail(app,{'project_id':scope['project_id'],'conversation_id':scope['conversation_id']})
    code,_=request(server,'/api/shell/bridge',authorized=False,json_body={'action':'message_list',**scope,'tail':True})
    assert code==401


def test_tail_reconciles_visible_pending_delivery_and_returns_exact_receipt_and_request_key(shell,monkeypatch):
    app,server,scope,call=scope_for(shell)
    seed_messages(app,scope,70)
    runtime=app._shell_runtime
    sends=[]
    monkeypatch.setattr(runtime,'dispatch_message',lambda *args:sends.append(args) or {'status':'uncertain'})
    key='tail-pending-'+uuid.uuid4().hex
    original=app.shell_bridge({'action':'message_send',**scope,'request_key':key,'content':'Keep this send pending'})['value']
    reconciled=[]
    def reconcile(project,owner,message):
        reconciled.append(message['message_id'])
        return {'status':'dispatched','receipt_id':'qa-reconciled-delivery'}
    monkeypatch.setattr(runtime,'reconcile_message',reconcile)
    latest=read_tail(app,scope)
    message=next(item for item in latest['items'] if item['message_id']==original['message_id'])
    assert message['status']=='dispatched' and message['receipt_id']=='qa-reconciled-delivery'
    assert message['operation_id']==original['operation_id'] and message['request_key']==key
    assert reconciled==[original['message_id']] and len(sends)==1


def test_tail_count_and_page_use_one_uncorrelated_indexed_statement(shell,monkeypatch):
    app,server,scope,call=scope_for(shell)
    seed_messages(app,scope,75)
    store=app._shell_runtime.control.store;connect=store.connect;statements=[]
    def traced(namespace,**kwargs):
        db=connect(namespace,**kwargs)
        if namespace=='shell':db.set_trace_callback(statements.append)
        return db
    with monkeypatch.context() as patch:
        patch.setattr(store,'connect',traced)
        assert read_tail(app,scope)['page']['total']==75
    selects=[sql for sql in statements if 'AS conversation_total' in sql]
    assert len(selects)==1
    with closing(connect('shell')) as db:
        details=[row['detail'] for row in db.execute('EXPLAIN QUERY PLAN '+selects[0])]
    assert any('SCALAR SUBQUERY' in detail for detail in details)
    assert all('CORRELATED' not in detail for detail in details)
    assert any('COVERING INDEX shell_messages_conversation' in detail for detail in details)


def test_tail_count_and_rows_are_consistent_when_a_writer_commits_during_the_select(shell,monkeypatch):
    app,server,scope,call=scope_for(shell)
    initial=seed_messages(app,scope,80)
    store=app._shell_runtime.control.store;connect=store.connect
    main=threading.current_thread();reading=threading.Event();written=threading.Event();triggered=[]
    class InterleavedConnection:
        def __init__(self,db):self.db=db
        def __getattr__(self,name):return getattr(self.db,name)
        def __enter__(self):self.db.__enter__();return self
        def __exit__(self,*args):return self.db.__exit__(*args)
        def execute(self,sql,parameters=()):
            if 'AS conversation_total' not in sql:return self.db.execute(sql,parameters)
            def progress():
                if not triggered:
                    triggered.append(True);reading.set()
                    assert written.wait(5),'Concurrent writer did not commit'
                return 0
            self.db.set_progress_handler(progress,10)
            try:return self.db.execute(sql,parameters)
            finally:self.db.set_progress_handler(None,0)
    def interleaved(namespace,**kwargs):
        db=connect(namespace,**kwargs)
        return InterleavedConnection(db) if namespace=='shell' and threading.current_thread() is main else db
    def append():
        assert reading.wait(5),'Tail query did not begin'
        try:return seed_messages(app,scope,5,start=80)
        finally:written.set()
    with monkeypatch.context() as patch,ThreadPoolExecutor(max_workers=1) as pool:
        patch.setattr(store,'connect',interleaved)
        writer=pool.submit(append)
        try:result=read_tail(app,scope)
        finally:reading.set()
        added=writer.result(timeout=6)
    assert triggered and written.is_set()
    total=result['page']['total']
    assert total in {80,85}
    coherent=initial if total==80 else initial+added
    assert [(row['message_id'],row['content']) for row in result['items']]==coherent[-50:]
    assert result['page']['offset']==total-50
    newest=read_tail(app,scope)
    assert newest['page']['total']==85
    assert [(row['message_id'],row['content']) for row in newest['items']]==(initial+added)[-50:]


def test_tail_statement_translates_to_postgres_without_window_or_offset_forms():
    from sentra_mcp.services.postgres_store import native_sql
    sql=("SELECT *, (SELECT COUNT(*) FROM shell_messages WHERE owner=? AND project_id=? AND conversation_id=?) AS conversation_total "
        "FROM shell_messages WHERE owner=? AND project_id=? AND conversation_id=? ORDER BY created_at DESC,message_id DESC LIMIT ?")
    translated=native_sql(sql)
    assert translated.count('%s')==7 and '?' not in translated
    assert 'COUNT(*)' in translated and 'ORDER BY created_at DESC,message_id DESC' in translated
    assert ' OVER(' not in translated and ' OFFSET ' not in translated
