"""Verify persisted file observations through the same authorized read service.

The receipt certifies byte integrity at the observed time, never arbitrary
business correctness or a claim written in an assistant's prose.
"""
from contextlib import closing
import hashlib,json,re,time
from sentra_core.conversations import _encode,_decode
from .shell_requests import ShellHostRequests
from .store import Denied


def schema(control):
    with closing(control.store.connect('shell')) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS shell_task_verifications('
            'owner TEXT NOT NULL,work_item TEXT NOT NULL,operation TEXT NOT NULL,body TEXT NOT NULL,'
            'PRIMARY KEY(owner,work_item,operation))')


def recorded(control,owner,wid):
    schema(control)
    with closing(control.store.connect('shell')) as db:
        rows=db.execute('SELECT body FROM shell_task_verifications WHERE owner=? AND work_item=? ORDER BY rowid DESC LIMIT 1',
            (owner,wid)).fetchall()
    return _decode(rows[0]['body']) if rows else None


def verify(actor,message,dot,payload):
    spec=json.loads(payload.get('value',''))
    if (not isinstance(spec,dict) or set(spec)!={'operation_ids'} or not isinstance(spec['operation_ids'],list)
            or not 1<=len(spec['operation_ids'])<=8 or len(set(spec['operation_ids']))!=len(spec['operation_ids'])
            or any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}',v) for v in spec['operation_ids'])):
        raise ValueError('verification requires one to eight distinct file-read operation_ids')
    key=payload.get('request_key')
    if not isinstance(key,str) or not 8<=len(key)<=128:raise ValueError('persistent verification identity required')
    control,owner=actor.control,actor.owner;requests=ShellHostRequests(control,owner)
    def observe():
        requests.note_before_admission(message['project_id'],key)
        sources=[]
        for oid in spec['operation_ids']:
            op=control.durable.operation_status(oid,owner);p=op.get('progress') or {}
            work=control.work_item_info(p.get('work_item_id'),owner)
            if (op['run_id']!=message['run_id'] or p.get('principal_id')!=dot['agent_id']
                    or p.get('capability_id')!='computer:file.read'
                    or work.get('metadata',{}).get('workspace_id')!=message['project_id']
                    or work.get('metadata',{}).get('conversation_id')!=message['conversation_id']):
                raise Denied('verification evidence belongs to another task or is not a file read')
            result=actor.canvas._machine_service().observe(workspace_id=message['project_id'],operation_id=oid)
            evidence=result.get('evidence') or {};evidence=evidence.get('payload',evidence)
            if result['state']!='SUCCEEDED' or not evidence.get('path') or not re.fullmatch('[a-f0-9]{64}',str(evidence.get('sha256',''))):
                raise Denied('verification requires a successful, hashed file read')
            sources.append((oid,p,evidence))
        requests.note_effect_possible(message['project_id'],key)
        files=[]
        for oid,p,original in sources:
            # Current authorization is checked again by the normal executor.
            read_id='verify-read-'+hashlib.sha256((key+oid).encode()).hexdigest()[:40]
            current=actor.canvas._machine_service().dispatch(workspace_id=message['project_id'],
                work_item_id=p['work_item_id'],machine_id=p['machine_id'],capability_id='computer:file.read',
                operation_id=read_id,idempotency_key=read_id,
                arguments={'action':'read','path':original['path'],'expected_sha256':original['sha256'],
                    'reason':'Conferir a evidência de conclusão deste trabalho'})
            evidence=current.get('evidence') or {};evidence=evidence.get('payload',evidence)
            if current['state']!='SUCCEEDED' or evidence.get('sha256')!=original['sha256']:
                return {'status':'waiting_confirmation','verified':False,'automatic_retry':False,
                    'reason':'O arquivo mudou ou a nova observação não foi confirmada.'}
            files.append({'path':original['path'],'sha256':original['sha256'],
                'source_operation_id':oid,'verification_operation_id':read_id})
        proof={'version':1,'verified':True,'scope':'file_integrity','verified_at':time.time(),
            'receipt_id':'task-verification:'+hashlib.sha256(key.encode()).hexdigest(),
            'work_item_id':message['work_item_id'],'operation_id':message['operation_id'],
            'files':files,'semantic_correctness_claimed':False}
        schema(control)
        with closing(control.store.connect('shell')) as db,db:
            db.execute('INSERT INTO shell_task_verifications VALUES(?,?,?,?) ON CONFLICT(owner,work_item,operation) DO UPDATE SET body=excluded.body',
                (owner,message['work_item_id'],message['operation_id'],_encode(proof)))
        return {'status':'verified','verification':proof,'automatic_retry':False}
    return requests.invoke(message['project_id'],'conversation_result_verify',
        {'space_id':message['space_id'],'conversation_id':message['conversation_id'],**spec},key,observe)


def confirm_for_publish(runtime,message):
    proof=recorded(runtime.control,runtime.owner,message['work_item_id'])
    if not proof or proof.get('operation_id')!=message['operation_id']:return None
    verified=True
    for file in proof['files']:
        try:
            source=runtime.control.durable.operation_status(file['source_operation_id'],runtime.owner)
            p=source['progress'];ident='verify-final-'+hashlib.sha256((message['operation_id']+file['source_operation_id']).encode()).hexdigest()[:40]
            current=runtime.canvas._machine_service().dispatch(workspace_id=message['project_id'],
                work_item_id=p['work_item_id'],machine_id=p['machine_id'],capability_id='computer:file.read',
                operation_id=ident,idempotency_key=ident,arguments={'action':'read','path':file['path'],
                    'expected_sha256':file['sha256'],'reason':'Conferir a evidência antes de publicar a conclusão'})
            evidence=current.get('evidence') or {};evidence=evidence.get('payload',evidence)
            verified=verified and current['state']=='SUCCEEDED' and evidence.get('sha256')==file['sha256']
            file['final_observation_operation_id']=ident
        except (PermissionError,ValueError,OSError,KeyError):verified=False
    proof={**proof,'verified':verified,'finalized':True,'published_check_at':time.time()}
    with closing(runtime.control.store.connect('shell')) as db,db:
        db.execute('UPDATE shell_task_verifications SET body=? WHERE owner=? AND work_item=? AND operation=?',
            (_encode(proof),runtime.owner,message['work_item_id'],message['operation_id']))
    return proof
