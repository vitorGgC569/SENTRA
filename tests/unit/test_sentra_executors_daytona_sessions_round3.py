"""Prepared schemas plus explicit optional REAL Daytona service acceptance."""
import asyncio
import base64
import os
import tempfile
import unittest
from pathlib import Path
from sentra_executors.daytona_sessions import DaytonaConnectionConfig,DaytonaSessionBinding,declare_daytona_session_machine
from sentra_executors.identity_sessions import SessionJournal
from sentra_executors.rpa import AuthorizedPaths
from sentra_runtime.contracts import OperationRequest,PolicyDecision


class DaytonaConfigurationContract(unittest.TestCase):
    def test_no_implicit_endpoint_credentials_or_unpinned_private_pty_api(self):
        with self.assertRaises(ValueError):DaytonaConnectionConfig('https://example.test/api','eu',lambda:'secret')
        with self.assertRaises(ValueError):DaytonaConnectionConfig('http://remote.test/api','eu',lambda:'secret',('1.0',),'0'*64)

    def test_caller_cannot_choose_arbitrary_sandbox_command_or_remote_pty_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();paths=AuthorizedPaths((str(root),),(str(root),))
            binding=DaytonaSessionBinding('terminal',DaytonaConnectionConfig('https://example.test/api','region',
                lambda:'not-dispatched',('explicit-test-version',),'0'*64),paths,existing_sandbox_ids=('owned',))
            declaration=declare_daytona_session_machine(machine_id='m',owner_principal_id='p',bindings=(binding,),
                journal=SessionJournal(str(root/'sessions.sqlite'),paths),policy=lambda r:PolicyDecision(True,'schema fixture'))
            for index,args in enumerate(({'action':'pty.create','session_id':'s','sandbox_id':'foreign'},
                {'action':'sandbox.read','inventory_sandbox_id':'foreign'},
                {'action':'pty.write','session_id':'s','text':'unapproved stdin'})):
                result=asyncio.run(declaration.adapter.start(OperationRequest(str(index),'p','m','terminal','w',str(index),args)))
                self.assertEqual(result.state,'FAILED');self.assertEqual(result.error,'invalid_scope_or_capability')


@unittest.skipUnless(os.environ.get('SENTRA_DAYTONA_ACCEPTANCE')=='1','REAL Daytona API/PTY service acceptance staged, disabled')
class RealDaytonaPTYAcceptance(unittest.TestCase):
    def test_owned_pty_stream_disconnect_reattach_cancel_and_evidence(self):
        required=('SENTRA_DAYTONA_API_URL','SENTRA_DAYTONA_TARGET','SENTRA_DAYTONA_API_KEY',
                  'SENTRA_DAYTONA_SDK_VERSION','SENTRA_DAYTONA_PTY_SHA256','SENTRA_DAYTONA_SANDBOX_ID')
        for key in required:self.assertTrue(os.environ.get(key),'required configuration missing: '+key)
        with tempfile.TemporaryDirectory(prefix='sentra-daytona-real-') as directory:
            root=Path(directory).resolve();paths=AuthorizedPaths((str(root),),(str(root),))
            config=DaytonaConnectionConfig(os.environ[required[0]],os.environ[required[1]],lambda:os.environ[required[2]],
                (os.environ[required[3]],),os.environ[required[4]])
            binding=DaytonaSessionBinding('terminal',config,paths,existing_sandbox_ids=(os.environ[required[5]],),allow_pty_input=True)
            declaration=declare_daytona_session_machine(machine_id='live-daytona',owner_principal_id='acceptance',bindings=(binding,),
                journal=SessionJournal(str(root/'sessions.sqlite'),paths),policy=lambda r:PolicyDecision(True,'explicit real Daytona lab'))
            counter=0
            def invoke(**arguments):
                nonlocal counter;counter+=1
                result=asyncio.run(declaration.adapter.start(OperationRequest('live'+str(counter),'acceptance','live-daytona',
                    'terminal','work','live-key'+str(counter),arguments)))
                self.assertEqual(result.state,'SUCCEEDED',(result.error,result.evidence));return result.evidence
            try:
                parent=invoke(action='sandbox.read',inventory_sandbox_id=os.environ[required[5]])['session_id']
                sid=invoke(action='pty.create',session_id=parent)['session_id']
                invoke(action='pty.write',session_id=sid,text="printf 'sentr%s\\n' 'a-executed'\n")
                output=b'';cursor=0
                for _ in range(20):
                    data=invoke(action='pty.read',session_id=sid,after=cursor,wait_seconds=.5)
                    output+=b''.join(base64.b64decode(e['data_base64']) for e in data['events'] if e['channel']=='pty')
                    cursor=data['cursor']
                    if b'sentra-executed' in output:break
                self.assertIn(b'sentra-executed',output)
                invoke(action='pty.disconnect',session_id=sid)
                self.assertFalse(invoke(action='pty.reattach',session_id=sid)['remote_history_replayed'])
                invoke(action='pty.resize',session_id=sid,rows=30,cols=100)
                invoke(action='evidence.export',session_id=sid,output=str(root/'pty.json'))
                invoke(action='pty.cancel',session_id=sid)
            finally:declaration.adapter.backend.shutdown()
