"""Real guacd TCP/TLS protocol client, scoped control and read-only replay.

The upstream wire protocol is preserved. This module is not a remote-machine
attestation service and never interprets guacd ready as authenticated guest ID.
"""
from __future__ import annotations
import codecs
import hashlib
import json
import math
import re
import socket
import ssl
import threading
import time
from collections import deque
from dataclasses import dataclass,field

from .identity_sessions import SessionExecutor,SessionScope,SessionJournal,declare_session_machine
from .rpa import ExecutorFailure,effect_checkpoint,AuthorizedPaths,atomic_output

GUAC_ACTIONS=frozenset({'session.list','open','reattach','read','write','close','recording.export','recording.read'})


def encode_instruction(opcode,*arguments):
    values=(opcode,)+arguments
    if any(type(v) is not str or '\x00' in v for v in values):raise ExecutorFailure('invalid_guacamole_instruction')
    return (','.join(str(len(v))+'.'+v for v in values)+';').encode('utf-8')


class GuacamoleParser:
    """Incremental UTF-8/codepoint parser matching libguac/Guacamole.Parser."""
    def __init__(self,*,max_bytes=1024*1024,max_elements=64):
        self.decoder=codecs.getincrementaldecoder('utf-8')('strict')
        self.buffer='';self.elements=[];self.max_bytes=max_bytes;self.max_elements=max_elements;self.instruction_bytes=0

    def feed(self,data):
        if len(data)>self.max_bytes:raise ExecutorFailure('guacamole_packet_limit')
        self.buffer+=self.decoder.decode(data)
        if len(self.buffer.encode())+self.instruction_bytes>self.max_bytes:raise ExecutorFailure('guacamole_instruction_limit')
        instructions=[]
        while True:
            dot=self.buffer.find('.')
            if dot<0:
                if len(self.buffer)>10:raise ExecutorFailure('guacamole_invalid_length')
                break
            prefix=self.buffer[:dot]
            if not prefix or len(prefix)>10 or not re.fullmatch('[0-9]+',prefix):raise ExecutorFailure('guacamole_invalid_length')
            length=int(prefix);end=dot+1+length
            if length>self.max_bytes:raise ExecutorFailure('guacamole_element_limit')
            if len(self.buffer)<=end:break
            separator=self.buffer[end]
            if separator not in {',',';'}:raise ExecutorFailure('guacamole_invalid_separator')
            value=self.buffer[dot+1:end]
            self.instruction_bytes+=len(self.buffer[:end+1].encode())
            self.buffer=self.buffer[end+1:];self.elements.append(value)
            if len(self.elements)>self.max_elements:raise ExecutorFailure('guacamole_argument_limit')
            if separator==';':
                instructions.append(tuple(self.elements));self.elements=[];self.instruction_bytes=0
        return instructions


@dataclass(frozen=True)
class GuacamoleBinding:
    capability_id:str
    host:str
    port:int
    protocol:str
    parameters:tuple[tuple[str,str],...]
    paths:AuthorizedPaths
    secrets:object=field(default=None,repr=False,compare=False)
    tls:bool=True
    ca_file:str|None=None
    server_certificate_sha256:str|None=None
    supported_versions:tuple[str,...]=('VERSION_1_5_0','VERSION_1_6_0')
    allowed_input:tuple[str,...]=()  # key,mouse,touch; empty means view-only
    actions:tuple[str,...]=tuple(sorted(GUAC_ACTIONS))
    timeout_seconds:float=15
    io_timeout_seconds:float=3
    max_instruction_bytes:int=1024*1024
    max_read_bytes:int=256*1024
    width:int=1280
    height:int=800

    def __post_init__(self):
        if (not self.capability_id or not self.host or type(self.port) is not int or not 1<=self.port<=65535 or self.protocol not in {'rdp','vnc','ssh'} or
            not 1<=self.io_timeout_seconds<self.timeout_seconds<=60 or not set(self.actions)<=GUAC_ACTIONS or
            not set(self.allowed_input)<={'key','mouse','touch'} or not 1<=self.max_read_bytes<=1024*1024 or
            not 1024<=self.max_instruction_bytes<=4*1024*1024 or not 1<=self.width<=8192 or not 1<=self.height<=8192 or
            self.tls and not re.fullmatch('[0-9a-f]{64}',self.server_certificate_sha256 or '') or
            not self.tls and self.host not in {'127.0.0.1','::1'}):
            raise ValueError('invalid_explicit_guacamole_transport')
        params=dict(self.parameters)
        if len(params)!=len(self.parameters) or not params.get('hostname'):
            raise ValueError('guacamole_configured_target_required')
        if any(k in params for k in ('password','private-key','passphrase')):
            raise ValueError('guacamole_secret_callback_required')
        if not self.supported_versions or any(not re.fullmatch('VERSION_[0-9]+_[0-9]+_[0-9]+',v) for v in self.supported_versions):
            raise ValueError('invalid_guacamole_protocol_versions')

    @property
    def identity(self):
        # Changing route/transport/policy invalidates persisted sessions.
        return hashlib.sha256(json.dumps([self.capability_id,self.host,self.port,self.protocol,
            self.parameters,self.tls,self.ca_file,self.server_certificate_sha256,self.allowed_input,
            self.supported_versions,self.actions],sort_keys=True).encode()).hexdigest()


