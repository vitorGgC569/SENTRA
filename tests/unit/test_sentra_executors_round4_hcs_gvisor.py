"""Prepared profile contracts and explicitly optional REAL native providers."""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from dataclasses import replace
from sentra_executors.hcs_provider import NativeHCSBinding,HCSCommand,prepared_hcs_config,declare_native_hcs_machine
from sentra_executors.gvisor_workload import RunscWorkloadBinding,WorkloadLease,inspect_workload,declare_runsc_workload_machine
from sentra_executors.identity_sessions import SessionJournal
from sentra_executors.rpa import AuthorizedPaths,ExecutorFailure,digest
from sentra_runtime.contracts import OperationRequest,PolicyDecision


class HeadlessProfileContract(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve();self.paths=AuthorizedPaths((str(self.root),),(str(self.root),))
    def test_hcs_requires_real_prepared_hyperv_profile_with_resource_limits(self):
        config=self.root/'hcs.json';payload={'SystemType':'Container','Name':'sentra-lab-unit','HvPartition':True,
            'Layers':[{'ID':'prepared-layer','Path':str(self.root)}],'HvRuntime':{'ImagePath':str(self.root)},
            'MemoryMaximumInMB':512,'ProcessorCount':1,'ProcessorMaximum':1000}
        config.write_text(json.dumps(payload))
        binding=NativeHCSBinding('hcs','sentra-lab-unit',str(self.root/'bridge.exe'),'0'*64,str(config),digest(config),self.paths,self.paths)
        self.assertTrue(prepared_hcs_config(binding)['HvPartition'])
        for key,value in (('HvPartition',False),('MappedDirectories',[{'HostPath':'C:\\','ReadOnly':False}]),('EndpointList',['unapproved-network'])):
            changed=dict(payload,**{key:value});config.write_text(json.dumps(changed))
            with self.assertRaises(ExecutorFailure):prepared_hcs_config(replace(binding,config_sha256=digest(config)))
    def test_runsc_useful_workload_is_pinned_and_cannot_add_host_hook_or_rw_mount(self):
        bundle=self.root/'bundle';program=bundle/'rootfs/bin/representative';program.parent.mkdir(parents=True);program.write_bytes(b'BYTE FIXTURE NOT EXECUTABLE')
        spec={'ociVersion':'1.0.2','root':{'path':'rootfs','readonly':True},'process':{'args':['/bin/representative'],'user':{'uid':1000,'gid':1000},
            'noNewPrivileges':True,'capabilities':{'bounding':[],'effective':[],'permitted':[],'inheritable':[],'ambient':[]}},'mounts':[],
            'linux':{'namespaces':[{'type':n} for n in ('pid','network','mount','ipc','uts')],
                     'resources':{'pids':{'limit':32},'memory':{'limit':128*1024*1024}}}}
        config=bundle/'config.json';config.write_text(json.dumps(spec))
        binding=RunscWorkloadBinding('runsc','sentra-lab-unit',str(self.root/'runsc'),'0'*64,str(bundle),digest(config),digest(program),
            str(self.root/'state'),str(self.root/'checkpoints'),self.paths)
        result=inspect_workload(binding);self.assertEqual(result['args'],['/bin/representative']);self.assertFalse(result['isolation_attested'])
        spec['hooks']={'prestart':[{'path':'/bin/sh'}]};config.write_text(json.dumps(spec))
        with self.assertRaisesRegex(ExecutorFailure,'hooks'):inspect_workload(replace(binding,config_sha256=digest(config)))


def invoke(declaration,principal,capability,counter,**args):
    return asyncio.run(declaration.adapter.start(OperationRequest('native'+str(counter),principal,declaration.machine.machine_id,
        capability,'work','native-key'+str(counter),args)))


@unittest.skipUnless(os.environ.get('SENTRA_RUNSC_R4_ACCEPTANCE')=='1','REAL Linux runsc workload acceptance staged, disabled')
class RealRunscWorkloadAcceptance(unittest.TestCase):
    def test_create_start_wait_and_cleanup_of_only_configured_workload(self):
        keys=('SENTRA_RUNSC_BINARY','SENTRA_RUNSC_BINARY_SHA256','SENTRA_RUNSC_BUNDLE','SENTRA_RUNSC_CONFIG_SHA256',
              'SENTRA_RUNSC_PROGRAM_SHA256','SENTRA_RUNSC_STATE_ROOT','SENTRA_RUNSC_CHECKPOINT_ROOT','SENTRA_RUNSC_CONTAINER_ID')
        for key in keys:self.assertTrue(os.environ.get(key),'required real runsc setting missing: '+key)
        with tempfile.TemporaryDirectory(prefix='sentra-runsc-real-') as directory:
            root=Path(directory).resolve();paths=AuthorizedPaths((str(root),),(str(root),))
            binding=RunscWorkloadBinding('workload',os.environ[keys[7]],os.environ[keys[0]],os.environ[keys[1]],
                os.environ[keys[2]],os.environ[keys[3]],os.environ[keys[4]],os.environ[keys[5]],os.environ[keys[6]],paths,
                actions=('create','start','state','wait','terminate','delete','evidence.export'))
            declaration=declare_runsc_workload_machine(machine_id='runsc-live',owner_principal_id='acceptance',bindings=(binding,),
                journal=SessionJournal(str(root/'state.sqlite'),paths),
                lease_reader=lambda cid,scope:WorkloadLease(cid,scope,1,time.monotonic()+60),
                policy=lambda r:PolicyDecision(True,'explicit disposable real Linux lab'))
            sid=None
            try:
                created=invoke(declaration,'acceptance','workload',1,action='create');self.assertEqual(created.state,'SUCCEEDED',(created.error,created.evidence));sid=created.evidence['session_id']
                self.assertEqual(invoke(declaration,'acceptance','workload',2,action='start',session_id=sid).state,'SUCCEEDED')
                waited=invoke(declaration,'acceptance','workload',3,action='wait',session_id=sid)
                self.assertEqual(waited.state,'SUCCEEDED',(waited.error,waited.evidence));self.assertEqual(waited.evidence['process_wait_result']['exitStatus'],0)
                self.assertEqual(invoke(declaration,'acceptance','workload',4,action='evidence.export',session_id=sid,output=str(root/'workload.json')).state,'SUCCEEDED')
            finally:
                if sid:
                    result=invoke(declaration,'acceptance','workload',5,action='delete',session_id=sid)
                    self.assertEqual(result.state,'SUCCEEDED',(result.error,result.evidence))
        # Filesystem/network denial and checkpoint compatibility need a pinned
        # adversarial/long-running workload; they're separate external criteria.


@unittest.skipUnless(os.environ.get('SENTRA_HCS_R4_ACCEPTANCE')=='1','REAL HCS/native bridge acceptance staged, disabled')
class RealHCSHeadlessAcceptance(unittest.TestCase):
    def test_real_prepared_container_command_and_waited_termination(self):
        keys=('SENTRA_HCS_BRIDGE','SENTRA_HCS_BRIDGE_SHA256','SENTRA_HCS_CONFIG','SENTRA_HCS_CONFIG_SHA256','SENTRA_HCS_CONTAINER_ID',
              'SENTRA_HCS_COMMAND_JSON','SENTRA_HCS_EXPECTED_STDOUT')
        for key in keys:self.assertTrue(os.environ.get(key),'required real HCS setting missing: '+key)
        with tempfile.TemporaryDirectory(prefix='sentra-hcs-real-') as directory:
            root=Path(directory).resolve();outputs=AuthorizedPaths((str(root),),(str(root),))
            host=AuthorizedPaths((str(Path(os.environ[keys[2]]).resolve().parent),),())
            command=HCSCommand(**json.loads(os.environ[keys[5]]))
            binding=NativeHCSBinding('headless',os.environ[keys[4]],os.environ[keys[0]],os.environ[keys[1]],os.environ[keys[2]],os.environ[keys[3]],
                host,outputs,commands=(command,),actions=('create','start','status','run','terminate'))
            declaration=declare_native_hcs_machine(machine_id='hcs-live',owner_principal_id='acceptance',bindings=(binding,),
                journal=SessionJournal(str(root/'hcs.sqlite'),outputs),policy=lambda r:PolicyDecision(True,'explicit disposable real HCS lab'))
            sid=None
            try:
                created=invoke(declaration,'acceptance','headless',1,action='create');self.assertEqual(created.state,'SUCCEEDED',(created.error,created.evidence));sid=created.evidence['session_id']
                self.assertFalse(created.evidence['interactive_desktop'])
                self.assertEqual(invoke(declaration,'acceptance','headless',2,action='start',session_id=sid).state,'SUCCEEDED')
                result=invoke(declaration,'acceptance','headless',3,action='run',session_id=sid,command_key=command.key)
                self.assertEqual(result.state,'SUCCEEDED',(result.error,result.evidence));self.assertEqual(result.evidence['exit_code'],0)
                self.assertIn(os.environ[keys[6]],result.evidence['stdout']);self.assertTrue(result.evidence['streams_completed'])
            finally:
                if sid:
                    closed=invoke(declaration,'acceptance','headless',4,action='terminate',session_id=sid)
                    self.assertEqual(closed.state,'SUCCEEDED',(closed.error,closed.evidence));self.assertTrue(closed.evidence['termination_wait_completed'])
