"""Paired devices are scoped clients, never a second grant authority."""
from __future__ import annotations
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

MOBILE_ACTIONS=frozenset({'dot_canvas_get','workspace_inventory','workspace_presentation_get','workspace_request_status','conversation_list','conversation_get',
    'message_list','message_send','message_request_status','coordinator_approval_list','coordinator_approval_reply','document_list','document_get','project_file_list',
    'project_file_preview','project_file_diff','dot_computer_get','dot_computer_read',
    'dot_computer_action','dot_vm_status','dot_vm_frame','dot_vm_input','dot_vm_handoff'})
READ_ACTIONS=MOBILE_ACTIONS-{'message_send','coordinator_approval_reply','dot_computer_action','dot_vm_input','dot_vm_handoff'}


class DeviceRegistry:
    def __init__(self,path,owner):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.owner=owner
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS mobile_invites(id TEXT PRIMARY KEY,owner TEXT,hash TEXT,expires REAL,used INTEGER);
            CREATE TABLE IF NOT EXISTS mobile_devices(id TEXT PRIMARY KEY,owner TEXT,public_key TEXT,name TEXT,state TEXT,token_hash TEXT,protected_token TEXT,scope TEXT,expires REAL);
            CREATE TABLE IF NOT EXISTS mobile_claim_receipts(device_id TEXT PRIMARY KEY,owner TEXT,protected_token TEXT,expires REAL);''')
    @contextmanager
    def db(self):
        conn=sqlite3.connect(self.path,timeout=10);conn.row_factory=sqlite3.Row
        try:
            conn.execute('BEGIN IMMEDIATE');yield conn;conn.commit()
        except BaseException:conn.rollback();raise
        finally:conn.close()
    @staticmethod
    def digest(value):return hashlib.sha256(value.encode()).hexdigest()
    def invite(self):
        token=secrets.token_urlsafe(32);ident=uuid.uuid4().hex
        with self.db() as db:db.execute('INSERT INTO mobile_invites VALUES(?,?,?,?,0)',(ident,self.owner,self.digest(token),time.time()+120))
        return {'invite_id':ident,'invite':token,'expires_in':120}
    def pair(self,invite_id,token,public_key,name):
        import base64
        if not isinstance(public_key,str) or len(base64.b64decode(public_key,validate=True))!=32 or not isinstance(name,str) or not 1<=len(name)<=60:
            raise ValueError('invalid device identity')
        with self.db() as db:
            row=db.execute('SELECT * FROM mobile_invites WHERE id=? AND owner=?',(invite_id,self.owner)).fetchone()
            if not row or row['used'] or row['expires']<time.time() or not hmac.compare_digest(row['hash'],self.digest(token)):
                raise PermissionError('pairing offer expired or consumed')
            db.execute('UPDATE mobile_invites SET used=1 WHERE id=?',(invite_id,))
            ident=uuid.uuid4().hex
            db.execute('INSERT INTO mobile_devices VALUES(?,?,?,?,?,NULL,NULL,NULL,?)',(ident,self.owner,public_key,name,'pending',time.time()+120))
        return {'device_id':ident,'fingerprint':self.digest(public_key),'state':'pending'}
    def list(self):
        with self.db() as db:return [{**dict(r),'fingerprint':self.digest(r['public_key'])} for r in db.execute('SELECT id,name,state,public_key,scope,expires FROM mobile_devices WHERE owner=?',(self.owner,))]
    def approve(self,device_id,scope):
        from sentra_remote.secrets import protect_secret
        if not isinstance(scope,dict) or set(scope)!={'project_id','space_id','dot_id','actions'} or not all(isinstance(scope[k],str) and scope[k] for k in ('project_id','space_id','dot_id')) or not isinstance(scope['actions'],list) or not scope['actions'] or not set(scope['actions'])<=MOBILE_ACTIONS:
            raise ValueError('exact device scope and allowed actions required')
        token=secrets.token_urlsafe(36)
        with self.db() as db:
            row=db.execute('SELECT * FROM mobile_devices WHERE id=? AND owner=?',(device_id,self.owner)).fetchone()
            if not row or row['state']!='pending' or row['expires']<time.time():raise PermissionError('pending device unavailable')
            db.execute("UPDATE mobile_devices SET state='approved',token_hash=?,protected_token=?,scope=?,expires=? WHERE id=?",(self.digest(token),protect_secret(token),json.dumps(scope),time.time()+30*86400,device_id))
        return {'approved':True,'device_id':device_id}
    def claim(self,device_id,public_key):
        from sentra_remote.secrets import unprotect_secret
        with self.db() as db:
            db.execute('DELETE FROM mobile_claim_receipts WHERE expires<?', (time.time(),))
            row=db.execute('SELECT * FROM mobile_devices WHERE id=? AND owner=?',(device_id,self.owner)).fetchone()
            if not row or not hmac.compare_digest(row['public_key'],public_key):raise PermissionError('device identity changed')
            if row['state']=='pending' and row['expires']>time.time():return {'state':'pending'}
            if row['state']=='active' and row['expires']>time.time():
                receipt=db.execute('SELECT * FROM mobile_claim_receipts WHERE device_id=? AND owner=?',
                    (device_id,self.owner)).fetchone()
                if receipt:
                    return {'state':'active','device_id':device_id,
                        'credential':unprotect_secret(receipt['protected_token']),'scope':json.loads(row['scope'])}
            if row['state']!='approved' or row['expires']<time.time():raise PermissionError('pairing not approved')
            token=unprotect_secret(row['protected_token'])
            db.execute('INSERT OR REPLACE INTO mobile_claim_receipts VALUES(?,?,?,?)',
                (device_id,self.owner,row['protected_token'],time.time()+120))
            db.execute("UPDATE mobile_devices SET state='active',protected_token=NULL WHERE id=?",(device_id,))
            return {'state':'active','device_id':device_id,'credential':token,'scope':json.loads(row['scope'])}
    def authenticate(self,device_id,token,public_key):
        with self.db() as db:row=db.execute('SELECT * FROM mobile_devices WHERE id=? AND owner=?',(device_id,self.owner)).fetchone()
        if not row or row['state']!='active' or row['expires']<time.time() or not hmac.compare_digest(row['public_key'],public_key) or not hmac.compare_digest(row['token_hash'] or '',self.digest(token)):
            raise PermissionError('mobile device revoked, expired or invalid')
        return json.loads(row['scope'])
    def revoke(self,device_id):
        with self.db() as db:
            db.execute("UPDATE mobile_devices SET state='revoked',token_hash=NULL,protected_token=NULL WHERE id=? AND owner=?",(device_id,self.owner))
            db.execute('DELETE FROM mobile_claim_receipts WHERE device_id=? AND owner=?',(device_id,self.owner))
        return {'revoked':True}


def registry(canvas):return DeviceRegistry(canvas.state_dir/'mobile-devices.sqlite3',canvas.store.principal)


def owner_control(canvas,body):
    action=body.get('action');devices=registry(canvas)
    if action=='start' and set(body)=={'action','bind'}:
        from .mobile_host import start_installed_host
        return start_installed_host(canvas.state_dir,body['bind'])
    if action=='status' and set(body)=={'action'}:
        from .mobile_network import host_status
        return host_status(canvas.state_dir)
    if action=='invite' and set(body)=={'action'}:
        import base64
        from .mobile_network import host_status
        host=host_status(canvas.state_dir)
        if not host['available'] or host['status']!='ready':
            raise RuntimeError('Gateway LAN não está pronto. Verifique a conexão antes de gerar o convite.')
        offer={**devices.invite(),'endpoint':host['endpoint'],'public_key':host['public_key'],'protocol_version':1}
        uri='sentra://pair#'+base64.urlsafe_b64encode(json.dumps(offer).encode()).decode().rstrip('=')
        return {**offer,'uri':uri}
    if action=='list' and set(body)=={'action'}:return devices.list()
    if action=='approve' and set(body)=={'action','device_id','scope'}:
        from .workspace_contract import inventory
        scope=body['scope'];inventory(canvas,scope['project_id'],{k:scope[k] for k in ('space_id','dot_id')})
        return devices.approve(body['device_id'],scope)
    if action=='revoke' and set(body)=={'action','device_id'}:return devices.revoke(body['device_id'])
    raise ValueError('unsupported owner mobile control')


def gateway_call(canvas,body):
    devices=registry(canvas);method=body['method'];public_key=body['public_key']
    if method=='pair':return devices.pair(body['invite_id'],body['invite'],public_key,body['name'])
    if method=='claim':return devices.claim(body['device_id'],public_key)
    if method != 'request':raise ValueError('unsupported mobile method')
    scope=devices.authenticate(body['device_id'],body['credential'],public_key)
    request=body.get('request')
    if not isinstance(request,dict) or request.get('action') not in scope['actions'] or any(request.get(k)!=scope[k] for k in ('project_id','space_id','dot_id')):
        raise PermissionError('request outside paired scope')
    action=request['action']
    if action=='workspace_request_status':
        selector=request.get('selector')
        if 'original' in request or not isinstance(selector,dict) or selector.get('action') not in scope['actions']:
            raise PermissionError('original request is outside paired capabilities')
        if selector.get('conversation_id'):
            control=canvas._shell_service()
            from contextlib import closing
            with closing(control.store.connect('shell')) as db:
                conversation=control.shell._entity(db,canvas._runtime().owner,scope['project_id'],'conversation',selector['conversation_id'],space_id=scope['space_id'])
            if conversation.get('dot_id')!=scope['dot_id']:raise PermissionError('original conversation outside paired Dot')
    if action=='dot_vm_input' and (not isinstance(request.get('arguments'),dict) or request['arguments'].get('action')!='input.tap'):
        raise PermissionError('mobile VM input currently supports host-owned atomic taps only')
    if action=='dot_computer_action':
        machine_request=request.get('request',{})
        if (not isinstance(machine_request,dict) or machine_request.get('action')!='machine_execute' or
                machine_request.get('capability_id') not in {'terminal:read','terminal:write','browser:operate'}):
            raise PermissionError('unsupported scoped mobile machine capability')
        if machine_request.get('capability_id')=='browser:operate' and machine_request.get('arguments',{}).get('action') not in {'session.list','session.status','observe','navigate','open','evidence'}:
            raise PermissionError('mobile browser input requires a separately bound input lease')
    if action not in READ_ACTIONS and (not isinstance(request.get('request_key'),str) or not 8<=len(request['request_key'])<=128):raise ValueError('durable request key required')
    # Validate membership at every request; pairing does not freeze authorization.
    from .workspace_contract import inventory
    inventory(canvas,scope['project_id'],{k:scope[k] for k in ('space_id','dot_id')})
    if action in {'coordinator_approval_list','coordinator_approval_reply'}:
        return scoped_approvals(canvas,scope,request)
    if request.get('conversation_id'):
        control=canvas._shell_service()
        from contextlib import closing
        with closing(control.store.connect('shell')) as db:
            conversation=control.shell._entity(db,canvas._runtime().owner,scope['project_id'],'conversation',request['conversation_id'],space_id=scope['space_id'])
        if conversation.get('dot_id')!=scope['dot_id']:raise PermissionError('conversation outside paired Dot')
    # Remove presentation selectors only for contracts that do not accept them.
    forwarded=dict(request)
    if action in {'conversation_list','project_file_list','project_file_preview','project_file_diff','document_list','document_get','conversation_get','message_list','message_request_status'}:forwarded.pop('dot_id',None)
    result=canvas.shell_bridge(forwarded,input_client_id='mobile:'+body['device_id'])
    if action=='conversation_list':
        result={**result,'value':{**result['value'],'items':[c for c in result['value'].get('items',[]) if c.get('dot_id')==scope['dot_id']]}}
    return result


def scoped_approvals(canvas,scope,request):
    """Resolve protected approval identity before exposing or answering it."""
    from contextlib import closing
    from sentra_runtime.coordinator_approvals import CoordinatorApprovalInbox
    control=canvas._shell_service();owner=canvas._runtime().owner
    inbox=CoordinatorApprovalInbox(control,owner)
    def allowed(row):
        if row['space_id']!=scope['space_id']:return False
        with closing(control.store.connect('shell')) as db:
            conversation=control.shell._entity(db,owner,scope['project_id'],'conversation',
                row['conversation_id'],space_id=scope['space_id'])
        return conversation.get('dot_id')==scope['dot_id']
    if request['action']=='coordinator_approval_list':
        if set(request)-{'action','project_id','space_id','dot_id','limit'}:raise ValueError('unsupported mobile approval fields')
        value=inbox.list(scope['project_id'],limit=100)
        return {'ok':True,'value':{**value,'items':[row for row in value['items'] if allowed(row)]}}
    if set(request)-{'action','project_id','space_id','dot_id','request_key','approval_id','answer'}:
        raise ValueError('unsupported mobile approval fields')
    row=inbox.get(scope['project_id'],request['approval_id'])
    if not allowed(row):raise PermissionError('approval outside paired Dot')
    return canvas.shell_bridge({k:v for k,v in request.items() if k!='dot_id'})
