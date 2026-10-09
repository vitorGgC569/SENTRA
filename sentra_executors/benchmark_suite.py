"""Configured dataset attempts with durable step intents and NO uncertain replay.

The local journal is recovery state, NOT central authorization. Actual request
binding, effect admission/fencing, dispatch, checkpoints and recovery are supplied
by trusted host callbacks around its existing central factory.
"""
from __future__ import annotations
import dataclasses
import inspect
import json
import math
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from sentra_runtime.contracts import OperationRequest,OperationResult,PolicyDecision
from .benchmark_acceptance import AcceptanceCasePlan,AcceptanceRunner,ReceiptField
from .benchmark_dataset import canonical,fingerprint,asset_requirements
from .benchmark_dataset_metrics import compile_source_metrics,source_metric_specs,validate_asset
from .rpa import AuthorizedPaths,ExecutorFailure,effect_checkpoint


@dataclass(frozen=True)
class DatasetTaskRegistration:
    task_key:str
    payload_sha256:str
    setup_sha256:str
    evaluator_sha256:str
    fixture_id:str
    snapshot_id:str
    provider_ids:tuple[str,...]
    environment_version:str
    contracts:tuple
    assets:tuple
    plan_factory:object
    verifier_machine_id:str
    verifier_capability_id:str
    setup_handling:str='preconfigured_fixture'
    postconfig_handling:str='none'
    reviewed_python:bool=False
    def __post_init__(self):
        if not self.task_key or not callable(self.plan_factory) or not self.fixture_id or not self.snapshot_id or not self.provider_ids or not self.environment_version:
            raise ValueError('configured_fixture_plan_and_provider_required')
        if self.setup_handling not in {'preconfigured_fixture','explicit_host_steps'} or self.postconfig_handling not in {'none','explicit_actor_steps','included_in_prepared_snapshot'}:
            raise ValueError('explicit_setup_and_postconfig_handling_required')


@dataclass(frozen=True)
class FixtureReadiness:
    fixture_id:str
    snapshot_id:str
    epoch:int
    available_provider_ids:tuple[str,...]
    state:str
    evidence:dict
    def __post_init__(self):
        if self.state not in {'READY','UNAVAILABLE','UNSUPPORTED'} or type(self.epoch) is not int or self.epoch<1:raise ValueError('typed_host_fixture_readiness_required')


@dataclass(frozen=True)
class HostDatasetCallbacks:
    bind_request:object  # (context, intent) -> real OperationRequest (factory.dispatch_request)
    dispatch:object      # (context, request) -> real OperationResult (factory.submit)
    recover:object       # (context, request) -> durable read ONLY, never resubmit
    checkpoint:object    # (context, phase, request_or_none) -> PolicyDecision
    fixture_readiness:object  # (task, registration) -> FixtureReadiness from actual host provider
    verifier_contract:object  # (task, registration) -> registered contract digest
    after_step:object=None    # trusted binding/epoch updates, never hidden dataset setup
    def __post_init__(self):
        if any(not callable(getattr(self,name)) for name in ('bind_request','dispatch','recover','checkpoint','fixture_readiness','verifier_contract')):
            raise ValueError('real_central_dataset_callbacks_required')


def registration_contract_sha256(registration):
    return fingerprint({'task_key':registration.task_key,'payload_sha256':registration.payload_sha256,
        'setup_sha256':registration.setup_sha256,'evaluator_sha256':registration.evaluator_sha256,
        'contracts':[dataclasses.asdict(c) for c in registration.contracts],
        'assets':[dataclasses.asdict(a) for a in registration.assets],
        'fixture_id':registration.fixture_id,'snapshot_id':registration.snapshot_id,'providers':registration.provider_ids,
        'verifier_machine_id':registration.verifier_machine_id,'verifier_capability_id':registration.verifier_capability_id,
        'setup_handling':registration.setup_handling,'postconfig_handling':registration.postconfig_handling})