class _GuacdConnection:
    def __init__(self,sock,b):
        self.sock=sock;self.binding=b;self.parser=GuacamoleParser(max_bytes=b.max_instruction_bytes)
        self.pending=deque();self.closed=False

    def send(self,opcode,*args):
        effect_checkpoint();self.sock.settimeout(self.binding.io_timeout_seconds)
        data=encode_instruction(opcode,*args)
        if len(data)>self.binding.max_instruction_bytes:raise ExecutorFailure('guacamole_write_limit')
        self.sock.sendall(data)

    def receive(self,timeout=None):
        if self.pending:return self.pending.popleft()
        deadline=time.monotonic()+(timeout or self.binding.io_timeout_seconds)
        while not self.pending:
            effect_checkpoint()
            remaining=deadline-time.monotonic()
            if remaining<=0:raise socket.timeout()
            self.sock.settimeout(remaining)
            data=self.sock.recv(min(16384,self.binding.max_instruction_bytes))
            if not data:self.closed=True;raise ExecutorFailure('guacamole_tunnel_disconnected')
            self.pending.extend(self.parser.feed(data))
        return self.pending.popleft()

    def close(self):
        if not self.closed:
            try:self.send('disconnect')
            except Exception:pass
        self.closed=True;self.sock.close()


class GuacamoleBackend:
    def __init__(self,journal:SessionJournal):
        self.journal=journal;self.connections={};self.lock=threading.RLock()

    def shutdown(self):
        with self.lock:
            for connection in self.connections.values():connection.close()
            self.connections.clear()

    def _connect(self,b,select):
        effect_checkpoint();sock=socket.create_connection((b.host,b.port),timeout=b.io_timeout_seconds)
        try:
            if b.tls:
                effect_checkpoint();context=ssl.create_default_context(cafile=b.ca_file)
                sock=context.wrap_socket(sock,server_hostname=b.host)
                if hashlib.sha256(sock.getpeercert(binary_form=True)).hexdigest()!=b.server_certificate_sha256:
                    raise ExecutorFailure('guacamole_daemon_certificate_pin_mismatch')
            conn=_GuacdConnection(sock,b);conn.send('select',select)
            deadline=time.monotonic()+b.timeout_seconds-2
            first=conn.receive()
            if not first or first[0]!='args' or len(first)<2:raise ExecutorFailure('guacamole_args_handshake_required')
            names=list(first[1:]);advertised=names[0]
            if not re.fullmatch('VERSION_[0-9]+_[0-9]+_[0-9]+',advertised):
                raise ExecutorFailure('guacamole_version_negotiation_required')
            def version(v):return tuple(int(p) for p in v.split('_')[1:])
            common=[v for v in b.supported_versions if version(v)<=version(advertised)]
            if not common:raise ExecutorFailure('guacamole_version_incompatible')
            selected=max(common,key=version)
            values=dict(b.parameters)
            if b.secrets is not None:
                secrets=b.secrets()
                if not isinstance(secrets,dict) or set(secrets)-{'password','private-key','passphrase','username'}:
                    raise ExecutorFailure('invalid_guacamole_secret_provider')
                values.update(secrets)
            # Disable channels rather than trusting the viewer to omit controls.
            values.update({'read-only':'false' if b.allowed_input else 'true','disable-upload':'true','disable-download':'true',
                'sftp-disable-upload':'true','sftp-disable-download':'true','enable-drive':'false',
                'enable-printing':'false','disable-copy':'true','disable-paste':'true','enable-audio':'false'})
            if not b.allowed_input and 'read-only' not in names:
                raise ExecutorFailure('guacamole_plugin_has_no_view_only_parameter')
            conn.send('size',str(b.width),str(b.height),'96');conn.send('audio');conn.send('video')
            conn.send('image','image/png','image/jpeg');conn.send('timezone','UTC')
            conn.send('connect',selected,*(str(values.get(name,'')) for name in names[1:]))
            while time.monotonic()<deadline:
                instruction=conn.receive()
                if instruction[0]=='error':raise ExecutorFailure('guacamole_remote_handshake_error')
                if instruction[0]=='ready':
                    if len(instruction)!=2 or not instruction[1].startswith('$') or len(instruction[1])>128:
                        raise ExecutorFailure('guacamole_invalid_connection_identity')
                    return conn,instruction[1],selected
            raise ExecutorFailure('guacamole_handshake_timeout')
        except Exception:
            sock.close();raise

    def run(self,b,a):
        with self.lock:
            action,scope=a['action'],a['_scope']
            if action=='session.list':return self.journal.list(scope,'guacamole',b.identity,limit=a.get('limit',64))
            if action=='open':
                prior=self.journal.reserve_effect(a['_operation_id'],scope,a)
                if prior is not None:return prior
                row=self.journal.create(scope,'guacamole',b.identity,'pending',{'protocol':b.protocol},state='CONNECTING')
                try:
                    conn,rid,version=self._connect(b,b.protocol)
                    self.connections[row['id']]=conn
                    self.journal.update(row,remote_id=rid,state='CONNECTED',metadata={'protocol':b.protocol,'version':version,
                        'transport_certificate_pinned':b.tls,'guest_identity_attested':False,'view_only':not bool(b.allowed_input)})
                    result={'session_id':row['id'],'protocol_version':version,'view_only':not bool(b.allowed_input),
                        'daemon_certificate_pinned':b.tls,'guest_identity_attested':False}
                    self.journal.complete_effect(a['_operation_id'],result);return result
                except Exception as exc:
                    if row['id'] in self.connections:self.connections.pop(row['id']).close()
                    raise ExecutorFailure(exc.code if isinstance(exc,ExecutorFailure) else 'guacamole_connect_error',
                        uncertain=True,evidence={'session_id':row['id']}) from exc
            row=self.journal.get(a['session_id'],scope,'guacamole',b.identity)
            if action=='recording.export':
                return {'artifact':self.journal.export(row,b.paths,a['output'])}
            if action=='recording.read':
                # Offline data only. Never obtains a live socket or sends input.
                result=self.journal.read(row,after=a.get('after',0),max_bytes=b.max_read_bytes)
                return dict(result,playback_only=True,transport_accessed=False)
            conn=self.connections.get(row['id'])
            if action=='reattach':
                if row['state']=='CLOSED' or not row['remote_id'].startswith('$'):raise ExecutorFailure('closed_or_unresolved_guacamole_session_cannot_reattach')
                if conn is not None:conn.close()
                effect_checkpoint();conn,rid,version=self._connect(b,row['remote_id'])
                if rid!=row['remote_id']:conn.close();raise ExecutorFailure('guacamole_reattach_identity_changed')
                self.connections[row['id']]=conn;self.journal.update(row,state='CONNECTED',new_epoch=True)
                self.journal.append(row,'gap',b'tunnel reconnected; no server replay cursor guaranteed')
                return {'session_id':row['id'],'reattached':True,'remote_history_replayed':False}
            if action=='close':
                if conn is not None:effect_checkpoint();conn.close();self.connections.pop(row['id'],None)
                self.journal.update(row,state='CLOSED');return {'session_id':row['id'],'tunnel_closed':True,'remote_os_session_deleted':False}
            if conn is None or conn.closed:raise ExecutorFailure('guacamole_explicit_reattach_required')
            if action=='write':
                prior=self.journal.reserve_effect(a['_operation_id'],scope,a)
                if prior is not None:return prior
                opcode=a['opcode'];args=a['args']
                if opcode not in {'sync','ack','nop'} and opcode not in b.allowed_input:
                    raise ExecutorFailure('guacamole_input_channel_denied')
                effect_checkpoint();conn.send(opcode,*args)
                result={'written':True,'input_recorded':False};self.journal.complete_effect(a['_operation_id'],result)
                return result
            deadline=time.monotonic()+a.get('wait_seconds',.5);used=0;count=0
            try:
                while time.monotonic()<deadline and used<b.max_read_bytes and count<100:
                    effect_checkpoint()
                    try:instruction=conn.receive(timeout=min(.2,max(.001,deadline-time.monotonic())))
                    except socket.timeout:continue
                    if instruction[0] in {'clipboard','file','filesystem','audio','video','pipe'}:
                        conn.close();self.connections.pop(row['id'],None)
                        raise ExecutorFailure('guacamole_server_sent_disabled_channel')
                    raw=encode_instruction(*instruction)
                    for start in range(0,len(raw),b.max_read_bytes):
                        self.journal.append(row,'guacamole',raw[start:start+b.max_read_bytes])
                    used+=len(raw);count+=1
                    if instruction[0]=='sync':
                        conn.send('sync',*instruction[1:])
                    if instruction[0]=='disconnect':
                        conn.close();self.journal.update(row,state='DISCONNECTED');break
                    if instruction[0]=='error':
                        self.journal.update(row,state='REMOTE_ERROR')
                        raise ExecutorFailure('guacamole_guest_or_transport_error',evidence={'session_id':row['id'],
                            'guest_identity_attested':False,'message_recorded_in_scoped_journal':True})
                    # Clipboard/filesystem/audio channel payloads are never passed
                    # to an implicitly authorized frontend channel.
            except ExecutorFailure as exc:
                # A malformed stream or authorization failure cannot leave an
                # owned input channel open for a later unsuspecting viewer.
                conn.close();self.connections.pop(row['id'],None)
                raise
            except Exception:
                conn.close();self.connections.pop(row['id'],None);raise
            return self.journal.read(row,after=a.get('after',0),max_bytes=b.max_read_bytes)


