"""Prepared loading/judging/intent tests. Synthetic callbacks are not VM proof."""
import asyncio
import dataclasses
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from sentra_runtime.contracts import OperationRequest,OperationResult,PolicyDecision
from sentra_executors.benchmark_dataset import DatasetSource,DatasetCatalog,local_clone_sources
from sentra_executors.benchmark_dataset_metrics import compile_source_metrics,DatasetAssetPin,judge_dataset_task
from sentra_executors.benchmark_suite import (DatasetTaskRegistration,FixtureReadiness,HostDatasetCallbacks,DatasetSuiteState,
    DatasetEvaluationSuite,registration_contract_sha256)
from sentra_executors.benchmark_acceptance import AcceptanceCasePlan,AcceptanceStep,ReceiptField
from sentra_executors.benchmark_suite_reports import aggregate_dataset_reports,render_dataset_report_html
from sentra_executors.rpa import AuthorizedPaths,digest,ExecutorFailure


class DatasetContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.clone=self.root/'clone';self.clone.mkdir()
        example=self.clone/'evaluation_examples/examples/vs_code';example.mkdir(parents=True)
        payload={'id':'task','snapshot':'vscode','instruction':'Set wrapping to 50.','config':[],'related_apps':['vscode'],
            'evaluator':{'func':'check_json_settings','result':{'type':'vm_file','path':'/guest/settings.json'},
                         'expected':{'type':'rule','rules':{'expected':{'editor.wordWrapColumn':50}}}}}
        (example/'task.json').write_text(json.dumps(payload),encoding='utf-8')
        self.catalog=DatasetCatalog((DatasetSource('osworld-v2',str(self.clone),'0'*40,'osworld-v1-json'),)).load()
        self.task=next(iter(self.catalog.tasks.values()));self.contracts,reasons=compile_source_metrics(self.task);self.assertFalse(reasons)
        self.golden=self.root/'golden';self.golden.mkdir();gold=self.golden/'expected.json';gold.write_text('{"editor.wordWrapColumn":50}')
        self.assets=(DatasetAssetPin(self.contracts[0].expected_ref,str(gold),digest(gold)),)
        self.workspace=self.root/'workspace';self.workspace.mkdir();self.actual=self.workspace/'settings.json'
        self.actual.write_text('{"editor.wordWrapColumn":50,"other":true}')
        self.actuals={self.contracts[0].actual_key:{'path':str(self.actual),'sha256':digest(self.actual)}}
        self.state_dir=self.root/'durable';self.state_dir.mkdir();self.state=DatasetSuiteState(str(self.state_dir/'attempts.sqlite'),
            AuthorizedPaths((str(self.state_dir),),(str(self.state_dir),)),source_roots=(str(self.clone),))
    def judge(self,assets=None):
        return judge_dataset_task(self.task,self.contracts,self.actuals,self.assets if assets is None else assets,
            actual_paths=AuthorizedPaths((str(self.workspace),),()),expected_paths=AuthorizedPaths((str(self.golden),),()))
    def test_missing_expected_is_unsupported_not_pass_or_evaluated(self):
        report=self.judge(assets=());self.assertEqual(report['state'],'UNSUPPORTED');self.assertFalse(report['evaluated']);self.assertIsNone(report['score'])
    def test_source_algorithm_json_subset_and_actual_mismatch(self):
        self.assertEqual(self.judge()['score'],1)
        self.actual.write_text('{"editor.wordWrapColumn":30}');self.actuals[self.contracts[0].actual_key]['sha256']=digest(self.actual)
        self.assertEqual(self.judge()['state'],'FAIL')
    def test_dataset_source_changes_invalidate_registration(self):
        path=Path(self.task.source_path);path.write_text('{}')
        with self.assertRaisesRegex(ExecutorFailure,'source_bytes_changed'):self.catalog.revalidate(self.task)
    def test_official_v2_manifest_does_not_substitute_v1_for_missing_gated_class(self):
        (self.clone/'evaluation_examples/test_v2.json').write_text('{"tasks":["001"]}')
        catalog=DatasetCatalog((DatasetSource('osworld-v2',str(self.clone),'0'*40,'osworld-v2-python'),)).load()
        task=next(iter(catalog.tasks.values()));self.assertEqual(task.task_id,'001');self.assertIn('official_gated_task_not_local',task.indexing_issues)
        self.assertFalse(task.source_file_sha256);self.assertNotIn('vscode',task.payload)
    def _suite(self,*,uncertain=False,recovered_state='UNCERTAIN'):
        self.dispatched=[];self.recovered=[]
        def plan(task,context):
            return AcceptanceCasePlan('case',context['work_item_id'],'env-v1','uia',(
                AcceptanceStep('reset','guest','fixture',{'action':'reset'},'reset'),
                AcceptanceStep('actor','guest','uia',{'action':'invoke'}),
                AcceptanceStep('verify','judge','judge',{'action':'verify','task_key':task.key,'actuals':self.actuals},'verify')),'baseline')
        registration=DatasetTaskRegistration(self.task.key,self.task.payload_sha256,self.task.setup_sha256,self.task.evaluator_sha256,
            'fixture','baseline',('guest',),'env-v1',self.contracts,self.assets,plan,'judge','judge')
        def bind(context,intent):return OperationRequest(intent['operation_id'],'principal',intent['machine_id'],intent['capability_id'],
            intent['work_item_id'],intent['idempotency_key'],intent['arguments'])
        def dispatch(context,request):
            self.dispatched.append(request.operation_id)
            if request.arguments['action']=='reset':evidence={'snapshot_id':'baseline'}
            elif request.arguments['action']=='verify':evidence=self.judge()
            else:
                if uncertain:return OperationResult(request.operation_id,'UNCERTAIN',{},'fixture uncertainty only')
                evidence={'actor_claimed_success':True}
            return OperationResult(request.operation_id,'SUCCEEDED',evidence)
        def recover(context,request):
            self.recovered.append(request.operation_id);return OperationResult(request.operation_id,recovered_state,{'actor_claimed_success':True})
        callbacks=HostDatasetCallbacks(bind,dispatch,recover,lambda *args:PolicyDecision(True,'synthetic contract only'),
            lambda *args:FixtureReadiness('fixture','baseline',1,('guest',),'READY',{'origin':'synthetic_not_runtime_proof'}),
            lambda *args:registration_contract_sha256(registration))
        return DatasetEvaluationSuite(catalog=self.catalog,registrations=(registration,),state=self.state,callbacks=callbacks,
            asset_paths=AuthorizedPaths((str(self.golden),),()))
    def test_attempt_stops_before_independent_judge_evaluate_is_separate(self):
        suite=self._suite();report=asyncio.run(suite.attempt(self.task.key,run_id='run',work_item_id='work',attempt_id='one'))
        self.assertEqual(report['state'],'READY_TO_EVALUATE');self.assertFalse(report['evaluated']);self.assertEqual(len(self.dispatched),2)
        report=asyncio.run(suite.evaluate('one'));self.assertTrue(report['evaluated']);self.assertEqual(report['score'],1)
        self.assertFalse(report['agent_result']['used_as_verifier_score']);self.assertEqual(len(self.dispatched),3)
    def test_resume_only_reads_uncertain_intent_no_dispatch_or_automatic_reset(self):
        suite=self._suite(uncertain=True)
        report=asyncio.run(suite.attempt(self.task.key,run_id='run',work_item_id='work',attempt_id='one'))
        self.assertEqual(report['state'],'UNCERTAIN');count=len(self.dispatched)
        report=asyncio.run(suite.resume('one',evaluate=True));self.assertEqual(report['state'],'UNCERTAIN')
        self.assertEqual(len(self.dispatched),count);self.assertEqual(len(self.recovered),1)
        with self.assertRaisesRegex(ExecutorFailure,'active_or_uncertain'):
            asyncio.run(suite.attempt(self.task.key,run_id='run',work_item_id='work',attempt_id='two'))
    def test_reports_exclude_unsupported_from_score_and_escape_source_text(self):
        report={'state':'UNSUPPORTED','evaluated':False,'score':None,'source':{'dataset':'<script>','task_id':'bad','category':'L1'}}
        aggregate=aggregate_dataset_reports([report]);self.assertEqual(aggregate['evaluated'],0);self.assertIsNone(aggregate['mean_score'])
        rendered=render_dataset_report_html(aggregate);self.assertNotIn('<script>',rendered);self.assertIn('&lt;script&gt;',rendered)


