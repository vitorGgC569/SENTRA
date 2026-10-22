"""Real Chromium and the same scoped bridge used by workspace/mobile panels."""
import os
import threading
import uuid
import hashlib
import json
import base64
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from test_shell_dot_features import shell,dot


@pytest.mark.skipif(os.environ.get('SENTRA_PLAYWRIGHT_ACCEPTANCE')!='1',reason='explicit real Chromium acceptance')
def test_workspace_browser_observation_receipt_and_revocation(shell):
    app,_server,scope,call=shell
    class Page(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            content=b'<html><body><h1>Workspace fixture</h1><button>Review draft</button></body></html>'
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
    server=ThreadingHTTPServer(('127.0.0.1',0),Page)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        actor=dot(call,'Browser');conversation=call('conversation_create',dot_id=actor['dot_id'])
        origin='http://127.0.0.1:'+str(server.server_port)
        machine=app.center_configure_machine(scope['project_id'],actor['agent_id'],'browser',
            profiles=[{'name':'test','mode':'loopback','allowed_origins':[origin],'remember_login':True}],headless=True)
        control=app._shell_service();owner=app._runtime().owner;run=app._runtime().run(scope['project_id'])
        item=control.create_work_item(run['run_id'],owner,objective='Observe local fixture through actual browser',
            assignee_agent_id=actor['agent_id'],required_capabilities=['browser:operate'],
            metadata={'workspace_id':scope['project_id'],'machine_id':machine['machine_id'],'conversation_id':conversation['conversation_id']})
        control.start_work_item_execution(item['work_item_id'],owner,run_id=run['run_id'],agent_id=actor['agent_id'])
        grant=control.authorization.grant(owner,principal_type='agent',principal_id=actor['agent_id'],
            capability='browser:operate',scope_type='work_item',scope_id=item['work_item_id'])
        originals=[]
        def execute(arguments):
            original={'action':'dot_computer_action',**scope,
            'dot_id':actor['dot_id'],'conversation_id':conversation['conversation_id'],'request_key':uuid.uuid4().hex,
            'request':{'action':'machine_execute','machine_id':machine['machine_id'],'work_item_id':item['work_item_id'],
                'capability_id':'browser:operate','arguments':arguments}}
            originals.append(original)
            return app.shell_bridge(original)['value']
        opened=execute({'action':'open','profile':'test'});assert opened['state']=='SUCCEEDED',opened
        session=opened['evidence']['session_id']
        navigated=execute({'action':'navigate','session_id':session,'url':origin+'/fixture'})
        assert navigated['state']=='SUCCEEDED',navigated
        observed=execute({'action':'observe','session_id':session,'include_image':True,'include_design':True})
        assert observed['state']=='SUCCEEDED',observed
        assert 'Review draft' in observed['evidence']['semantic_summary']
        image=observed['evidence']['viewport_image']
        raw=base64.b64decode(image['base64'],validate=True)
        assert raw.startswith(b'\xff\xd8') and len(raw)<=1024*1024
        assert image['sha256']==hashlib.sha256(raw).hexdigest()
        assert image['page_id']==observed['evidence']['page_id']
        assert image['observation_id']==observed['evidence']['observation_id']
        designed=next(e for e in observed['evidence']['elements'] if e['role']=='button')
        assert designed['design']['box']['width']>0
        assert designed['design']['selector'] and designed['design']['styles']['font-size']
        receipt=app.shell_bridge({'action':'dot_computer_read',**scope,'dot_id':actor['dot_id'],
            'conversation_id':conversation['conversation_id'],'request':{'action':'machine_observe','target_operation_id':observed['operation_id']}})['value']
        assert receipt['state']=='SUCCEEDED'
        # Drop the original caller's projection and recover using only durable
        # selectors, as a freshly opened desktop or phone would do.
        original=originals[0]
        intent=original['request'];action=intent['action']
        payload={'space_id':scope['space_id'],**{k:v for k,v in intent.items() if k!='action'}}
        fingerprint=hashlib.sha256(json.dumps([action,payload],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        for _ in range(2):
            recovered=app.shell_bridge({'action':'workspace_request_status',**scope,'dot_id':actor['dot_id'],
                'selector':{'action':'dot_computer_action','request_key':original['request_key'],
                            'fingerprint':fingerprint,'conversation_id':conversation['conversation_id']}})['value']
            assert recovered['resolved'] and recovered['operation']['operation_id']==opened['operation_id']
            assert recovered['receipt']['stage']=='completed' and recovered['automatic_retry'] is False
            assert 'intent' not in recovered
        sessions=execute({'action':'session.list','limit':20})
        assert len(sessions['evidence']['sessions'])==1
        from sentra_canvas.mobile_devices import registry,gateway_call
        devices=registry(app);offer=devices.invite();public=base64.b64encode(b'r'*32).decode()
        paired=devices.pair(offer['invite_id'],offer['invite'],public,'Recovery phone')
        devices.approve(paired['device_id'],{**scope,'dot_id':actor['dot_id'],
            'actions':['workspace_request_status','dot_computer_action']})
        device=devices.claim(paired['device_id'],public)
        query={'method':'request','public_key':public,'device_id':paired['device_id'],
            'credential':device['credential'],'request':{'action':'workspace_request_status',**scope,
                'dot_id':actor['dot_id'],'selector':{'action':'dot_computer_action',
                    'request_key':original['request_key'],'fingerprint':fingerprint,
                    'conversation_id':conversation['conversation_id']}}}
        assert gateway_call(app,query)['value']['operation']['operation_id']==opened['operation_id']
        devices.revoke(paired['device_id'])
        with pytest.raises(PermissionError):gateway_call(app,query)
        assert execute({'action':'profile.forget','profile':'test'})['state']=='SUCCEEDED'
        assert execute({'action':'close','session_id':session})['state']=='SUCCEEDED'
        forgotten=execute({'action':'profile.forget','profile':'test'})
        assert forgotten['state']=='SUCCEEDED' and forgotten['evidence']['login_persistence']=='forgotten'
        control.authorization.revoke(grant['grant_id'],owner)
        with pytest.raises(PermissionError):execute({'action':'navigate','session_id':session,'url':origin+'/must-not-run'})
        with pytest.raises(PermissionError):execute({'action':'profile.forget','profile':'test'})
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
