"""New Home contracts against production HTTP, SQLite and attachment storage.

The model scheduler is parked in the message test: this validates admission,
identity and recovery, and deliberately makes no claim about model inference.
"""
import base64
import hashlib
import json
import urllib.request
import uuid

from test_shell_dot_features import shell, dot
from test_sentra_runtime_canvas_center_http import request


def test_production_desktop_serves_the_current_home_and_assets(shell):
    _, server, _, _ = shell
    def get(path):
        req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,
            headers={'Authorization':'Bearer '+server.secret})
        with urllib.request.urlopen(req,timeout=10) as response:
            return response.read()
    page=get('/desktop.html')
    assert b'/desktop-assets/bootstrap.js' in page
    manifest=json.loads(get('/desktop-assets/manifest.json'))
    for name in ('desktop.js','desktop.css'):
        data=get('/desktop-assets/'+name)
        assert hashlib.sha256(data).hexdigest()==manifest['files'][name]
    script=get('/desktop-assets/desktop.js').decode()
    assert 'O que vamos criar?' in script
    assert 'orca-preview-api' not in script
    assert 'shell-start-compose' in get('/desktop-assets/desktop.css').decode()


def test_home_create_and_first_message_keep_one_durable_identity(shell,monkeypatch):
    app,server,scope,call=shell
    selected=dot(call,'Visual integration')
    key=uuid.uuid4().hex
    title='Revisar integração visual e recuperar meu trabalho'
    body={'action':'conversation_create',**scope,'dot_id':selected['dot_id'],
          'title':title,'request_key':key}
    code,first=request(server,'/api/shell/bridge',json_body=body)
    assert code==200,first
    conversation=first['value']
    code,repeated=request(server,'/api/shell/bridge',json_body=body)
    assert code==200 and repeated['value']['conversation_id']==conversation['conversation_id']
    listed=call('conversation_list')['items']
    assert len(listed)==1 and listed[0]['conversation_id']==conversation['conversation_id']
    assert all(listed[0][field]==conversation[field] for field in ('project_id','space_id','dot_id','title'))
    assert conversation['title']==title
    # The real admission and protected outbox run; an external model does not.
    monkeypatch.setattr(app._shell_runtime,'_execute',lambda _:None)
    content='Confira o visual.\nPreserve o rascunho, acentos e Unicode 😀.'
    sent=call('message_send',conversation_id=conversation['conversation_id'],content=content)
    messages=call('message_list',conversation_id=conversation['conversation_id'])['items']
    assert len(messages)==1 and messages[0]['content']==content
    assert messages[0]['operation_id']==sent['operation_id']
    restored=call('conversation_get',conversation_id=conversation['conversation_id'])
    assert restored['conversation_id']==conversation['conversation_id']
    assert app.store.resource('agents',selected['agent_id'],scope['project_id'])['id']==selected['agent_id']
    assert not app._sessions  # Opening a conversation never launches a terminal.


def test_home_attachment_handoff_uses_real_chunked_storage_and_scope(shell):
    app,server,scope,call=shell
    selected=dot(call,'Attachment integration')
    conversation=call('conversation_create',dot_id=selected['dot_id'])
    cid=conversation['conversation_id']
    data='Documento de homologação. Nenhuma credencial ou dado pessoal.\n'.encode()
    digest=hashlib.sha256(data).hexdigest()
    upload=call('attachment_upload_begin',conversation_id=cid,kind='text',name='homologacao.txt',
        total_bytes=len(data),total_sha256=digest)
    chunk=call('attachment_upload_chunk',conversation_id=cid,upload_id=upload['upload_id'],index=0,
        data_url='data:application/octet-stream;base64,'+base64.b64encode(data).decode(),chunk_sha256=digest)
    assert chunk['received_bytes']==len(data)
    result=call('attachment_upload_complete',conversation_id=cid,upload_id=upload['upload_id'])
    stored=result['attachments'][0]
    assert stored['sha256']==digest
    attachments=app._shell_runtime.optional._attachment_store()
    descriptor,raw=attachments.read_bytes(app._runtime().owner,stored['attachment_id'])
    assert raw==data and descriptor['conversation_id']==cid
    other=call('conversation_create',dot_id=selected['dot_id'])
    code,_=request(server,'/api/shell/bridge',json_body={'action':'attachment_upload_status',**scope,
        'conversation_id':other['conversation_id'],'upload_id':upload['upload_id'],'request_key':uuid.uuid4().hex})
    assert code!=200  # Navigation cannot attach another conversation's file.
