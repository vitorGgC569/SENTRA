"""Configured real Daytona SDK lifecycle, persistent PTY/command identities.

No UI service is started and no caller may pick a remote sandbox/PTY ID.
SDK/transport postconditions are provider reports, not sandbox attestation.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import re
import threading
import time
from dataclasses import dataclass,field
from pathlib import Path
from urllib.parse import urlsplit

from .identity_sessions import SessionExecutor,SessionScope,SessionJournal,declare_session_machine
from .rpa import ExecutorFailure,effect_checkpoint,AuthorizedPaths

DAYTONA_SESSION_ACTIONS=frozenset({'session.list','sandbox.create','sandbox.read','sandbox.reconcile','sandbox.start','sandbox.stop','sandbox.delete',
    'pty.create','pty.reattach','pty.read','pty.write','pty.resize','pty.cancel','pty.disconnect',
    'command.create','command.execute','command.read','command.input','command.cancel','evidence.export'})


@dataclass(frozen=True)
class DaytonaConnectionConfig:
    api_url:str
    target:str
    credential:object=field(repr=False,compare=False)
    allowed_sdk_versions:tuple[str,...]=()
    pty_handle_sha256:str=''
    request_timeout_seconds:float=8.0

    def __post_init__(self):
        p=urlsplit(self.api_url)
        if (p.scheme not in {'https','http'} or not p.hostname or p.username or p.password or p.query or p.fragment or
                p.scheme=='http' and p.hostname not in {'127.0.0.1','::1'} or not self.target or
                not callable(self.credential) or not self.allowed_sdk_versions or
                not re.fullmatch('[0-9a-f]{64}',self.pty_handle_sha256) or not 0<self.request_timeout_seconds<=30):
            raise ValueError('explicit_daytona_endpoint_credentials_version_and_pty_pin_required')


@dataclass(frozen=True)
class DaytonaSessionBinding:
    capability_id:str
    connection:DaytonaConnectionConfig
    paths:AuthorizedPaths
    existing_sandbox_ids:tuple[str,...]=()
    trusted_snapshot:str|None=None
    actions:tuple[str,...]=tuple(sorted(DAYTONA_SESSION_ACTIONS))
    timeout_seconds:float=45.0
    auto_stop_minutes:int=15
    auto_archive_minutes:int=60
    auto_delete_minutes:int=120
    cwd:str='/home/daytona'
    max_read_bytes:int=65536
    max_sessions:int=16
    allow_pty_input:bool=False
    allowed_commands:tuple[str,...]=()

    def __post_init__(self):
        if (not self.capability_id or not set(self.actions)<=DAYTONA_SESSION_ACTIONS or
                not 12<=self.timeout_seconds<=120 or self.connection.request_timeout_seconds>=self.timeout_seconds/2 or
                any(type(n) is not int or n<0 for n in (self.auto_stop_minutes,self.auto_archive_minutes,self.auto_delete_minutes)) or
                not 1<=self.max_read_bytes<=1024*1024 or not 1<=self.max_sessions<=64 or
                not self.cwd.startswith('/') or '\x00' in self.cwd or type(self.allow_pty_input) is not bool):
            raise ValueError('invalid_daytona_session_binding')

    @property
    def identity(self):
        return hashlib.sha256(json.dumps([self.capability_id,self.connection.api_url,self.connection.target,
            self.connection.allowed_sdk_versions,self.connection.pty_handle_sha256,self.existing_sandbox_ids,
            self.trusted_snapshot,self.allow_pty_input,self.allowed_commands,self.cwd,self.actions],sort_keys=True).encode()).hexdigest()


class DaytonaSessionBackend:
    def __init__(self,journal:SessionJournal):
        self.journal=journal; self.lock=threading.RLock(); self.clients={};self.handles={};self.log_streams={}

    def _sdk(self,b):
        cfg=b.connection
        try:version=importlib.metadata.version('daytona')
        except importlib.metadata.PackageNotFoundError as exc:raise ExecutorFailure('daytona_sdk_missing') from exc
        if version not in cfg.allowed_sdk_versions:raise ExecutorFailure('daytona_sdk_version_not_pinned',evidence={'installed':version})
        import daytona,httpx,urllib3
        from daytona.handle.pty_handle import PtyHandle
        source=Path(inspect.getfile(PtyHandle)).read_bytes()
        if hashlib.sha256(source).hexdigest()!=cfg.pty_handle_sha256:
            raise ExecutorFailure('daytona_pty_implementation_pin_mismatch')
        key=(cfg.api_url,cfg.target,version,id(cfg.credential))
        if key not in self.clients:
            secret=cfg.credential()
            if not isinstance(secret,str) or not secret:raise ExecutorFailure('daytona_credential_unavailable')
            class ExplicitEnvironment:
                def get(self,*_args,**_kwargs):return None
            effect_checkpoint()
            client=daytona.Daytona(daytona.DaytonaConfig(api_url=cfg.api_url,target=cfg.target,
                api_key=secret,otel_enabled=False),env_reader=ExplicitEnvironment())
            try:
                # get/PTY metadata SDK methods expose no request_timeout argument.
                # Configure their actual generated HTTP pools rather than wrapping
                # an unbounded call in a thread and asserting cancellation.
                for api in (client._api_client,client._toolbox_api_client):
                    api.rest_client.pool_manager.connection_pool_kw['timeout']=urllib3.Timeout(
                        connect=cfg.request_timeout_seconds,read=cfg.request_timeout_seconds)
                    original=api.rest_client.request
                    def guarded_request(*args,_request=original,**kwargs):
                        # SDK create/start waits issue several HTTP calls. The
                        # current central ContextVar must be checked per call.
                        effect_checkpoint();return _request(*args,**kwargs)
                    api.rest_client.request=guarded_request
                client._http_client.timeout=httpx.Timeout(cfg.request_timeout_seconds)
                client._http_client.event_hooks['request'].append(lambda _request:effect_checkpoint())
            except AttributeError as exc:raise ExecutorFailure('daytona_sdk_bounded_transport_unsupported') from exc
            self.clients[key]=client
        return self.clients[key],daytona,version

    def _sandbox(self,client,b,row):
        sid=row['metadata'].get('sandbox_id',row['remote_id'])
        effect_checkpoint(); sandbox=client.get(sid)
        if sandbox.id!=sid or getattr(sandbox,'public',None) is not False or getattr(sandbox,'network_block_all',None) is not True:
            raise ExecutorFailure('daytona_remote_postconditions_changed')
        if row['metadata'].get('managed'):
            labels=getattr(sandbox,'labels',{}) or {}
            if labels.get('sentra-scope')!=row['scope'] or labels.get('sentra-resource')!=row['metadata']['resource_token']:
                raise ExecutorFailure('daytona_remote_ownership_label_mismatch')
        elif sid not in b.existing_sandbox_ids:
            raise ExecutorFailure('daytona_sandbox_outside_host_inventory')
        return sandbox

    def run(self,b,a):
        with self.lock:
            action,scope=a['action'],a['_scope']
            if action=='session.list':return self.journal.list(scope,'daytona',b.identity,limit=a.get('limit',64))
            if action=='evidence.export':
                row=self.journal.get(a['session_id'],scope,'daytona',b.identity)
                return {'artifact':self.journal.export(row,b.paths,a['output'])}
            client,sdk,version=self._sdk(b)
            mutating=action not in {'sandbox.read','sandbox.reconcile','pty.read','command.read','pty.reattach'}
            if mutating:
                old=self.journal.reserve_effect(a['_operation_id'],scope,a)
                if old is not None:return old
            dispatched=False;row=None;child=None
            try:
                if action=='sandbox.create':
                    if not b.trusted_snapshot:raise ExecutorFailure('daytona_provisioning_not_configured')
                    token=hashlib.sha256((scope+a['_operation_id']).encode()).hexdigest()
                    name='sentra-'+token[:24]
                    row=self.journal.create(scope,'daytona',b.identity,name,
                        {'managed':True,'sandbox_id':name,'resource_token':token,'resource_kind':'sandbox','sdk_version':version},max_sessions=b.max_sessions)
                    params=sdk.CreateSandboxFromSnapshotParams(name=name,snapshot=b.trusted_snapshot,public=False,
                        network_block_all=True,labels={'sentra-scope':scope,'sentra-resource':token},
                        auto_stop_interval=b.auto_stop_minutes,auto_archive_interval=b.auto_archive_minutes,
                        auto_delete_interval=b.auto_delete_minutes,ephemeral=False)
                    effect_checkpoint();dispatched=True
                    sandbox=client.create(params,timeout=b.timeout_seconds-5)
                    row['remote_id']=sandbox.id;row['metadata']['sandbox_id']=sandbox.id
                    self.journal.update(row,remote_id=sandbox.id,metadata=row['metadata'],state='CREATED')
                    self._sandbox(client,b,row)
                    result={'session_id':row['id'],'sandbox_id':sandbox.id,'remote_state':str(getattr(sandbox.state,'value',sandbox.state)),
                            'provider_reported_private':True,'provider_reported_network_blocked':True,'attested_isolation':False}
                elif action=='sandbox.read' and 'session_id' not in a:
                    sid=a['inventory_sandbox_id']
                    if sid not in b.existing_sandbox_ids:raise ExecutorFailure('daytona_inventory_scope_mismatch')
                    row=self.journal.create(scope,'daytona',b.identity,sid,
                        {'managed':False,'sandbox_id':sid,'resource_kind':'sandbox'},max_sessions=b.max_sessions)
                    sandbox=self._sandbox(client,b,row)
                    self.journal.update(row,state='OBSERVED')
                    result={'session_id':row['id'],'sandbox_id':sid,'remote_state':str(getattr(sandbox.state,'value',sandbox.state))}
                else:
                    row=self.journal.get(a['session_id'],scope,'daytona',b.identity)
                    if action=='sandbox.reconcile':
                        if not row['metadata'].get('managed') or row['metadata']['resource_kind']!='sandbox':
                            raise ExecutorFailure('daytona_reconcile_requires_owned_sandbox_intent')
                        effect_checkpoint();observed=client.get(row['remote_id'])
                        labels=getattr(observed,'labels',{}) or {}
                        if (labels.get('sentra-scope')!=scope or labels.get('sentra-resource')!=row['metadata']['resource_token'] or
                                observed.public is not False or observed.network_block_all is not True):
                            raise ExecutorFailure('daytona_reconcile_ownership_or_network_mismatch')
                        metadata=dict(row['metadata'],sandbox_id=observed.id)
                        self.journal.update(row,remote_id=observed.id,metadata=metadata,state='OBSERVED')
                        return {'session_id':row['id'],'sandbox_id':observed.id,'creation_replayed':False,
                                'provider_reported_private':True,'attested_isolation':False,
                                'original_operation_requires_central_reconciliation':True}
                    sandbox=self._sandbox(client,b,row)
                    process=sandbox.process
                    if action.startswith('sandbox.'):
                        if row['metadata']['resource_kind']!='sandbox':raise ExecutorFailure('daytona_resource_kind_mismatch')
                        if action=='sandbox.read':pass
                        else:
                            if not row['metadata'].get('managed'):raise ExecutorFailure('cannot_administer_borrowed_sandbox')
                            effect_checkpoint();dispatched=True
                            if action=='sandbox.start':sandbox.start(timeout=b.timeout_seconds-5)
                            elif action=='sandbox.stop':sandbox.stop(timeout=b.timeout_seconds-5)
                            elif action=='sandbox.delete':client.delete(sandbox,timeout=b.timeout_seconds-5)
                        result={'session_id':row['id'],'requested_action':action,
                            'remote_state':'deleted' if action=='sandbox.delete' else str(getattr(sandbox.state,'value',sandbox.state))}
                        self.journal.update(row,state='DELETED' if action=='sandbox.delete' else 'OBSERVED')
                    elif action in {'pty.create','command.create'}:
                        if row['metadata']['resource_kind']!='sandbox':raise ExecutorFailure('daytona_parent_sandbox_required')
                        rid='sentra-'+hashlib.sha256((scope+a['_operation_id']).encode()).hexdigest()[:32]
                        child=self.journal.create(scope,'daytona',b.identity,rid,
                            dict(row['metadata'],resource_kind='pty' if action=='pty.create' else 'command',parent_id=row['id']),max_sessions=b.max_sessions)
                        effect_checkpoint();dispatched=True
                        if action=='pty.create':
                            handle=process.create_pty_session(id=rid,cwd=b.cwd,envs={},
                                pty_size=sdk.PtySize(rows=a.get('rows',24),cols=a.get('cols',80)))
                            if handle.session_id!=rid:raise ExecutorFailure('daytona_pty_id_mismatch',uncertain=True)
                            self.handles[child['id']]=handle
                        else:process.create_session(rid)
                        self.journal.update(child,state='ATTACHED')
                        result={'session_id':child['id'],'parent_session_id':row['id'],'remote_id':rid,'kind':child['metadata']['resource_kind']}
                    elif action.startswith('pty.'):
                        if row['metadata']['resource_kind']!='pty':raise ExecutorFailure('daytona_pty_required')
                        effect_checkpoint();info=process.get_pty_session_info(row['remote_id'])
                        if str(info.id)!=row['remote_id']:raise ExecutorFailure('daytona_pty_identity_mismatch')
                        handle=self.handles.get(row['id'])
                        if action=='pty.reattach':
                            if handle is not None:handle.disconnect()
                            effect_checkpoint();handle=process.connect_pty_session(row['remote_id'])
                            if handle.session_id!=row['remote_id']:raise ExecutorFailure('daytona_pty_identity_mismatch')
                            self.handles[row['id']]=handle
                            self.journal.update(row,state='ATTACHED',new_epoch=True)
                            self.journal.append(row,'gap',b'reconnected; Daytona PTY has no remote replay cursor')
                            result={'session_id':row['id'],'reattached':True,'remote_history_replayed':False}
                        elif action=='pty.cancel':
                            effect_checkpoint();dispatched=True;process.kill_pty_session(row['remote_id'])
                            if handle is not None:handle.disconnect()
                            self.handles.pop(row['id'],None);self.journal.update(row,state='TERMINATED')
                            result={'session_id':row['id'],'remote_pty_kill_requested':True}
                        elif action=='pty.disconnect':
                            if handle is not None:handle.disconnect()
                            self.handles.pop(row['id'],None);self.journal.update(row,state='DISCONNECTED')
                            result={'session_id':row['id'],'remote_pty_preserved':True}
                        else:
                            if handle is None or not handle.is_connected():raise ExecutorFailure('daytona_explicit_reattach_required')
                            effect_checkpoint()
                            if action=='pty.write':
                                dispatched=True;handle.send_input(a['text']);result={'input_bytes':len(a['text'].encode()),'input_logged':False}
                            elif action=='pty.resize':
                                dispatched=True;handle.resize(sdk.PtySize(rows=a['rows'],cols=a['cols']));result={'resized':True}
                            else:result=self._poll_pty(handle,row,b,a)
                    elif action.startswith('command.'):
                        if row['metadata']['resource_kind']!='command':raise ExecutorFailure('daytona_command_session_required')
                        effect_checkpoint();remote=process.get_session(row['remote_id'])
                        if str(remote.session_id)!=row['remote_id']:raise ExecutorFailure('daytona_command_session_identity_mismatch')
                        metadata=dict(row['metadata']);cmd_id=metadata.get('command_id')
                        if action=='command.execute':
                            # One durable command identity per session. Replacing
                            # it would orphan a running command and its cursor.
                            if cmd_id:raise ExecutorFailure('daytona_command_session_already_used_create_new_session')
                            effect_checkpoint();dispatched=True
                            response=process.execute_session_command(row['remote_id'],sdk.SessionExecuteRequest(
                                command=a['command'],run_async=True),timeout=int(b.connection.request_timeout_seconds))
                            metadata['command_id']=response.cmd_id;self.journal.update(row,metadata=metadata,state='RUNNING')
                            result={'command_id':response.cmd_id,'session_id':row['id']}
                        elif action=='command.input':
                            if not cmd_id:raise ExecutorFailure('daytona_no_bound_command')
                            effect_checkpoint();dispatched=True;process.send_session_command_input(row['remote_id'],cmd_id,a['text'])
                            result={'input_sent':True,'input_logged':False}
                        elif action=='command.cancel':
                            effect_checkpoint();dispatched=True;process.delete_session(row['remote_id'])
                            if row['id'] in self.log_streams:self.log_streams.pop(row['id'])[0].__exit__(None,None,None)
                            self.journal.update(row,state='TERMINATED');result={'remote_command_session_delete_requested':True}
                        else:
                            if not cmd_id:
                                return {'session_id':row['id'],'remote_session_exists':True,'bound_command':False,
                                        'command_replayed':False}
                            effect_checkpoint();command=process.get_session_command(row['remote_id'],cmd_id)
                            result=dict(self._poll_command(process,row,b,a,cmd_id),exit_code=command.exit_code)
                    else:raise ExecutorFailure('unsupported_daytona_session_action')
                if mutating:self.journal.complete_effect(a['_operation_id'],result)
                return result
            except ExecutorFailure as exc:
                evidence=dict(exc.evidence)
                if child is not None or row is not None:evidence['session_id']=(child or row)['id']
                raise ExecutorFailure(exc.code,uncertain=exc.uncertain or dispatched,evidence=evidence) from exc
            except Exception as exc:
                raise ExecutorFailure('daytona_transport_error',uncertain=dispatched,
                    evidence=dict({'exception_type':type(exc).__name__},
                        **({'session_id':(child or row)['id']} if child is not None or row is not None else {}))) from exc

    def shutdown(self):
        """Release local streams only; never delete borrowed cloud resources."""
        with self.lock:
            for handle in self.handles.values():
                try:handle.disconnect()
                except Exception:pass
            self.handles.clear()
            for manager,*_ in self.log_streams.values():
                try:manager.__exit__(None,None,None)
                except Exception:pass
            self.log_streams.clear()

    def _poll_pty(self,handle,row,b,a):
        # Public SDK wait(timeout) only checks time after data arrives; the pinned
        # implementation's underlying httpx-ws receive supports real idle timeout.
        from wsproto.events import TextMessage,BytesMessage,CloseConnection
        from httpx_ws import WebSocketDisconnect
        ws=getattr(handle,'_ws',None)
        if ws is None or not callable(getattr(ws,'receive',None)):
            raise ExecutorFailure('daytona_bounded_pty_receive_unsupported')
        deadline=time.monotonic()+a.get('wait_seconds',0.5);used=0
        while time.monotonic()<deadline and used<b.max_read_bytes:
            effect_checkpoint()
            try:event=ws.receive(timeout=min(.25,max(.001,deadline-time.monotonic())))
            except TimeoutError:continue
            except WebSocketDisconnect as exc:
                handle._handle_close(getattr(exc,'code',None),getattr(exc,'reason',None))
                self.journal.update(row,state='DISCONNECTED');break
            if isinstance(event,CloseConnection):
                handle._handle_close(event.code,event.reason)
                self.journal.update(row,state='DISCONNECTED');break
            if isinstance(event,TextMessage):
                try:control=json.loads(event.data)
                except ValueError:control=None
                if isinstance(control,dict) and control.get('type')=='control':
                    handle._handle_control_message(control)
                    self.journal.append(row,'control',json.dumps({k:control[k] for k in ('type','status','exit_code') if k in control}).encode());continue
                data=event.data.encode()
            elif isinstance(event,BytesMessage):data=bytes(event.data)
            else:continue
            if len(data)>b.max_read_bytes-used:
                # Received bytes remain durable instead of disappearing because
                # the UI requested a smaller page. Journal caps excess explicitly.
                if len(data)>self.journal.max_bytes:raise ExecutorFailure('daytona_pty_frame_limit')
            for start in range(0,len(data),b.max_read_bytes):self.journal.append(row,'pty',data[start:start+b.max_read_bytes])
            used+=len(data)
        return dict(self.journal.read(row,after=a.get('after',0),max_bytes=b.max_read_bytes),
                    exit_code=handle.exit_code,transport_cursor_supported=False)

    def _poll_command(self,process,row,b,a,cmd_id):
        import httpx_ws
        from wsproto.events import TextMessage,BytesMessage,CloseConnection
        from daytona._utils.stream import STDOUT_PREFIX,STDERR_PREFIX
        entry=self.log_streams.get(row['id'])
        if entry is None or entry[2]!=cmd_id:
            if entry is not None:entry[0].__exit__(None,None,None)
            effect_checkpoint()
            _,url,headers,*_=process._api_client._get_session_command_logs_serialize(
                session_id=row['remote_id'],command_id=cmd_id,follow=True,_request_auth=None,
                _content_type=None,_headers=None,_host_index=None)
            url=re.sub('^http','ws',url)
            manager=httpx_ws.connect_ws(url,process._http_client,headers=headers,max_message_size_bytes=b.max_read_bytes)
            effect_checkpoint();ws=manager.__enter__()
            entry=(manager,ws,cmd_id,{'buffer':bytearray(),'channel':None})
            self.log_streams[row['id']]=entry
            self.journal.append(row,'gap',b'command log websocket opened; remote replay/dedup cursor unavailable')
        manager,ws,_,state=entry
        deadline=time.monotonic()+a.get('wait_seconds',.5);used=0
        prefixes=(('stdout',STDOUT_PREFIX),('stderr',STDERR_PREFIX))
        tail=max(len(p) for _,p in prefixes)-1
        def append(channel,data):
            for start in range(0,len(data),b.max_read_bytes):self.journal.append(row,channel,data[start:start+b.max_read_bytes])
        while time.monotonic()<deadline and used<b.max_read_bytes:
            effect_checkpoint()
            try:event=ws.receive(timeout=min(.25,max(.001,deadline-time.monotonic())))
            except TimeoutError:continue
            except httpx_ws.WebSocketDisconnect:
                manager.__exit__(None,None,None);self.log_streams.pop(row['id'],None)
                if state['buffer'] and state['channel']:append(state['channel'],bytes(state['buffer']))
                break
            if isinstance(event,CloseConnection):
                manager.__exit__(None,None,None);self.log_streams.pop(row['id'],None)
                if state['buffer'] and state['channel']:append(state['channel'],bytes(state['buffer']))
                break
            if isinstance(event,TextMessage):data=event.data.encode()
            elif isinstance(event,BytesMessage):data=bytes(event.data)
            else:continue
            if len(data)>b.max_read_bytes:raise ExecutorFailure('daytona_command_stream_frame_limit')
            used+=len(data);state['buffer'].extend(data)
            while state['buffer']:
                positions=[(state['buffer'].find(prefix),kind,prefix) for kind,prefix in prefixes]
                positions=[p for p in positions if p[0]>=0]
                if positions:
                    index,kind,prefix=min(positions,key=lambda p:p[0]);emit=bytes(state['buffer'][:index])
                    del state['buffer'][:index+len(prefix)]
                    if emit:append(state['channel'] or 'untyped-command-wire',emit)
                    state['channel']=kind
                else:
                    safe=max(0,len(state['buffer'])-tail)
                    if safe:
                        emit=bytes(state['buffer'][:safe]);del state['buffer'][:safe]
                        append(state['channel'] or 'untyped-command-wire',emit)
                    break
        return dict(self.journal.read(row,after=a.get('after',0),max_bytes=b.max_read_bytes),
                    provider_streaming=True,remote_cursor_supported=False)


class DaytonaSessionExecutor(SessionExecutor):
    kind='daytona_session'
    def __init__(self,*,machine_id,owner_principal_id,bindings,journal,policy=None,backend=None):
        if len({b.capability_id for b in bindings})!=len(bindings):raise ValueError('duplicate_daytona_session_capability')
        super().__init__(machine_id=machine_id,owner_principal_id=owner_principal_id,
            bindings={b.capability_id:b for b in bindings},policy=policy)
        self.backend=backend or DaytonaSessionBackend(journal)

    def _validate(self,request,b):
        a=dict(request.arguments);action=a.get('action')
        if type(action) is not str or action not in b.actions:raise ValueError('daytona_session_action_denied')
        fields={'session.list':{'limit'},'pty.create':{'rows','cols'},'pty.read':{'after','wait_seconds'},'pty.write':{'text'},
            'pty.resize':{'rows','cols'},'command.execute':{'command'},'command.input':{'text'},
            'command.read':{'after','wait_seconds'},'sandbox.read':{'inventory_sandbox_id'},'evidence.export':{'output'}}.get(action,set())
        if set(a)-({'action','session_id'}|fields):raise ValueError('invalid_daytona_session_arguments')
        if action not in {'session.list','sandbox.create','sandbox.read'} and (type(a.get('session_id')) is not str or not a['session_id']):
            raise ValueError('bound_daytona_session_required')
        if action in {'session.list','sandbox.create'} and 'session_id' in a:raise ValueError('server_assigned_session_identity')
        if 'limit' in a and (type(a['limit']) is not int or not 1<=a['limit']<=100):raise ValueError('bounded_session_list_required')
        if action=='sandbox.read' and ('session_id' in a)==('inventory_sandbox_id' in a):raise ValueError('one_sandbox_identity_required')
        if 'inventory_sandbox_id' in a and a['inventory_sandbox_id'] not in b.existing_sandbox_ids:raise ValueError('sandbox_outside_inventory')
        if action in {'pty.write','command.input'} and (not b.allow_pty_input or type(a.get('text')) is not str or len(a['text'].encode())>8192):
            raise ValueError('daytona_stdin_not_authorized')
        if action=='command.execute' and a.get('command') not in b.allowed_commands:raise ValueError('command_not_allowlisted')
        for k in ('rows','cols'):
            if k in a and (type(a[k]) is not int or not 1<=a[k]<=300):raise ValueError('invalid_pty_size')
        if action=='pty.resize' and not {'rows','cols'}<=set(a):raise ValueError('pty_size_required')
        if 'after' in a and (type(a['after']) is not int or a['after']<0):raise ValueError('invalid_cursor')
        if 'wait_seconds' in a and (type(a['wait_seconds']) not in (int,float) or not 0<a['wait_seconds']<=3):raise ValueError('bounded_read_required')
        if action=='evidence.export':
            path=b.paths.resolve(a.get('output'),write=True)
            if path.suffix.lower()!='.json':raise ValueError('json_evidence_required')
            a['output']=str(path)
        a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id
        return json.loads(json.dumps(a,allow_nan=False))

    def _run(self,b,a):return self.backend.run(b,a)


def declare_daytona_session_machine(*,machine_id,owner_principal_id,bindings,journal,policy,backend=None):
    executor=DaytonaSessionExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,
        bindings=bindings,journal=journal,policy=policy,backend=backend)
    return declare_session_machine(executor,bindings,'Configured Daytona lifecycle and persistent sessions')
