import base64
import hashlib
import io
import json
import urllib.request
from pathlib import Path
from contextlib import closing

import pytest
from PIL import Image

from test_shell_dot_features import shell, dot
from sentra_core.generated_media import GeneratedMediaStore, validate_asset, TRANSPORT
from sentra_canvas.shell_generated_media import ShellGeneratedMedia


def image_payload(request_id='native-test-turn'):
    image = Image.new('RGB', (4, 3), (25, 100, 200))
    stream = io.BytesIO(); image.save(stream, format='PNG'); raw = stream.getvalue()
    return {'type':'sentra.generated_asset','transport':TRANSPORT,'request_id':request_id,
        'conversation_id':'remote-conversation','message_id':'remote-assistant','filename':'sentra.png',
        'mime_type':'image/png','byte_length':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
        'data_base64':base64.b64encode(raw).decode()}, raw


def prepare(shell, monkeypatch):
    app, server, scope, call = shell
    actor = dot(call, 'Media owner')
    cid = call('conversation_create',dot_id=actor['dot_id'])['conversation_id']
    runtime = app._shell_runtime
    monkeypatch.setattr(runtime, '_execute', lambda _: None)
    sent = call('message_send',conversation_id=cid,content='Create image')
    workspace = app.store.workspace(scope['project_id'])['path']
    runtime.conversations.open(workspace,session_id=cid)
    turn, _ = runtime.conversations.begin_turn(cid,'Create image')
    native_id = 'native-test-turn'
    context = {'owner':runtime.owner,'workspace':workspace,'run_id':app._runtime().run(scope['project_id'])['run_id'],
        'work_item_id':sent['work_item_id'],'operation_id':sent['operation_id'],'agent_id':actor['agent_id']}
    runtime.conversations.provider_state(cid,turn,'gateway',native_id,'submitted',context=context)
    store = GeneratedMediaStore(runtime.conversations)
    payload, raw = image_payload(native_id)
    asset_id = store.stage(cid,turn,'gateway',native_id,payload)
    message = {**sent,**scope,'conversation_id':cid,'run_id':context['run_id']}
    return app,server,scope,call,actor,cid,runtime,turn,native_id,store,asset_id,message,payload,raw


def test_binary_is_encrypted_and_pending_provider_cannot_publish(shell,monkeypatch):
    app,server,scope,call,actor,cid,runtime,turn,native,store,asset_id,message,payload,raw = prepare(shell,monkeypatch)
    with pytest.raises(PermissionError): store.read(cid,asset_id)
    publisher = ShellGeneratedMedia(runtime)
    assert publisher.publish(message,actor,'assistant-test') == []
    with runtime.conversations._connect() as db:
        wrapped = db.execute('SELECT protected_bytes FROM generated_provider_media_chunks WHERE asset_id=?',(asset_id,)).fetchone()[0]
        assert wrapped.startswith(('dpapi:','keyring:')) and payload['data_base64'] not in wrapped
    runtime.conversations.provider_state(cid,turn,'gateway',native,'completed')
    # Transport completion is only 'received'; the CLI then commits its
    # assistant response, advancing the provider call to 'completed'.
    with pytest.raises(PermissionError): store.read(cid,asset_id)
    assert publisher.publish(message,actor,'assistant-test') == []
    runtime.conversations.finish_response(cid,turn,'Generated image')
    assert store.read(cid,asset_id)[1] == raw
    assert publisher.publish(message,actor,'assistant-test')[0]['sha256'] == payload['sha256']
    assert publisher.publish({**message,'operation_id':'another-operation'},actor,'assistant-other') == []
    with pytest.raises(PermissionError): store.read('another-conversation',asset_id)


