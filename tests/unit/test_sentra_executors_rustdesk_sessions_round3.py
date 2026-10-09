"""Prepared peer/ownership contracts and opt-in actual native acceptance.

Byte fixtures below are NOT RustDesk binaries and never claim connectivity.
"""
import asyncio
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from sentra_executors.identity_sessions import SessionJournal
from sentra_executors.remote_rustdesk import RustDeskPeerBinding,RustDeskNativeBackend,declare_rustdesk_machine
from sentra_executors.remote_rustdesk_build import native_peer_gate_patch
from sentra_executors.remote_deployment import guacd_compose,rustdesk_server_compose
from sentra_executors.rpa import AuthorizedPaths,ExecutorFailure,digest
from sentra_runtime.contracts import OperationRequest,PolicyDecision


class NativePeerConfigurationContract(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve();self.paths=AuthorizedPaths((str(self.root),),(str(self.root),))
        self.exe=self.root/'client.exe';self.exe.write_bytes(b'unit-byte-fixture-not-a-rustdesk-executable')
        self.manifest=self.root/'build.json';self.manifest.write_text('{}')
        self.binding=RustDeskPeerBinding('peer','fixed-inventory-alias','123456789','0'*64,'rd.example.test',
            'host-reviewed-server-public-key',str(self.exe),digest(self.exe),str(self.manifest),str(self.root),self.paths)
        self.journal=SessionJournal(str(self.root/'sessions.sqlite'),self.paths)
        self.backend=RustDeskNativeBackend(self.journal)

    def test_stock_launcher_manifest_is_not_accepted_as_peer_pin(self):
        with self.assertRaisesRegex(ExecutorFailure,'not_attested'):self.backend._build(self.binding)
        self.manifest.write_text(json.dumps({'extension':'sentra-peer-gate-v1','source_revision':'reviewed-source',
            'executable_sha256':digest(self.exe),'stock_cli_supported':False}))
        with self.assertRaisesRegex(ExecutorFailure,'bundle_pins_required'):self.backend._build(self.binding)

    def test_host_runtime_write_authority_cannot_be_used_by_export(self):
        workspace=self.root/'workspace';workspace.mkdir()
        artifact_paths=AuthorizedPaths((str(workspace),),(str(workspace),))
        binding=replace(self.binding,paths=artifact_paths,host_runtime_paths=self.paths)
        declaration=declare_rustdesk_machine(machine_id='m',owner_principal_id='p',bindings=(binding,),
            journal=self.journal,policy=lambda r:PolicyDecision(True,'schema-only fixture'))
        for index,output in enumerate((self.manifest,self.root/'lease.json')):
            result=asyncio.run(declaration.adapter.start(OperationRequest('output'+str(index),'p','m','peer','w','output'+str(index),
                {'action':'evidence.export','session_id':'not-dispatched','output':str(output)})))
            self.assertNotEqual(result.state,'SUCCEEDED');self.assertEqual(result.error,'invalid_scope_or_capability')
        self.assertEqual(binding.runtime_paths.resolve(str(self.root/'lease.json'),write=True),self.root/'lease.json')

    def test_readonly_manifest_policy_can_be_separate_from_runtime_and_workspace(self):
        runtime=self.root/'runtime';runtime.mkdir()
        workspace=self.root/'workspace';workspace.mkdir()
        binding=replace(self.binding,paths=AuthorizedPaths((str(workspace),),(str(workspace),)),runtime_root=str(runtime),
            host_runtime_paths=AuthorizedPaths((str(runtime),),(str(runtime),)),
            manifest_paths=AuthorizedPaths((str(self.root),),()))
        self.assertEqual(binding.build_paths.resolve(str(self.exe)),self.exe)
        with self.assertRaisesRegex(ValueError,'path_outside_authorized_roots'):
            binding.artifact_paths.resolve(str(self.manifest),write=True)
        with self.assertRaisesRegex(ValueError,'readonly_host_manifest_paths_required'):
            replace(binding,manifest_paths=self.paths)

    def test_runtime_nested_under_workspace_is_still_not_exportable(self):
        workspace=self.root/'workspace';workspace.mkdir();runtime=workspace/'native-runtime';runtime.mkdir()
        binding=replace(self.binding,paths=AuthorizedPaths((str(workspace),),(str(workspace),)),runtime_root=str(runtime),
            host_runtime_paths=AuthorizedPaths((str(runtime),),(str(runtime),)))
        with self.assertRaisesRegex(ValueError,'overlaps_protected_host_paths'):
            binding.resolve_artifact_output(str(runtime/'lease.json'))
        self.assertEqual(binding.resolve_artifact_output(str(workspace/'evidence.json')),workspace/'evidence.json')

    def test_bundle_cannot_read_outside_owned_build(self):
        self.manifest.write_text(json.dumps({'extension':'sentra-peer-gate-v1','source_revision':'reviewed-source',
            'executable_sha256':digest(self.exe),'stock_cli_supported':False,
            'bundle_sha256':{'librustdesk.dll':'0'*64,'../foreign.dll':'0'*64}}))
        with self.assertRaises((ExecutorFailure,FileNotFoundError)):self.backend._build(self.binding)

    def test_request_cannot_replace_peer_key_endpoint_or_executable(self):
        declaration=declare_rustdesk_machine(machine_id='m',owner_principal_id='p',bindings=(self.binding,),
            journal=self.journal,policy=lambda r:PolicyDecision(True,'schema-only fixture'))
        for index,field in enumerate(('peer_id','peer_key_sha256','executable','rendezvous_server','remote_id')):
            result=asyncio.run(declaration.adapter.start(OperationRequest(str(index),'p','m','peer','w',str(index),
                {'action':'open',field:'attacker-controlled'})))
            self.assertEqual(result.error,'invalid_scope_or_capability');self.assertEqual(self.backend.running,{})

    def test_ip_or_arbitrary_url_is_not_an_inventory_peer_id(self):
        for value in ('192.168.1.5','https://foreign.test','123@remote','--install'):
            with self.subTest(value=value),self.assertRaises(ValueError):replace(self.binding,peer_id=value)

    def test_restart_never_reuses_a_stored_pid(self):
        row=self.journal.create('scope','rustdesk',self.binding.identity,self.binding.peer_id,{'native_pid':123})
        with self.assertRaisesRegex(ExecutorFailure,'not_reattachable'):
            self.backend.run(self.binding,{'action':'reattach','session_id':row['id'],'_scope':'scope','_operation_id':'op'})

    def test_native_patch_fails_on_unknown_source_instead_of_guessing_protocol(self):
        (self.root/'src').mkdir();(self.root/'src/lib.rs').write_text('unknown source')
        with self.assertRaisesRegex(ExecutorFailure,'source_drift'):native_peer_gate_patch(str(self.root))

    def test_reviewable_patch_from_actual_clone_never_marks_build_operational(self):
        clone=Path(__file__).resolve().parents[2]/'third_party/rustdesk'
        if not clone.is_dir():self.skipTest('source clone unavailable; no native build claim')
        plan=native_peer_gate_patch(str(clone))
        self.assertFalse(plan['compiled']);self.assertFalse(plan['operational'])
        self.assertIn('SENTRA requires verified rendezvous peer identity',plan['patch'])
        self.assertIn('GetEnvironmentVariableW',plan['patch'])
        self.assertIn('check_identity(peer_id, &sign_pk.0)',plan['patch'])

    def test_deployment_specs_have_real_daemon_commands_and_no_unpinned_images(self):
        with self.assertRaises(ValueError):guacd_compose(image='guacamole/guacd:latest',
            certificate_file=str(self.exe),private_key_file=str(self.exe))
        spec=guacd_compose(image='guacamole/guacd@sha256:'+'0'*64,
            certificate_file=str(self.exe),private_key_file=str(self.exe))
        self.assertEqual(spec['services']['sentra-guacd']['ports'],['127.0.0.1:4822:4822/tcp'])
        native=rustdesk_server_compose(image='rustdesk/rustdesk-server@sha256:'+'0'*64,
            data_directory=str(self.root),relay_address='relay.example.test:21117',bind_address='127.0.0.1')
        self.assertEqual(native['services']['sentra-hbbr']['command'],['hbbr'])
        self.assertNotIn('21118',json.dumps(native));self.assertNotIn('21119',json.dumps(native))


@unittest.skipUnless(os.environ.get('SENTRA_RUSTDESK_ACCEPTANCE')=='1','REAL peer-gated native build acceptance staged, disabled')
class RealRustDeskNativeAcceptance(unittest.TestCase):
    def test_verified_peer_owned_reattach_artifact_close_and_wrong_pin(self):
        required=('SENTRA_RUSTDESK_EXECUTABLE','SENTRA_RUSTDESK_EXECUTABLE_SHA256','SENTRA_RUSTDESK_BUILD_MANIFEST',
                  'SENTRA_RUSTDESK_PEER_ID','SENTRA_RUSTDESK_PEER_SHA256','SENTRA_RUSTDESK_SERVER','SENTRA_RUSTDESK_SERVER_KEY')
        for key in required:self.assertTrue(os.environ.get(key),'required real native configuration missing: '+key)
        with tempfile.TemporaryDirectory(prefix='sentra-native-acceptance-') as directory:
            root=Path(directory).resolve();runtime=root/'native';runtime.mkdir()
            paths=AuthorizedPaths((str(root),str(Path(os.environ[required[0]]).resolve().parent),
                str(Path(os.environ[required[2]]).resolve().parent)),(str(root),))
            binding=RustDeskPeerBinding('peer','authorized-acceptance-peer',os.environ[required[3]],os.environ[required[4]],
                os.environ[required[5]],os.environ[required[6]],os.environ[required[0]],os.environ[required[1]],
                os.environ[required[2]],str(runtime),paths)
            journal=SessionJournal(str(root/'native.sqlite'),paths)
            declaration=declare_rustdesk_machine(machine_id='native',owner_principal_id='acceptance',bindings=(binding,),
                journal=journal,policy=lambda r:PolicyDecision(True,'explicit actual native acceptance'))
            count=0
            def invoke(work='work',**arguments):
                nonlocal count;count+=1
                return asyncio.run(declaration.adapter.start(OperationRequest('native'+str(count),'acceptance','native',
                    'peer',work,'native-key'+str(count),arguments)))
            try:
                opened=invoke(action='open');self.assertEqual(opened.state,'SUCCEEDED',(opened.error,opened.evidence))
                sid=opened.evidence['session_id'];self.assertTrue(opened.evidence['peer_authenticated'])
                self.assertFalse(opened.evidence['desktop_login_asserted']);self.assertFalse(opened.evidence['control_api_available'])
                denied=invoke(work='foreign',action='read',session_id=sid);self.assertNotEqual(denied.state,'SUCCEEDED')
                attached=invoke(action='reattach',session_id=sid);self.assertEqual(attached.state,'SUCCEEDED',attached.error)
                self.assertEqual(attached.evidence['current_transport_state'],'UNKNOWN')
                exported=invoke(action='evidence.export',session_id=sid,output=str(root/'identity.json'))
                self.assertEqual(exported.state,'SUCCEEDED',exported.error)
                closed=invoke(action='close',session_id=sid);self.assertEqual(closed.state,'SUCCEEDED',closed.error)
                self.assertEqual(declaration.adapter.backend.running,{})
            finally:declaration.adapter.backend.shutdown()
            wrong=replace(binding,peer_key_sha256=('1' if binding.peer_key_sha256[0]!='1' else '2')+binding.peer_key_sha256[1:])
            negative=declare_rustdesk_machine(machine_id='negative',owner_principal_id='acceptance',bindings=(wrong,),journal=journal,
                policy=lambda r:PolicyDecision(True,'explicit actual wrong-pin lab'))
            try:
                result=asyncio.run(negative.adapter.start(OperationRequest('negative-pin','acceptance','negative','peer','work',
                    'negative-pin',{'action':'open'})))
                self.assertNotEqual(result.state,'SUCCEEDED');self.assertFalse(result.evidence.get('peer_authenticated',False))
                self.assertEqual(negative.adapter.backend.running,{})
            finally:negative.adapter.backend.shutdown()
