"""Prepared EXTERNAL Hyper-V guest acceptance; never enabled implicitly.

Uses actual PowerShell Direct + interactive task. Standalone lab lease here
does not validate central grants/fencing/OS host lock integration.
"""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from sentra_executors.windows_guest import (HyperVGuestConfig,GuestLease,HyperVFixtureBinding,GuestArtifactBinding,
    declare_hyperv_fixture_machine,declare_guest_artifact_machine,declare_windows_guest_uia_machine)
from sentra_executors.windows_guest_deployment import binding_from_fixture_identity
from sentra_executors.uia_semantic import UIASelector
from sentra_executors.benchmark_acceptance import BenchmarkVerifierBinding,ExpectedArtifact,ArtifactCriterion,VerifierCase,verify_case
from sentra_executors.rpa import AuthorizedPaths,digest
from sentra_runtime.contracts import OperationRequest,PolicyDecision


@unittest.skipUnless(os.environ.get('SENTRA_GUEST_R4_ACCEPTANCE')=='1','REAL disposable Hyper-V desktop acceptance staged, disabled')
class RealHyperVDesktopAcceptance(unittest.TestCase):
    def test_reset_prepare_interactive_uia_and_independent_csv_result(self):
        keys=('SENTRA_GUEST_CONFIG_JSON','SENTRA_GUEST_USERNAME','SENTRA_GUEST_PASSWORD','SENTRA_GUEST_IDENTITY_PATH',
              'SENTRA_GUEST_RESULT_CSV_PATH','SENTRA_GUEST_MACHINE_GUID','SENTRA_GUEST_FIXTURE_EXE_SHA256',
              'SENTRA_GUEST_EXPECTED_CSV','SENTRA_GUEST_EXPECTED_CSV_SHA256','SENTRA_GUEST_INPUT_VALUE')
        for key in keys:self.assertTrue(os.environ.get(key),'required actual guest configuration missing: '+key)
        settings=json.loads(os.environ[keys[0]]);settings['guest_source_pins']=tuple(tuple(p) for p in settings['guest_source_pins'])
        settings.setdefault('fixture_identity_path',os.environ[keys[3]])
        if 'allowed_switch_ids' in settings:settings['allowed_switch_ids']=tuple(settings['allowed_switch_ids'])
        config=HyperVGuestConfig(**settings,credential=lambda:(os.environ[keys[1]],os.environ[keys[2]]))
        def lease(vm,scope):return GuestLease(vm,scope,1,time.monotonic()+60)
        policy=lambda r:PolicyDecision(True,'explicit disposable EXTERNAL real guest lab')
        with tempfile.TemporaryDirectory(prefix='sentra-hyperv-real-') as directory:
            root=Path(directory).resolve();outputs=AuthorizedPaths((str(root),),(str(root),))
            fixture=declare_hyperv_fixture_machine(machine_id='fixture',owner_principal_id='acceptance',bindings=(
                HyperVFixtureBinding('fixture',config,actions=('status','reset','prepare')),),lease_reader=lease,policy=policy)
            collector=declare_guest_artifact_machine(machine_id='collect',owner_principal_id='acceptance',bindings=(GuestArtifactBinding(
                'collect',config,(('fixture_identity',os.environ[keys[3]]),('result_csv',os.environ[keys[4]])),outputs),),lease_reader=lease,policy=policy)
            count=0
            def invoke(declaration,capability,**arguments):
                nonlocal count;count+=1
                result=asyncio.run(declaration.adapter.start(OperationRequest('guest'+str(count),'acceptance',declaration.machine.machine_id,
                    capability,'work','guest-key'+str(count),arguments)))
                self.assertEqual(result.state,'SUCCEEDED',(result.error,result.evidence));return result.evidence
            reset=invoke(fixture,'fixture',action='reset');self.assertEqual(reset['snapshot_id'],config.baseline_snapshot_id)
            invoke(fixture,'fixture',action='prepare')
            # Allow initial fixture creation; repeated polling is read-only and
            # must use fresh Operation IDs. Never replay a failed UI mutation.
            identity_output=root/'identity.json'
            identity=invoke(collector,'collect',action='collect',artifact_key='fixture_identity',output=str(identity_output))
            self.assertEqual(digest(identity_output),identity['sha256'])
            binding=binding_from_fixture_identity(capability_id='uia',identity_bytes=identity_output.read_bytes(),
                expected_machine_guid=os.environ[keys[5]],expected_executable_sha256=os.environ[keys[6]],paths=outputs,
                selectors=(UIASelector('input','InputValue','Edit',actions=('read','set_value')),
                    UIASelector('save','SaveResult','Button',actions=('read','invoke')),
                    UIASelector('status','ResultStatus','Text')),timeout_seconds=config.timeout_seconds+10)
            desktop=declare_windows_guest_uia_machine(machine_id='desktop',owner_principal_id='acceptance',bindings=(binding,),
                guest_config=config,lease_reader=lease,policy=policy)
            try:
                invoke(desktop,'uia',action='wait',selector_key='status',expected={'text':'Not saved'},wait_seconds=5)
                observed=invoke(desktop,'uia',action='observe')
                self.assertEqual(observed['vm_id'],config.vm_id);self.assertFalse(observed['isolation_attested'])
                invoke(desktop,'uia',action='set_value',reference=observed['elements'][0]['reference'],value=os.environ[keys[9]])
                observed=invoke(desktop,'uia',action='observe')
                invoke(desktop,'uia',action='invoke',reference=observed['elements'][1]['reference'])
                invoke(desktop,'uia',action='wait',selector_key='status',expected={'text':'Saved: '+os.environ[keys[9]]},wait_seconds=5)
                invoke(desktop,'uia',action='screenshot',output=str(root/'window.png'))
                result=invoke(collector,'collect',action='collect',artifact_key='result_csv',output=str(root/'result.csv'))
                golden=Path(os.environ[keys[7]]).resolve();case=VerifierCase('forms',(ArtifactCriterion('csv','result','golden','table'),))
                judge=BenchmarkVerifierBinding('judge',AuthorizedPaths((str(root),),()),AuthorizedPaths((str(golden.parent),),()),outputs,
                    (ExpectedArtifact('golden',str(golden),os.environ[keys[8]]),),(case,))
                verdict=verify_case(judge,case,{'result':{'path':result['path'],'sha256':result['sha256']}})
                self.assertEqual(verdict['state'],'PASS',verdict);self.assertFalse(verdict['executor_success_used_as_score'])
            finally:desktop.adapter.backend.shutdown()