class ActualLocalCloneIndexAcceptance(unittest.TestCase):
    def test_index_actual_formats_and_known_source_payloads_without_importing_task_code(self):
        root=Path(__file__).resolve().parents[2]
        if not (root/'third_party/windowsworld/benchmark.json').exists():self.skipTest('local datasets absent, no evaluated claim')
        catalog=DatasetCatalog(local_clone_sources(root)).load()
        arena=catalog.select(dataset='windows-agent-arena',task_ids=('28b91a24-5d97-4c2a-891c-dccbd3820c62-WOS',))
        self.assertTrue(arena);self.assertEqual(arena[0].evaluator['result']['filename'],'Differences.txt')
        world=catalog.select(dataset='windowsworld',task_ids=('win_hr__l1_001',));self.assertTrue(world)
        self.assertIn('files_to_create',world[0].setup);self.assertIn('intermediate_checks',world[0].evaluator)
        v2=[t for t in catalog.tasks.values() if t.source.layout=='osworld-v2-python'];self.assertTrue(v2)
        self.assertTrue(all(t.view()['evaluated'] is False for t in catalog.tasks.values()))


@unittest.skipUnless(os.environ.get('SENTRA_DATASET_REAL_ACCEPTANCE')=='1','REAL dataset/providers acceptance staged, disabled')
class RealConfiguredDatasetAcceptance(unittest.TestCase):
    def test_local_source_through_actual_central_provider_and_independent_verifier(self):
        name=os.environ.get('SENTRA_DATASET_HOST_FACTORY')
        self.assertTrue(name,'host-owned real factory module:function required')
        module,function=name.split(':',1)
        config=getattr(importlib.import_module(module),function)()
        suite=config['suite'];key=config['task_key'];task=suite.catalog.get(key)
        self.assertTrue(task.source_file_sha256);self.assertIn('third_party',task.source_path)
        supported=asyncio.run(suite.eligibility(key));self.assertTrue(supported['supported'],supported)
        report=asyncio.run(suite.attempt(key,run_id=config['run_id'],work_item_id=config['work_item_id'],attempt_id=config['attempt_id']))
        self.assertEqual(report['state'],'READY_TO_EVALUATE',report)
        report=asyncio.run(suite.evaluate(config['attempt_id']))
        self.assertTrue(report['evaluated'],report);self.assertIsNotNone(report['score'])
        self.assertTrue(report['verifier_result']['criteria']);self.assertFalse(report['agent_result']['used_as_verifier_score'])
        for criterion in report['verifier_result']['criteria']:
            if criterion['state']=='PASS':self.assertTrue(criterion.get('artifact_id'));self.assertTrue(criterion.get('resource_uri'))
