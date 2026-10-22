"""Owner-scoped presentation state. Restoring it never opens a resource."""
from contextlib import closing
import json
import math
import time
from sentra_core.conversations import _encode,_decode
from .workspace_contract import inventory

KINDS={'map','terminals','files','review','browser','computer','activity'}


def validate_profile(value):
    def text(x,n=128):return isinstance(x,str) and 0<len(x)<=n and '\0' not in x
    def tab(t):
        return isinstance(t,dict) and not set(t)-{'id','kind','resourceId','dotId','conversationId','executionWorkspaceId','label'} and text(t.get('id'),255) and t.get('kind') in KINDS and all(k not in t or text(t[k],128 if k!='label' else 80) for k in ('resourceId','dotId','conversationId','executionWorkspaceId','label'))
    def layout(v):
        if not isinstance(v,dict) or set(v)-{'version','tree','panes','focused','chrome'} or type(v.get('version')) is not int or v.get('version')!=1 or not isinstance(v.get('panes'),dict):return False
        ids=set();count=0
        def walk(node,depth=0):
            nonlocal count
            count+=1
            if not isinstance(node,dict) or count>31 or depth>8:return False
            if node.get('type')=='leaf':
                key=node.get('groupId')
                if set(node)!={'type','groupId'} or not text(key,80) or key in ids:return False
                ids.add(key);p=v['panes'].get(key)
                return isinstance(p,dict) and set(p)=={'tabs','active'} and isinstance(p['tabs'],list) and len(p['tabs'])<=30 and all(tab(t) for t in p['tabs']) and len({t['id'] for t in p['tabs']})==len(p['tabs']) and (p['active'] is None or p['active'] in {t['id'] for t in p['tabs']})
            r=node.get('ratio')
            return set(node)=={'type','direction','ratio','first','second'} and node.get('type')=='split' and node.get('direction') in {'horizontal','vertical'} and type(r) in {float,int} and math.isfinite(r) and .15<=r<=.85 and walk(node['first'],depth+1) and walk(node['second'],depth+1)
        chrome=v.get('chrome',{})
        return walk(v.get('tree')) and ids==set(v['panes']) and v.get('focused') in ids and isinstance(chrome,dict) and not set(chrome)-{'explorerRatio'} and ('explorerRatio' not in chrome or type(chrome['explorerRatio']) in {int,float} and math.isfinite(chrome['explorerRatio']) and .15<=chrome['explorerRatio']<=.85)
    if not isinstance(value,dict) or set(value)!={'version','layouts','sessionNames','recent','started','focusPanels'} or (type(value['version']) is not int or value['version']!=1):return False
    if type(value['started']) is not bool or type(value['focusPanels']) is not bool:return False
    if not isinstance(value['layouts'],dict) or set(value['layouts'])-{'simple','advanced'} or not all(layout(v) for v in value['layouts'].values()):return False
    if not isinstance(value['sessionNames'],dict) or len(value['sessionNames'])>200 or not all(text(k) and text(v,80) for k,v in value['sessionNames'].items()):return False
    return isinstance(value['recent'],list) and len(value['recent'])<=12 and all(tab(t) for t in value['recent']) and len(json.dumps(value,allow_nan=False).encode())<=64000


def dispatch_presentation(canvas,pid,action,params):
    fields={'space_id','dot_id'}|({'expected_revision','profile'} if action=='workspace_presentation_save' else set())
    if set(params)!=fields:raise ValueError('exact presentation scope required')
    view=inventory(canvas,pid,{k:params[k] for k in ('space_id','dot_id')})
    control=canvas._shell_service();owner=canvas._runtime().owner;key=view['layout_scope']
    if action=='workspace_presentation_save' and (type(params['expected_revision']) is not int or params['expected_revision']<0 or not validate_profile(params['profile'])):raise ValueError('invalid versioned presentation profile')
    with closing(control.store.connect('shell')) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS canvas_workspace_presentation(owner TEXT NOT NULL,scope TEXT NOT NULL,version INTEGER NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(owner,scope))')
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM canvas_workspace_presentation WHERE owner=? AND scope=?',(owner,key)).fetchone()
        if row and row['version']!=1:raise RuntimeError('presentation schema is newer than this application')
        old=_decode(row['body']) if row else None;revision=row['revision'] if row else 0
        if action=='workspace_presentation_get':return {'scope':key,'revision':revision,'profile':old,'restoration_creates_resources':False}
        if old==params['profile']:return {'saved':True,'revision':revision,'scope':key}
        if revision!=params['expected_revision']:return {'saved':False,'conflict':True,'revision':revision,'scope':key,'profile':old,'execution_started':False}
        revision+=1
        db.execute('INSERT INTO canvas_workspace_presentation VALUES(?,?,?,?,?,?) ON CONFLICT(owner,scope) DO UPDATE SET revision=excluded.revision,body=excluded.body,updated_at=excluded.updated_at',
            (owner,key,1,revision,_encode(params['profile']),time.time()))
        return {'saved':True,'revision':revision,'scope':key,'execution_started':False}
