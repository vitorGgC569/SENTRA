"""Prepared deterministic contracts. Injected observations prove cache logic ONLY."""
import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
from sentra_executors.uia_semantic import SemanticUIABinding,DesktopIdentity,UIASelector,SemanticUIABackend
from sentra_executors.windows_identity import ProcessIdentity
from sentra_executors.benchmark_acceptance import (
    ExpectedArtifact,ArtifactCriterion,VerifierCase,BenchmarkVerifierBinding,verify_case,
    AcceptanceRunner,AcceptanceCasePlan,AcceptanceStep,forms_acceptance_plan,
)
from sentra_executors.windows_guest import HyperVGuestConfig,HyperVClient,GuestLease
from sentra_executors.windows_guest_deployment import windows_forms_fixture_script,interactive_guest_task_setup
from sentra_executors.rpa import AuthorizedPaths,ExecutorFailure,digest


class ObservationFixtureRunner:
    """Synthetic UIA values, no COM/Windows/VM or identity assurance."""
    def __init__(self):self.calls=[]
    def invoke(self,*args,input_document,**kwargs):
        self.calls.append(input_document)
        return {'elements':[{'selector_key':'input','runtime_id':[1,2],'value':'fixture'}]}


class SemanticReferenceContract(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve();self.paths=AuthorizedPaths((str(self.root),),(str(self.root),))
        self.binding=SemanticUIABinding('uia',ProcessIdentity(11,22,33,'0'*64),'fixture',DesktopIdentity('fixture-machine',1),
            (UIASelector('input','InputValue','Edit'),),self.paths)
        self.runner=ObservationFixtureRunner();self.backend=SemanticUIABackend(self.runner)
    def test_reference_cannot_cross_work_item_or_profile_and_reobserve_invalidates_it(self):
        observed=self.backend.run(self.binding,{'action':'observe','_scope':'work-one'})
        token=observed['elements'][0]['reference']
        for binding,scope in ((self.binding,'work-two'),(replace(self.binding,identity=ProcessIdentity(11,22,34,'0'*64)),'work-one')):
            with self.assertRaisesRegex(ExecutorFailure,'reference_not_owned'):
                self.backend.run(binding,{'action':'read','_scope':scope,'reference':token})
        self.backend.run(self.binding,{'action':'observe','_scope':'work-one'})
        with self.assertRaisesRegex(ExecutorFailure,'reference_not_owned'):
            self.backend.run(self.binding,{'action':'read','_scope':'work-one','reference':token})
        self.assertEqual(len(self.runner.calls),2)
    def test_guest_requires_live_owned_epoch_before_launch(self):
        config=HyperVGuestConfig('00000000-0000-0000-0000-000000000001','fixture-vm','SENTRA-DISPOSABLE:unit',
            '0'*64,str(self.root/'powershell.exe'),'0'*64,lambda:('user','secret'),guest_source_pins=((r'C:\SENTRA\worker.py','0'*64),))
        client=HyperVClient(config,lambda vm,scope:GuestLease(vm,'0'*64,1,1e20))
        with self.assertRaisesRegex(ExecutorFailure,'ownership_or_epoch'):client._lease('work-one')
    def test_deployment_script_only_registers_interactive_guest_task(self):
        config=HyperVGuestConfig('00000000-0000-0000-0000-000000000001','fixture-vm','SENTRA-DISPOSABLE:unit',
            '0'*64,str(self.root/'powershell.exe'),'0'*64,lambda:('user','secret'),guest_source_pins=((r'C:\SENTRA\worker.py','0'*64),))
        plan=interactive_guest_task_setup(config,guest_user='FixtureUser')
        self.assertIn('-LogonType Interactive -RunLevel Limited',plan);self.assertNotIn('Start-VM',plan)
        script=windows_forms_fixture_script(output_csv=r'C:\Fixture\OUTPUT_CSV.csv',identity_json=r'C:\Fixture\identity.json')
        self.assertIn("'C:\\Fixture\\OUTPUT_CSV.csv'",script);self.assertIn('ConvertTo-Csv',script)


class IndependentVerifierContract(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve();self.workspace=self.root/'workspace';self.golden=self.root/'golden'
        self.workspace.mkdir();self.golden.mkdir();self.expected=self.golden/'result.json';self.expected.write_text('{"Result":"accepted"}')
        self.actual=self.workspace/'result.json';self.actual.write_text('{"Result":"accepted"}')
        self.actuals={'result':{'path':str(self.actual),'sha256':digest(self.actual)}}
        self.case=VerifierCase('case',(ArtifactCriterion('final','result','golden','json'),))
        self.binding=BenchmarkVerifierBinding('judge',AuthorizedPaths((str(self.workspace),),()),
            AuthorizedPaths((str(self.golden),),()),AuthorizedPaths((str(self.workspace),),(str(self.workspace),)),
            (ExpectedArtifact('golden',str(self.expected),digest(self.expected)),),(self.case,))
    def test_result_is_independent_and_mismatch_is_task_failure(self):
        result=verify_case(self.binding,self.case,self.actuals)
        self.assertEqual(result['state'],'PASS');self.assertFalse(result['executor_success_used_as_score'])
        self.actual.write_text('{"Result":"wrong"}');self.actuals['result']['sha256']=digest(self.actual)
        result=verify_case(self.binding,self.case,self.actuals);self.assertEqual(result['state'],'FAIL');self.assertEqual(result['score'],0)
    def test_golden_or_captured_bytes_drift_is_evaluator_error_not_zero_score(self):
        self.actual.write_text('{"Result":"changed-after-capture"}')
        result=verify_case(self.binding,self.case,self.actuals)
        self.assertEqual(result['state'],'EVALUATOR_ERROR');self.assertIsNone(result['score'])
        self.expected.write_text('{}')
        result=verify_case(self.binding,self.case,{})
        self.assertEqual(result['criteria'][0]['reason'],'expected_artifact_pin_changed')
    def test_absent_actual_has_explicit_failure_and_goldens_are_not_exportable(self):
        self.assertEqual(verify_case(self.binding,self.case,{})['state'],'FAIL')
        with self.assertRaisesRegex(ValueError,'golden_inside_agent_output_scope'):
            replace(self.binding,output_paths=AuthorizedPaths((str(self.root),),(str(self.root),)))
    def test_composite_short_circuit_reports_unexecuted_criteria(self):
        case=VerifierCase('case',(ArtifactCriterion('absent','missing','golden','json'),ArtifactCriterion('not-run','result','golden','json')),
            short_circuit=True)
        result=verify_case(self.binding,case,self.actuals)
        self.assertEqual(result['criteria'][1]['state'],'NOT_EVALUATED');self.assertEqual(result['state'],'FAIL')


class RunnerContract(unittest.TestCase):
    def test_uncertain_effect_never_replayed_or_scored_as_success(self):
        calls=[]
        async def dispatch(**kwargs):
            calls.append(kwargs)
            if kwargs['arguments']['action']=='reset':return SimpleNamespace(state='SUCCEEDED',error=None,evidence={'snapshot_id':'baseline'})
            return SimpleNamespace(state='UNCERTAIN',error='physical_timeout',evidence={})
        plan=AcceptanceCasePlan('case','work','env-v1','uia',(
            AcceptanceStep('reset','guest','fixture',{'action':'reset'},'reset'),
            AcceptanceStep('mutate','guest','uia',{'action':'invoke'}),
            AcceptanceStep('judge','judge','verify',{'action':'verify'},'verify')),'baseline')
        result=asyncio.run(AcceptanceRunner(dispatch).run(run_id='run',plans=(plan,)))
        self.assertEqual(len(calls),2);self.assertEqual(result['passed'],0)
        self.assertEqual(result['cases'][0]['state'],'EXECUTOR_UNCERTAIN');self.assertNotIn('runtime_validation_performed_by_this_call',result)
    def test_self_reported_success_without_verifier_contract_is_rejected(self):
        async def dispatch(**kwargs):return SimpleNamespace(state='SUCCEEDED',error=None,evidence={'snapshot_id':'baseline','passed':True})
        plan=AcceptanceCasePlan('case','work','env-v1','uia',(
            AcceptanceStep('reset','guest','fixture',{'action':'reset'},'reset'),
            AcceptanceStep('judge','judge','verify',{'action':'verify'},'verify')),'baseline')
        result=asyncio.run(AcceptanceRunner(dispatch).run(run_id='run',plans=(plan,)))
        self.assertEqual(result['cases'][0]['state'],'VERIFIER_CONTRACT_ERROR');self.assertEqual(result['passed'],0)
