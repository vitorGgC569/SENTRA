"""Actual Guacamole WebSocket tunnel; every call goes through a host dispatcher.

No direct guacd socket path, no policy grants, no proprietary remote wire.
Host issues short-lived single-connection tickets AFTER central authorization.
"""
from __future__ import annotations
import base64
import codecs
import secrets
import threading
import time
from urllib.parse import urlsplit
from dataclasses import dataclass
from .remote_guacamole import GuacamoleParser,encode_instruction
from .rpa import ExecutorFailure


@dataclass(frozen=True)
class TunnelTicket:
    session_id:str
    machine_id:str
    principal_id:str
    capability_id:str
    work_item_id:str
    run_id:str
    expires_monotonic:float


class GuacamoleTunnelServer:
    def __init__(self,*,dispatch,port=8766,max_connection_seconds=300,allowed_origins=()):
        if not callable(dispatch) or type(port) is not int or not 1<=port<=65535 or not 1<=max_connection_seconds<=3600:
            raise ValueError('configured_central_tunnel_dispatch_required')
        self.dispatch=dispatch;self.port=port;self.max_seconds=max_connection_seconds
        if not isinstance(allowed_origins,tuple) or any(not isinstance(v,str) or urlsplit(v).scheme not in {'http','https'} or
            not urlsplit(v).netloc or urlsplit(v).path not in {'','/'} or urlsplit(v).query or urlsplit(v).fragment for v in allowed_origins):
            raise ValueError('explicit_guacamole_viewer_origins_required')
        self.allowed_origins=allowed_origins
        self.tickets={};self.lock=threading.Lock()

    def issue(self,*,session_id,machine_id,principal_id,capability_id,work_item_id,run_id,lifetime_seconds=30):
        """Trusted host only. This ticket never substitutes for dispatch policy."""
        if not all(type(s) is str and s for s in (session_id,machine_id,principal_id,capability_id,work_item_id,run_id)) or not 1<=lifetime_seconds<=60:
            raise ValueError('invalid_scoped_tunnel_ticket')
        token=secrets.token_hex(32)
        ticket=TunnelTicket(session_id,machine_id,principal_id,capability_id,work_item_id,run_id,time.monotonic()+lifetime_seconds)
        with self.lock:
            self.tickets={k:v for k,v in self.tickets.items() if v.expires_monotonic>time.monotonic()}
            if len(self.tickets)>=128:raise ExecutorFailure('tunnel_ticket_limit')
            self.tickets[token]=ticket
        return {'url':f'ws://127.0.0.1:{self.port}/tunnel/{token}','expires_in_seconds':lifetime_seconds,
                'scope':'principal/machine/capability/work_item/run/session','single_connection':True}

    def _call(self,ticket,**arguments):
        # dispatch MUST marshal onto the host's central event loop, create a
        # unique OperationRequest and revalidate the live Run/WorkItem/grant.
        result=self.dispatch(ticket,dict(arguments,session_id=ticket.session_id))
        if getattr(result,'state',None)!='SUCCEEDED':raise ExecutorFailure('central_tunnel_dispatch_denied_or_uncertain')
        return result.evidence

    def handle(self,websocket):
        parsed=urlsplit(websocket.request.path);path=parsed.path
        prefix='/tunnel/'
        if not path.startswith(prefix) or parsed.query or parsed.fragment:
            websocket.close(code=1008,reason='invalid tunnel');return
        with self.lock:ticket=self.tickets.pop(path[len(prefix):],None)
        if ticket is None or ticket.expires_monotonic<=time.monotonic():
            websocket.close(code=1008,reason='expired ticket');return
        parser=GuacamoleParser(max_bytes=65536);decoder=codecs.getincrementaldecoder('utf-8')('strict')
        cursor=0;deadline=time.monotonic()+self.max_seconds
        try:
            # Guacamole.WebSocketTunnel expects a UUID in an empty-opcode
            # internal instruction. This UUID is ours, never a remote ID.
            websocket.send(encode_instruction('',ticket.session_id).decode())
            while time.monotonic()<deadline:
                data=self._call(ticket,action='read',after=cursor,wait_seconds=.15)
                if data.get('gap'):raise ExecutorFailure('tunnel_cursor_gap_requires_new_view')
                for event in data.get('events',[]):
                    if event['channel']=='gap':raise ExecutorFailure('tunnel_reconnect_requires_new_view')
                    if event['channel']=='guacamole':
                        text=decoder.decode(base64.b64decode(event['data_base64'],validate=True))
                        if text:websocket.send(text)
                    cursor=event['sequence']
                try:incoming=websocket.recv(timeout=.01)
                except TimeoutError:continue
                if not isinstance(incoming,str) or len(incoming.encode())>65536:
                    raise ExecutorFailure('guacamole_frontend_packet_limit')
                instructions=parser.feed(incoming.encode())
                if len(instructions)>256:raise ExecutorFailure('guacamole_frontend_instruction_limit')
                for instruction in instructions:
                    if time.monotonic()>=deadline:raise ExecutorFailure('guacamole_tunnel_session_deadline')
                    if instruction[0]=='':
                        # Upstream internal websocket keepalive; never guacd input.
                        websocket.send(encode_instruction('',*instruction[1:]).decode());continue
                    self._call(ticket,action='write',opcode=instruction[0],args=list(instruction[1:]))
        except Exception:
            try:websocket.close(code=1008,reason='session no longer authorized or connected')
            except Exception:pass
        finally:
            # Central dispatch may refuse after revocation. The socket-facing
            # provider also closes on its own policy/checkpoint failure.
            try:self._call(ticket,action='close')
            except Exception:pass

    def serve(self):
        """Blocking explicit host startup; no default public listener."""
        try:from websockets.sync.server import serve
        except ImportError as exc:raise ExecutorFailure('websockets_sync_provider_missing') from exc
        if not self.allowed_origins:raise ExecutorFailure('guacamole_web_origin_configuration_required')
        return serve(self.handle,'127.0.0.1',self.port,subprotocols=['guacamole'],
                     origins=list(self.allowed_origins),max_size=65536,max_queue=16,open_timeout=5,close_timeout=3)