class GuacamoleExecutor(SessionExecutor):
    kind='guacamole'
    def __init__(self,*,machine_id,owner_principal_id,bindings,journal,policy=None,backend=None):
        if len({b.capability_id for b in bindings})!=len(bindings):raise ValueError('duplicate_guacamole_capability')
        super().__init__(machine_id=machine_id,owner_principal_id=owner_principal_id,
                         bindings={b.capability_id:b for b in bindings},policy=policy)
        self.backend=backend or GuacamoleBackend(journal)

    def _validate(self,request,b):
        a=dict(request.arguments);action=a.get('action')
        if type(action) is not str or action not in b.actions:raise ValueError('guacamole_action_denied')
        fields={'session.list':{'limit'},'read':{'after','wait_seconds'},'recording.read':{'after'},'recording.export':{'output'},
                'write':{'opcode','args'}}.get(action,set())
        if set(a)-({'action'}|fields|({'session_id'} if action not in {'open','session.list'} else set())):raise ValueError('invalid_guacamole_arguments')
        if action not in {'open','session.list'} and (type(a.get('session_id')) is not str or not a['session_id']):raise ValueError('bound_guacamole_session_required')
        if 'limit' in a and (type(a['limit']) is not int or not 1<=a['limit']<=100):raise ValueError('bounded_session_list_required')
        if 'after' in a and (type(a['after']) is not int or a['after']<0):raise ValueError('invalid_cursor')
        if 'wait_seconds' in a and (type(a['wait_seconds']) not in (int,float) or not 0<a['wait_seconds']<=3):raise ValueError('bounded_tunnel_read_required')
        if action=='write':
            opcode,args=a.get('opcode'),a.get('args')
            if opcode not in set(b.allowed_input)|{'sync','ack','nop'} or not isinstance(args,list) or len(args)>16 or any(type(v) is not str or len(v)>1024 for v in args):
                raise ValueError('guacamole_control_channel_denied')
            expected={'key':2,'mouse':3,'touch':7,'sync':1,'ack':3,'nop':0}
            if opcode in expected and len(args)!=expected[opcode]:raise ValueError('invalid_guacamole_control_arity')
            if opcode in {'key','mouse','sync'} and any(not re.fullmatch('[0-9]+',v) for v in args):raise ValueError('numeric_guacamole_input_required')
            if opcode=='key' and (int(args[0])>0xffffffff or args[1] not in {'0','1'}):raise ValueError('invalid_guacamole_key')
            if opcode=='mouse' and (int(args[0])>8192 or int(args[1])>8192 or int(args[2])>31):raise ValueError('invalid_guacamole_mouse')
            if opcode=='touch':
                try:numbers=[float(v) for v in args]
                except ValueError as exc:raise ValueError('invalid_guacamole_touch') from exc
                if any(not math.isfinite(v) for v in numbers) or not 0<=numbers[-1]<=1 or any(v<0 or v>8192 for v in numbers[:5]):
                    raise ValueError('invalid_guacamole_touch')
        if action=='recording.export':
            path=b.paths.resolve(a.get('output'),write=True)
            if path.suffix.lower()!='.json':raise ValueError('json_recording_required')
            a['output']=str(path)
        a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id
        return json.loads(json.dumps(a,allow_nan=False))

    def _run(self,b,a):return self.backend.run(b,a)


def declare_guacamole_machine(*,machine_id,owner_principal_id,bindings,journal,policy,backend=None):
    executor=GuacamoleExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,
                              bindings=bindings,journal=journal,policy=policy,backend=backend)
    return declare_session_machine(executor,bindings,'Guacd scoped tunnel, channel policy and offline recording')