def test_http_returns_bytes_only_for_the_confirmed_original_assistant_message(shell,monkeypatch):
    app,server,scope,call,actor,cid,runtime,turn,native,store,asset_id,message,payload,raw = prepare(shell,monkeypatch)
    runtime.conversations.provider_state(cid,turn,'gateway',native,'completed')
    runtime.conversations.finish_response(cid,turn,'')
    runtime.control.durable.update_operation(message['operation_id'],runtime.owner,state='RUNNING')
    runtime._publish_answer(message,'','conversation:'+cid+':2',evidence={'protected_journal':True})
    messages=call('message_list',conversation_id=cid)['items']
    answer=next(m for m in messages if m['role']=='assistant')
    assert len(answer['generated_assets']) == 1 and 'data_base64' not in json.dumps(answer)
    fields={**scope,'conversation_id':cid,'message_id':answer['message_id'],'asset_id':asset_id}
    from urllib.parse import urlencode
    url=f'http://127.0.0.1:{server.server_port}/api/shell/generated-media?'+urlencode(fields)
    request=urllib.request.Request(url,headers={'Authorization':'Bearer '+server.secret})
    with urllib.request.urlopen(request) as response:
        assert response.headers['Content-Type']=='image/png'
        assert response.headers['X-Content-Type-Options']=='nosniff'
        assert response.read()==raw
    with pytest.raises(urllib.error.HTTPError) as denied: urllib.request.urlopen(url)
    assert denied.value.code==401
    fields['conversation_id']=call('conversation_create',dot_id=actor['dot_id'])['conversation_id']
    request=urllib.request.Request(url.split('?')[0]+'?'+urlencode(fields),headers={'Authorization':'Bearer '+server.secret})
    with pytest.raises(urllib.error.HTTPError) as denied: urllib.request.urlopen(request)
    assert denied.value.code==403


@pytest.mark.parametrize('changes',[{'request_id':'foreign-native-turn'},{'message_id':''},{'sha256':'0'*64},
    {'filename':'../../image.png'},{'mime_type':'image/svg+xml'},{'download_url':'https://untrusted.test/file'},
    {'byte_length':8*1024**2+1}])
def test_generated_bytes_require_exact_identity_integrity_and_safe_format(changes):
    payload,_=image_payload()
    with pytest.raises((ValueError,PermissionError)): validate_asset({**payload,**changes},'native-test-turn')


def test_large_binary_uses_small_protected_chunks(shell,monkeypatch):
    app,server,scope,call,actor,cid,runtime,turn,native,store,asset_id,message,payload,raw = prepare(shell,monkeypatch)
    pdf=b'%PDF-1.7\n'+b' '+b'x'*(2*1024**2)+b'\n%%EOF\n'
    large={**payload,'mime_type':'application/pdf','filename':'report.pdf','byte_length':len(pdf),
        'sha256':hashlib.sha256(pdf).hexdigest(),'data_base64':base64.b64encode(pdf).decode()}
    ident=store.stage(cid,turn,'gateway',native,large)
    runtime.conversations.provider_state(cid,turn,'gateway',native,'completed')
    runtime.conversations.finish_response(cid,turn,'Generated PDF')
    assert store.read(cid,ident)[1]==pdf
    with runtime.conversations._connect() as db:
        chunks=db.execute('SELECT protected_bytes FROM generated_provider_media_chunks WHERE asset_id=?',(ident,)).fetchall()
        assert len(chunks)>32 and all(len(chunk[0])<2_000_000 for chunk in chunks)


def test_native_sse_media_only_completion_requires_receipt_and_has_no_base64_text(tmp_path,monkeypatch):
    from sentra_cli.config import CLIConfig
    from sentra_cli.client import ModelClient
    client=ModelClient(CLIConfig(workspace=tmp_path,model='sentra/chatgpt-web/gpt-6'))
    native='native-test-turn'
    monkeypatch.setattr(client,'_next_turn_metadata',lambda: ('{}',native,{}))
    payload,_=image_payload(native)
    def response(complete):
        frames=[payload]
        if complete: frames.append({'type':'response.completed','response':{'output':[]}})
        return io.BytesIO(''.join('data: '+json.dumps(frame)+'\n\n' for frame in frames).encode())
    monkeypatch.setattr(client,'_provider_http',lambda *a,**k: response(True))
    received=[]; states=[]
    client.on_generated_asset=lambda provider,ident,value: received.append((ident,value))
    client.on_delivery=lambda provider,ident,state: states.append(state)
    assert list(client._responses_stream([{'role':'user','content':'generate'}],client.config.model)) == []
    assert len(received)==1 and states==['submitted','completed']
    monkeypatch.setattr(client,'_provider_http',lambda *a,**k: response(False))
    with pytest.raises(Exception,match='before completion'):
        list(client._responses_stream([{'role':'user','content':'generate'}],client.config.model))
    assert states[-1]=='uncertain'
