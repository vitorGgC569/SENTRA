"""Prepared scope/journal/protocol tests. TCP fixture is NOT a guacd/desktop proof."""
import asyncio
import json
import os
import base64
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from sentra_executors.identity_sessions import SessionJournal,SessionScope
from sentra_executors.remote_guacamole import GuacamoleParser,encode_instruction,GuacamoleBinding,declare_guacamole_machine
from sentra_executors.remote_guacamole_tunnel import GuacamoleTunnelServer
from sentra_executors.rpa import AuthorizedPaths,ExecutorFailure
from sentra_runtime.contracts import OperationRequest,PolicyDecision


class JournalOwnershipContract(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve();self.paths=AuthorizedPaths((str(self.root),),(str(self.root),))
        self.journal=SessionJournal(str(self.root/'provider.sqlite'),self.paths,max_bytes=1024)

    def test_work_item_scope_cannot_be_changed_on_reattach(self):
        one=SessionScope('m','p','c','work-one').key;two=SessionScope('m','p','c','work-two').key
        row=self.journal.create(one,'guacamole','binding','$server-id',{})
        with self.assertRaisesRegex(ExecutorFailure,'scope_mismatch'):self.journal.get(row['id'],two,'guacamole','binding')
        with self.assertRaisesRegex(ExecutorFailure,'scope_mismatch'):self.journal.get(row['id'],one,'guacamole','new-binding')

    def test_restart_preserves_cursor_and_reports_eviction_gap(self):
        row=self.journal.create('scope','provider','binding','remote',{})
        self.journal.append(row,'stdout',b'A'*700);self.journal.append(row,'stdout',b'B'*700)
        restarted=SessionJournal(str(self.root/'provider.sqlite'),self.paths,max_bytes=1024)
        result=restarted.read(row,after=0,max_bytes=1024)
        self.assertTrue(result['gap']);self.assertEqual(result['first_sequence'],2);self.assertEqual(result['cursor'],2)

    def test_uncertain_mutation_is_not_replayed_after_restart(self):
        self.assertIsNone(self.journal.reserve_effect('op','scope',{'action':'write','text':'private'}))
        restarted=SessionJournal(str(self.root/'provider.sqlite'),self.paths,max_bytes=1024)
        with self.assertRaisesRegex(ExecutorFailure,'requires_reconciliation'):
            restarted.reserve_effect('op','scope',{'action':'write','text':'private'})

    def test_parser_uses_codepoints_and_handles_fragmented_utf8(self):
        raw=encode_instruction('name','ação 😀');parser=GuacamoleParser()
        instructions=[]
        for value in raw:instructions.extend(parser.feed(bytes([value])))
        self.assertEqual(instructions,[('name','ação 😀')])

    def test_parser_refuses_malformed_or_oversized_wire(self):
        for raw in (b'x.nop;',b'10000000000.blob;',b'3.nop!'):
            with self.subTest(raw=raw),self.assertRaises(ExecutorFailure):GuacamoleParser(max_bytes=1024).feed(raw)

    def test_ticket_is_single_connection_scoped_and_no_server_starts_on_issue(self):
        calls=[]
        server=GuacamoleTunnelServer(dispatch=lambda *args:calls.append(args),port=8766)
        ticket=server.issue(session_id='sid',machine_id='m',principal_id='p',capability_id='c',work_item_id='w',run_id='r')
        self.assertTrue(ticket['single_connection']);self.assertTrue(ticket['url'].startswith('ws://127.0.0.1:8766/tunnel/'))
        self.assertEqual(calls,[])


class GuacdWireFixtureAcceptance(unittest.TestCase):
    """Real socket, synthetic protocol endpoint: proves framing/gate only."""
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve();self.paths=AuthorizedPaths((str(self.root),),(str(self.root),))
        self.journal=SessionJournal(str(self.root/'guacamole.sqlite'),self.paths)
        self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.listener.listen(1)
        self.addCleanup(self.listener.close);self.written=[];self.server_errors=[]
        def fixture():
            try:
                sock,_=self.listener.accept();sock.settimeout(5);parser=GuacamoleParser();pending=[]
                def read():
                    while not pending:
                        data=sock.recv(16384)
                        if not data:raise EOFError()
                        pending.extend(parser.feed(data))
                    return pending.pop(0)
                self.assertEqual(read(),('select','vnc'))
                sock.sendall(encode_instruction('args','VERSION_1_6_0','hostname','port','read-only'))
                while True:
                    instruction=read();self.written.append(instruction)
                    if instruction[0]=='connect':
                        self.assertEqual(instruction,('connect','VERSION_1_6_0','127.0.0.1','5900','true'));break
                sock.sendall(encode_instruction('ready','$fixture-owned')+encode_instruction('size','0','640','480')+
                             encode_instruction('sync','1000'))
                while True:
                    instruction=read();self.written.append(instruction)
                    if instruction[0]=='disconnect':break
                sock.close()
            except EOFError:pass
            except Exception as exc:self.server_errors.append(exc)
        self.thread=threading.Thread(target=fixture,daemon=True);self.thread.start()
        binding=GuacamoleBinding('view','127.0.0.1',self.listener.getsockname()[1],'vnc',
            (('hostname','127.0.0.1'),('port','5900')),self.paths,tls=False)
        self.declaration=declare_guacamole_machine(machine_id='guac-fixture',owner_principal_id='p',
            bindings=(binding,),journal=self.journal,policy=lambda r:PolicyDecision(True,'explicit wire fixture'))
        self.addCleanup(self.declaration.adapter.backend.shutdown);self.counter=0

    def invoke(self,**args):
        self.counter+=1
        return asyncio.run(self.declaration.adapter.start(OperationRequest('g'+str(self.counter),'p','guac-fixture',
            'view','work','g-key'+str(self.counter),args)))

    def test_handshake_view_only_recording_and_offline_replay_data(self):
        opened=self.invoke(action='open');self.assertEqual(opened.state,'SUCCEEDED',opened.error)
        sid=opened.evidence['session_id']
        self.assertFalse(opened.evidence['guest_identity_attested'])
        received=self.invoke(action='read',session_id=sid,wait_seconds=.1)
        self.assertEqual(received.state,'SUCCEEDED',received.error);self.assertTrue(received.evidence['events'])
        denied=self.invoke(action='write',session_id=sid,opcode='key',args=['65','1'])
        self.assertEqual(denied.state,'FAILED')
        output=self.root/'recording.json';exported=self.invoke(action='recording.export',session_id=sid,output=str(output))
        self.assertEqual(exported.state,'SUCCEEDED',exported.error)
        self.assertFalse(json.loads(output.read_text())['completeness_asserted'])
        closed=self.invoke(action='close',session_id=sid);self.assertEqual(closed.state,'SUCCEEDED')
        playback=self.invoke(action='recording.read',session_id=sid)
        self.assertEqual(playback.state,'SUCCEEDED');self.assertTrue(playback.evidence['playback_only'])
        self.assertFalse(playback.evidence['transport_accessed'])
        self.thread.join(timeout=2);self.assertEqual(self.server_errors,[])
        self.assertFalse(any(i[0]=='key' for i in self.written))


@unittest.skipUnless(os.environ.get('SENTRA_GUACD_ACCEPTANCE')=='1','REAL TLS guacd/desktop acceptance staged, disabled')
class RealGuacdDesktopAcceptance(unittest.TestCase):
    def test_tls_handshake_actual_display_stream_recording_and_scope(self):
        required=('SENTRA_GUACD_HOST','SENTRA_GUACD_CERT_SHA256','SENTRA_GUACD_CA_FILE',
                  'SENTRA_GUACD_PROTOCOL','SENTRA_GUACD_PARAMETERS_JSON')
        for key in required:self.assertTrue(os.environ.get(key),'required real guacd configuration missing: '+key)
        parameters=json.loads(os.environ[required[4]])
        self.assertIsInstance(parameters,dict)
        # Credentials are supplied separately; never exported into the recording.
        def credentials():return json.loads(os.environ.get('SENTRA_GUACD_SECRETS_JSON','{}'))
        with tempfile.TemporaryDirectory(prefix='sentra-guacd-real-') as directory:
            root=Path(directory).resolve();paths=AuthorizedPaths((str(root),),(str(root),))
            binding=GuacamoleBinding('view',os.environ[required[0]],int(os.environ.get('SENTRA_GUACD_PORT','4822')),
                os.environ[required[3]],tuple(parameters.items()),paths,secrets=credentials,
                ca_file=os.environ[required[2]],server_certificate_sha256=os.environ[required[1]])
            declaration=declare_guacamole_machine(machine_id='live-guacd',owner_principal_id='acceptance',bindings=(binding,),
                journal=SessionJournal(str(root/'guacd.sqlite'),paths),policy=lambda r:PolicyDecision(True,'explicit actual TLS guacd lab'))
            count=0
            def invoke(work='work',**arguments):
                nonlocal count;count+=1
                return asyncio.run(declaration.adapter.start(OperationRequest('guacd'+str(count),'acceptance','live-guacd',
                    'view',work,'guacd-key'+str(count),arguments)))
            try:
                opened=invoke(action='open');self.assertEqual(opened.state,'SUCCEEDED',(opened.error,opened.evidence))
                self.assertTrue(opened.evidence['daemon_certificate_pinned']);self.assertFalse(opened.evidence['guest_identity_attested'])
                sid=opened.evidence['session_id'];cursor=0;parser=GuacamoleParser();instructions=[]
                for _ in range(30):
                    result=invoke(action='read',session_id=sid,after=cursor,wait_seconds=.5)
                    self.assertEqual(result.state,'SUCCEEDED',(result.error,result.evidence))
                    for event in result.evidence['events']:
                        if event['channel']=='guacamole':instructions.extend(parser.feed(base64.b64decode(event['data_base64'])))
                    cursor=result.evidence['cursor']
                    if any(i[0]=='size' for i in instructions) and any(i[0] in {'img','png','jpeg','rect'} for i in instructions):break
                self.assertTrue(any(i[0]=='size' for i in instructions),'daemon ready alone is not desktop display evidence')
                self.assertTrue(any(i[0] in {'img','png','jpeg','rect'} for i in instructions),'no actual display instructions received')
                denied=invoke(work='foreign',action='read',session_id=sid);self.assertNotEqual(denied.state,'SUCCEEDED')
                denied=invoke(action='write',session_id=sid,opcode='key',args=['65','1']);self.assertNotEqual(denied.state,'SUCCEEDED')
                output=root/'desktop-recording.json'
                exported=invoke(action='recording.export',session_id=sid,output=str(output))
                self.assertEqual(exported.state,'SUCCEEDED',(exported.error,exported.evidence))
                self.assertFalse(json.loads(output.read_text(encoding='utf-8'))['completeness_asserted'])
                self.assertEqual(invoke(action='close',session_id=sid).state,'SUCCEEDED')
                replay=invoke(action='recording.read',session_id=sid)
                self.assertEqual(replay.state,'SUCCEEDED');self.assertFalse(replay.evidence['transport_accessed'])
            finally:declaration.adapter.backend.shutdown()