class DatasetSuiteState:
    def __init__(self,path,paths,*,source_roots):
        if not source_roots:raise ValueError('dataset_source_roots_required_for_write_exclusion')
        self.path=paths.resolve(path,write=True)
        if any(self.path.is_relative_to(Path(root).resolve()) for root in source_roots):raise ValueError('dataset_clone_state_write_denied')
        with self._db() as db:db.executescript('''
        CREATE TABLE IF NOT EXISTS dataset_attempts(
          id TEXT PRIMARY KEY,task_key TEXT,run_id TEXT,work_item_id TEXT,registration_sha TEXT,
          plan TEXT,state TEXT,fixture_epoch INTEGER,report TEXT,created_ns INTEGER);
        CREATE TABLE IF NOT EXISTS dataset_step_intents(
          attempt_id TEXT,step_index INTEGER,operation_id TEXT UNIQUE,intent TEXT,intent_sha TEXT,
          state TEXT,result TEXT,PRIMARY KEY(attempt_id,step_index));
        ''')
    def _db(self):
        db=sqlite3.connect(self.path,timeout=5);db.row_factory=sqlite3.Row;return db
    def get(self,attempt_id):
        with self._db() as db:
            row=db.execute('SELECT * FROM dataset_attempts WHERE id=?',(attempt_id,)).fetchone()
            if row is None:raise KeyError(attempt_id)
            steps=db.execute('SELECT * FROM dataset_step_intents WHERE attempt_id=? ORDER BY step_index',(attempt_id,)).fetchall()
        data=dict(row);data['plan']=json.loads(data['plan']);data['report']=json.loads(data['report']) if data['report'] else None
        data['intents']=[dict(s,intent=json.loads(s['intent']),result=json.loads(s['result']) if s['result'] else None) for s in steps];return data
    def create(self,attempt_id,task,registration,plan,run_id,work_item_id,epoch):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM dataset_attempts WHERE id=?',(attempt_id,)).fetchone()
            if old:raise ExecutorFailure('attempt_id_exists_use_resume')
            busy=db.execute("SELECT id FROM dataset_attempts WHERE run_id=? AND work_item_id=? AND state IN ('CREATED','EXECUTING','READY_TO_EVALUATE','UNCERTAIN') LIMIT 1",(run_id,work_item_id)).fetchone()
            if busy:raise ExecutorFailure('active_or_uncertain_attempt_requires_resume',evidence={'attempt_id':busy['id']})
            db.execute('INSERT INTO dataset_attempts VALUES(?,?,?,?,?,?,?,?,?,?)',(attempt_id,task.key,run_id,work_item_id,
                registration_contract_sha256(registration),canonical(plan),'CREATED',epoch,None,time.time_ns()))
    def reserve(self,attempt,index,intent):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM dataset_step_intents WHERE attempt_id=? AND step_index=?',(attempt,index)).fetchone()
            sha=fingerprint(intent)
            if old:
                if old['intent_sha']!=sha:raise ExecutorFailure('dataset_step_intent_conflict')
                return dict(old)
            db.execute('INSERT INTO dataset_step_intents VALUES(?,?,?,?,?,?,NULL)',(attempt,index,intent['operation_id'],canonical(intent),sha,'RESERVED'))
        return {'state':'RESERVED','operation_id':intent['operation_id'],'intent_sha':sha}
    def step(self,attempt,index,state,result=None):
        with self._db() as db:db.execute('UPDATE dataset_step_intents SET state=?,result=? WHERE attempt_id=? AND step_index=?',
            (state,canonical(result) if result is not None else None,attempt,index))
    def claim_dispatch(self,attempt,index):
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            count=db.execute("UPDATE dataset_step_intents SET state='DISPATCHING' WHERE attempt_id=? AND step_index=? AND state='RESERVED'",(attempt,index)).rowcount
        return count==1
    def epoch(self,attempt,epoch):
        with self._db() as db:db.execute('UPDATE dataset_attempts SET fixture_epoch=? WHERE id=?',(epoch,attempt))
    def finish(self,attempt,state,report=None):
        with self._db() as db:db.execute('UPDATE dataset_attempts SET state=?,report=? WHERE id=?',(state,canonical(report) if report is not None else None,attempt))


def _encode(value):
    if isinstance(value,ReceiptField):return {'$receipt_field':{'step_id':value.step_id,'keys':list(value.keys)}}
    if isinstance(value,dict):return {k:_encode(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [_encode(v) for v in value]
    return value
def _resolve(value,receipts):
    if isinstance(value,dict) and set(value)=={'$receipt_field'}:
        ref=value['$receipt_field'];current=receipts[ref['step_id']]
        for key in ref['keys']:current=current[key]
        return current
    if isinstance(value,dict):return {k:_resolve(v,receipts) for k,v in value.items()}
    if isinstance(value,list):return [_resolve(v,receipts) for v in value]
    return value


class DatasetEvaluationSuite:
    def __init__(self,*,catalog,registrations,state,callbacks,asset_paths):
        self.catalog=catalog;self.registrations={r.task_key:r for r in registrations};self.state=state;self.host=callbacks;self.asset_paths=asset_paths
        if len(self.registrations)!=len(registrations):raise ValueError('duplicate_dataset_registration')
        if any(state.path.is_relative_to(Path(s.clone_root).resolve()) for s in catalog.sources):raise ValueError('dataset_clone_state_write_denied')
    async def _call(self,fn,*args):
        value=fn(*args);return await value if inspect.isawaitable(value) else value
    async def _checkpoint(self,context,phase,request=None):
        effect_checkpoint();decision=await self._call(self.host.checkpoint,context,phase,request)
        if not isinstance(decision,PolicyDecision) or decision.allowed is not True:raise ExecutorFailure('central_dataset_checkpoint_denied')
    async def eligibility(self,key):
        task=self.catalog.get(key);r=self.registrations.get(key);reasons=list(task.indexing_issues)
        if r is None:reasons.append('task_not_bound_to_configured_fixture_provider_verifier');return {'supported':False,'evaluated':False,'reasons':reasons,'task':task.view()}
        if r.reviewed_python:reasons=[s for s in reasons if s!='python_task_requires_host_reviewed_translation']
        if (r.payload_sha256,r.setup_sha256,r.evaluator_sha256)!=(task.payload_sha256,task.setup_sha256,task.evaluator_sha256):reasons.append('configured_task_source_pin_changed')
        if task.payload.get('is_duplicate') or task.payload.get('validity_info',{}).get('is_valid') is False:reasons.append('source_marks_task_duplicate_or_invalid')
        postconfig=task.evaluator.get('postconfig',[])
        if postconfig and r.postconfig_handling=='none':reasons.append('postconfig_has_no_explicit_host_translation')
        try:
            self.catalog.revalidate(task)
            contracts,metric_reasons=compile_source_metrics(task,reviewed=tuple(c for c in r.contracts if c.origin=='host_reviewed'))
            if metric_reasons:reasons.extend(metric_reasons)
            expected_specs={fingerprint(s) for s in source_metric_specs(task)}
            if not expected_specs or {c.source_spec_sha256 for c in r.contracts}!=expected_specs:reasons.append('registered_metric_coverage_incomplete')
            compiled={c.source_spec_sha256:c for c in contracts}
            for c in r.contracts:
                if c.origin=='native_subset':
                    native=compiled.get(c.source_spec_sha256)
                    if native is None or dataclasses.replace(native,actual_key=c.actual_key,metric_id=c.metric_id)!=c:reasons.append('native_metric_contract_differs_from_source')
            pins={a.ref:a for a in r.assets}
            for required in asset_requirements(task):
                if required['purpose']=='fixture' and required['ref'] not in pins:reasons.append('fixture_asset_not_pinned:'+required['ref'])
            for c in r.contracts:
                if c.expected_ref not in pins:reasons.append('expected_asset_not_pinned:'+c.expected_ref)
            for pin in r.assets:validate_asset(pin,self.asset_paths)
        except (ExecutorFailure,OSError,ValueError) as exc:reasons.append(exc.code if isinstance(exc,ExecutorFailure) else type(exc).__name__)
        if reasons:return {'supported':False,'evaluated':False,'reasons':reasons,'task':task.view()}
        try:health=await self._call(self.host.fixture_readiness,task,r)
        except Exception as exc:
            return {'supported':False,'evaluated':False,'reasons':['fixture_readiness_unavailable:'+ (exc.code if isinstance(exc,ExecutorFailure) else type(exc).__name__)],'task':task.view()}
        if not isinstance(health,FixtureReadiness) or health.state!='READY' or health.fixture_id!=r.fixture_id or health.snapshot_id!=r.snapshot_id or not set(r.provider_ids)<=set(health.available_provider_ids):
            return {'supported':False,'evaluated':False,'reasons':['fixture_guest_or_provider_not_ready'],'task':task.view()}
        try:registration=await self._call(self.host.verifier_contract,task,r)
        except Exception as exc:
            return {'supported':False,'evaluated':False,'reasons':['verifier_registration_unavailable:'+type(exc).__name__],'task':task.view()}
        if registration!=registration_contract_sha256(r):return {'supported':False,'evaluated':False,'reasons':['independent_verifier_registration_not_matching'],'task':task.view()}
        return {'supported':True,'evaluated':False,'reasons':[],'task':task.view(),'fixture_epoch':health.epoch,'fixture_evidence':health.evidence}
    async def catalog_tasks(self,**filters):return [await self.eligibility(t.key) for t in self.catalog.select(**filters)]
    async def select(self,**filters):return tuple(row['task']['key'] for row in await self.catalog_tasks(**filters) if row['supported'])
    async def attempt(self,key,*,run_id,work_item_id,attempt_id):
        status=await self.eligibility(key)
        if not status['supported']:return dict(status,state='UNSUPPORTED',attempt_id=attempt_id)
        task=self.catalog.get(key);r=self.registrations[key];context={'run_id':run_id,'work_item_id':work_item_id,'attempt_id':attempt_id,'task_key':key}
        await self._checkpoint(context,'before_attempt')
        plan=await self._call(r.plan_factory,task,context)
        if not isinstance(plan,AcceptanceCasePlan) or plan.work_item_id!=work_item_id or plan.reset_snapshot_id!=r.snapshot_id or plan.environment_version!=r.environment_version:
            raise ValueError('host_dataset_plan_fixture_or_work_item_mismatch')
        if not plan.steps or plan.steps[0].phase!='reset':raise ValueError('explicit_reset_before_attempt_required')
        verify_steps=[s for s in plan.steps if s.phase=='verify']
        if not verify_steps or any((s.machine_id,s.capability_id)!=(r.verifier_machine_id,r.verifier_capability_id) for s in verify_steps):raise ValueError('independent_registered_verifier_steps_required')
        seen_verify=False
        for step in plan.steps:
            if step.phase=='verify':seen_verify=True
            elif seen_verify:raise ValueError('no_implicit_mutation_after_dataset_evaluation')
        encoded={'case_id':plan.case_id,'environment_version':plan.environment_version,'observation_mode':plan.observation_mode,
                 'snapshot_id':plan.reset_snapshot_id,'steps':[{'step_id':s.step_id,'machine_id':s.machine_id,'capability_id':s.capability_id,
                 'phase':s.phase,'arguments':_encode(s.arguments)} for s in plan.steps]}
        self.state.create(attempt_id,task,r,encoded,run_id,work_item_id,status['fixture_epoch'])
        return await self._run(attempt_id,evaluate=False)
    async def evaluate(self,attempt_id):return await self._run(attempt_id,evaluate=True)
    async def resume(self,attempt_id,*,evaluate=False):return await self._run(attempt_id,evaluate=evaluate,recover=True)
    async def _run(self,attempt_id,*,evaluate,recover=False):
        attempt=self.state.get(attempt_id);r=self.registrations[attempt['task_key']];task=self.catalog.get(attempt['task_key'])
        if attempt['state'] in {'PASS','FAIL','EVALUATOR_ERROR','UNSUPPORTED','EXECUTOR_FAILED'}:return self.report(attempt_id)
        eligible=await self.eligibility(task.key)
        if not eligible['supported']:return dict(eligible,state='UNSUPPORTED',attempt_id=attempt_id)
        if eligible['fixture_epoch']!=attempt['fixture_epoch']:raise ExecutorFailure('fixture_epoch_changed_requires_explicit_host_reconciliation')
        if attempt['registration_sha']!=registration_contract_sha256(r):raise ExecutorFailure('dataset_registration_changed_during_attempt')
        context={k:attempt[k] for k in ('run_id','work_item_id','task_key')};context['attempt_id']=attempt_id
        receipts={};old={s['step_index']:s for s in attempt['intents']};self.state.finish(attempt_id,'EXECUTING')
        for index,step in enumerate(attempt['plan']['steps']):
            previous=old.get(index)
            if previous and previous.get('result') and previous['result'].get('host_hook_reconciliation_required'):
                self.state.finish(attempt_id,'UNCERTAIN');raise ExecutorFailure('dataset_host_hook_reconciliation_required_no_implicit_retry')
            if previous and previous['state']=='SUCCEEDED':receipts[step['step_id']]=previous['result']['evidence'];continue
            if step['phase']=='verify' and not evaluate:
                self.state.finish(attempt_id,'READY_TO_EVALUATE');return self.report(attempt_id)
            if previous and previous['state'] in {'FAILED','DENIED','CANCELLED'}:
                self.state.finish(attempt_id,'EXECUTOR_FAILED');return self.report(attempt_id)
            arguments=_resolve(step['arguments'],receipts)
            if 'output' in arguments and any(Path(arguments['output']).resolve().is_relative_to(Path(s.clone_root).resolve()) for s in self.catalog.sources):raise ExecutorFailure('dataset_source_output_denied')
            operation=previous['operation_id'] if previous else 'dataset:'+attempt_id+':'+str(index)
            intent={'operation_id':operation,'principal_id':None,'run_id':attempt['run_id'],'work_item_id':attempt['work_item_id'],
                'machine_id':step['machine_id'],'capability_id':step['capability_id'],'arguments':arguments,'idempotency_key':operation}
            # Host binds actual principal, never a caller supplied principal ID.
            await self._checkpoint(context,'before_'+step['phase'])
            request=await self._call(self.host.bind_request,context,intent)
            if not isinstance(request,OperationRequest) or (request.operation_id,request.machine_id,request.capability_id,request.work_item_id,request.idempotency_key)!=(operation,step['machine_id'],step['capability_id'],attempt['work_item_id'],operation) or canonical(dict(request.arguments))!=canonical(arguments):
                raise ExecutorFailure('central_bound_dataset_request_mismatch')
            intent['principal_id']=request.principal_id
            reserved=self.state.reserve(attempt_id,index,intent)
            await self._checkpoint(context,'dispatch_'+step['phase'],request)
            started=time.perf_counter()
            if reserved['state'] in {'DISPATCHING','UNCERTAIN','RUNNING','PENDING','ACCEPTED'}:
                if not recover:
                    self.state.finish(attempt_id,'UNCERTAIN');return self.report(attempt_id)
                result=await self._call(self.host.recover,context,request)
            else:
                if reserved['state']!='RESERVED' or not self.state.claim_dispatch(attempt_id,index):
                    self.state.finish(attempt_id,'UNCERTAIN');return self.report(attempt_id)
                try:result=await self._call(self.host.dispatch,context,request)
                except BaseException:
                    self.state.step(attempt_id,index,'UNCERTAIN');self.state.finish(attempt_id,'UNCERTAIN');raise
            if not isinstance(result,OperationResult) or result.operation_id!=operation:
                self.state.step(attempt_id,index,'UNCERTAIN');self.state.finish(attempt_id,'UNCERTAIN');raise ExecutorFailure('typed_central_dataset_result_required')
            stored={'state':result.state,'error':result.error,'evidence':dict(result.evidence),'operation_id':operation,
                    'phase':step['phase'],'latency_ms':round((time.perf_counter()-started)*1000,3),'recovered_without_dispatch':reserved['state'] in {'DISPATCHING','UNCERTAIN','RUNNING','PENDING','ACCEPTED'}}
            self.state.step(attempt_id,index,result.state,stored)
            if result.state!='SUCCEEDED':
                self.state.finish(attempt_id,'UNCERTAIN' if result.state in {'UNCERTAIN','RUNNING','PENDING'} else 'EXECUTOR_FAILED');return self.report(attempt_id)
            receipts[step['step_id']]=stored['evidence']
            if step['phase']=='reset' and result.evidence.get('snapshot_id')!=r.snapshot_id:
                self.state.finish(attempt_id,'EXECUTOR_FAILED');raise ExecutorFailure('dataset_reset_snapshot_mismatch')
            if self.host.after_step:
                try:await self._call(self.host.after_step,context,step,result)
                except BaseException:
                    stored['host_hook_reconciliation_required']=True
                    self.state.step(attempt_id,index,'UNCERTAIN',stored);self.state.finish(attempt_id,'UNCERTAIN');raise
            if step['phase']=='reset':
                health=await self._call(self.host.fixture_readiness,task,r)
                if not isinstance(health,FixtureReadiness) or health.state!='READY' or health.fixture_id!=r.fixture_id or health.snapshot_id!=r.snapshot_id:
                    self.state.finish(attempt_id,'UNCERTAIN');raise ExecutorFailure('post_reset_fixture_revalidation_required')
                self.state.epoch(attempt_id,health.epoch)
        return self._finalize(attempt_id,task,r)
    def _finalize(self,attempt_id,task,r):
        attempt=self.state.get(attempt_id);verifications=[s['result']['evidence'] for s in attempt['intents'] if s['result'] and s['result']['phase']=='verify' and s['state']=='SUCCEEDED']
        if not verifications:raise ExecutorFailure('independent_dataset_evaluation_not_executed')
        verdict=verifications[-1];criteria=verdict.get('criteria',[])
        valid=(verdict.get('deterministic') is True and verdict.get('executor_success_used_as_score') is False and
            verdict.get('source_payload_sha256')==task.payload_sha256 and isinstance(criteria,list) and
            all(isinstance(c,dict) for c in criteria) and
            {c.get('source_spec_sha256') for c in criteria}=={c.source_spec_sha256 for c in r.contracts})
        if verdict.get('state')=='UNSUPPORTED' and verdict.get('evaluated') is False:state='UNSUPPORTED'
        elif not valid:state='EVALUATOR_ERROR'
        elif verdict.get('evaluated') is not True:state='UNSUPPORTED' if verdict.get('state')=='UNSUPPORTED' else 'EVALUATOR_ERROR'
        elif type(verdict.get('score')) not in (int,float) or not math.isfinite(verdict['score']) or not 0<=verdict['score']<=1:state='EVALUATOR_ERROR'
        else:state='PASS' if verdict['score']==1 else 'FAIL'
        self.state.finish(attempt_id,state,{'verifier_result':verdict,'evaluated':state in {'PASS','FAIL'}})
        return self.report(attempt_id)
    def report(self,attempt_id):
        a=self.state.get(attempt_id);task=self.catalog.get(a['task_key']);r=self.registrations[task.key]
        verdict=(a['report'] or {}).get('verifier_result');evaluated=bool((a['report'] or {}).get('evaluated'))
        return {'attempt_id':attempt_id,'run_id':a['run_id'],'work_item_id':a['work_item_id'],'state':a['state'],'evaluated':evaluated,
            'score':verdict.get('score') if evaluated else None,'agent_result':self._agent_result(a),
            'reasons':[verdict['reason']] if verdict and verdict.get('reason') else [],
            'verifier_result':verdict,'source':task.view(),'environment_version':a['plan']['environment_version'],
            'snapshot_id':r.snapshot_id,'fixture_epoch':a['fixture_epoch'],'registration_sha256':a['registration_sha'],
            'plan_sha256':fingerprint(a['plan']),
            'expected_assets':[dataclasses.asdict(pin) for pin in r.assets if pin.ref in {c.expected_ref for c in r.contracts}],
            'trajectory':[s['result'] or {'operation_id':s['operation_id'],'state':s['state']} for s in a['intents']],
            'latency_ms':sum(s['result'].get('latency_ms',0) for s in a['intents'] if s['result']),
            'runtime_attestation':'not_inferred_from_callback_state'}
    def _agent_result(self,attempt):
        steps=[s for s in attempt['intents'] if s['result'] and s['result']['phase']!='verify']
        return {'execution_states':[s['state'] for s in steps],'completed_steps':sum(s['state']=='SUCCEEDED' for s in steps),
                'used_as_verifier_score':False}
