"""Independent deterministic artifact judge and centrally dispatched fixture runner.

WindowsWorld table semantics / OSWorld conjunction and checkpoints / Arena VM
trajectory patterns. No agent code replay, model judge or hidden postconfig.
"""
from __future__ import annotations
import hashlib
import inspect
import json
import math
import tempfile
import time
import uuid
from dataclasses import dataclass,field
from pathlib import Path
from .documents import DocumentBinding,verify_artifact
from .guest_process import declaration
from .identity_sessions import SessionExecutor,SessionScope
from .rpa import AuthorizedPaths,ExecutorFailure,effect_checkpoint,atomic_output,digest


@dataclass(frozen=True)
class ExpectedArtifact:
    key:str
    path:str
    sha256:str
    def __post_init__(self):
        if not self.key or not Path(self.path).is_absolute() or len(self.sha256)!=64 or any(c not in '0123456789abcdef' for c in self.sha256):raise ValueError('pinned_expected_artifact_required')


@dataclass(frozen=True)
class ArtifactCriterion:
    criterion_id:str
    actual_key:str
    expected_key:str
    metric:str='bytes'
    options:dict=field(default_factory=dict)
    def __post_init__(self):
        if not self.criterion_id or not self.actual_key or not self.expected_key or self.metric not in {'bytes','table','excel','pdf','json'}:raise ValueError('typed_artifact_criterion_required')
        object.__setattr__(self,'options',json.loads(json.dumps(self.options,allow_nan=False)))


@dataclass(frozen=True)
class VerifierCase:
    case_id:str
    criteria:tuple[ArtifactCriterion,...]
    conjunction:str='and'
    short_circuit:bool=False
    def __post_init__(self):
        if not self.case_id or not 1<=len(self.criteria)<=32 or self.conjunction not in {'and','or'} or len({c.criterion_id for c in self.criteria})!=len(self.criteria):raise ValueError('invalid_acceptance_case')


@dataclass(frozen=True)
class BenchmarkVerifierBinding:
    capability_id:str
    actual_paths:AuthorizedPaths
    expected_paths:AuthorizedPaths
    output_paths:AuthorizedPaths
    expected:tuple[ExpectedArtifact,...]
    cases:tuple[VerifierCase,...]
    max_artifact_bytes:int=32*1024*1024
    timeout_seconds:float=45
    def __post_init__(self):
        if not self.capability_id or not self.expected or not self.cases or len({c.case_id for c in self.cases})!=len(self.cases) or len({e.key for e in self.expected})!=len(self.expected):raise ValueError('invalid_independent_verifier_inventory')
        keys={e.key for e in self.expected}
        if any(c.expected_key not in keys for case in self.cases for c in case.criteria):raise ValueError('unknown_pinned_expected_artifact')
        # Expected files must never be under an agent-writable output root.
        for item in self.expected:
            path=self.expected_paths.resolve(item.path)
            if any(path.is_relative_to(Path(root)) for root in self.output_paths.write_roots):raise ValueError('golden_inside_agent_output_scope')


def _json_metric(actual,expected,options):
    if set(options)-{'keys','ignore_extra_keys'}:raise ExecutorFailure('unsupported_json_metric_options')
    a=json.loads(actual.read_text(encoding='utf-8'));e=json.loads(expected.read_text(encoding='utf-8'))
    if options.get('keys'):
        keys=options['keys']
        if not isinstance(keys,list) or any(type(k) is not str for k in keys) or not isinstance(a,dict) or not isinstance(e,dict):raise ExecutorFailure('json_key_projection_invalid')
        if any(k not in a or k not in e for k in keys):return {'passed':False,'score':0.0,'reason':'missing_json_key'}
        a={k:a[k] for k in keys};e={k:e[k] for k in keys}
    elif options.get('ignore_extra_keys') and isinstance(a,dict) and isinstance(e,dict):a={k:a[k] for k in e if k in a}
    passed=a==e;return {'passed':passed,'score':float(passed),'reason':'json_equal' if passed else 'json_differ','deterministic':True}


def verify_case(binding,case,actuals):
    """Judge bounded immutable snapshots, not executor self-reported success."""
    expected={e.key:e for e in binding.expected};results=[];decisive=False
    with tempfile.TemporaryDirectory(prefix='sentra-independent-verifier-') as directory:
        root=Path(directory);paths=AuthorizedPaths((str(root.resolve()),),())
        db=DocumentBinding('independent-artifact-judge',paths,max_input_bytes=binding.max_artifact_bytes)
        for criterion in case.criteria:
            if decisive:
                results.append({'criterion_id':criterion.criterion_id,'state':'NOT_EVALUATED','reason':'explicit_short_circuit'});continue
            start=time.perf_counter();record={'criterion_id':criterion.criterion_id,'actual_key':criterion.actual_key,'metric':criterion.metric}
            try:
                effect_checkpoint();golden=expected[criterion.expected_key];ep=binding.expected_paths.resolve(golden.path)
                if ep.stat().st_size>binding.max_artifact_bytes:raise ExecutorFailure('expected_artifact_size_limit')
                golden_bytes=ep.read_bytes()
                if hashlib.sha256(golden_bytes).hexdigest()!=golden.sha256:raise ExecutorFailure('expected_artifact_pin_changed')
                item=actuals.get(criterion.actual_key)
                if item is None:record.update(state='FAIL',score=0.0,passed=False,reason='actual_artifact_missing')
                else:
                    ap=binding.actual_paths.resolve(item['path'])
                    if ap.stat().st_size>binding.max_artifact_bytes:raise ExecutorFailure('actual_artifact_size_limit')
                    actual_bytes=ap.read_bytes();actual_sha=hashlib.sha256(actual_bytes).hexdigest()
                    if actual_sha!=item['sha256']:raise ExecutorFailure('actual_artifact_changed_since_capture')
                    left=root/('actual'+ap.suffix.lower());right=root/('expected'+ep.suffix.lower())
                    left.write_bytes(actual_bytes);right.write_bytes(golden_bytes)
                    metric=_json_metric(left,right,criterion.options) if criterion.metric=='json' else verify_artifact(
                        db,str(left),str(right),metric=criterion.metric,options=criterion.options,expected_sha256=golden.sha256)
                    record.update(metric,state='PASS' if metric['passed'] else 'FAIL',actual_sha256=actual_sha,
                                  expected_sha256=golden.sha256,artifact_id=item.get('artifact_id'),resource_uri=item.get('resource_uri'))
            except (ExecutorFailure,OSError,ValueError,KeyError) as exc:
                if isinstance(exc,ExecutorFailure) and exc.code=='effect_checkpoint_denied':raise
                record.update(state='EVALUATOR_ERROR',score=None,passed=False,
                              reason=exc.code if isinstance(exc,ExecutorFailure) else type(exc).__name__,
                              diagnosis=exc.evidence if isinstance(exc,ExecutorFailure) else {})
            record['latency_ms']=round((time.perf_counter()-start)*1000,3);results.append(record)
            if case.short_circuit and record['state']!='EVALUATOR_ERROR':
                decisive=(case.conjunction=='and' and not record['passed']) or (case.conjunction=='or' and record['passed'])
    errors=[r for r in results if r['state']=='EVALUATOR_ERROR'];evaluated=[r for r in results if r['state'] in {'PASS','FAIL'}]
    scores=[r['score'] for r in evaluated]
    score=None if errors or not scores else (math.prod(scores) if case.conjunction=='and' else max(scores))
    passed=score==1.0 if score is not None else False
    return {'case_id':case.case_id,'state':'EVALUATOR_ERROR' if errors else 'PASS' if passed else 'FAIL',
            'score':score,'passed':passed,'criteria':results,'conjunction':case.conjunction,
            'deterministic':True,'environment_mutated':False,'executor_success_used_as_score':False}


class BenchmarkVerifierExecutor(SessionExecutor):
    kind='benchmark_verifier'
    def __init__(self,*,machine_id,owner_principal_id,bindings,policy=None):
        super().__init__(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings={b.capability_id:b for b in bindings},policy=policy)
    def _validate(self,request,b):
        a=dict(request.arguments)
        if set(a)-{'action','case_id','actuals','output'} or a.get('action')!='verify' or a.get('case_id') not in {c.case_id for c in b.cases} or not isinstance(a.get('actuals'),dict) or len(a['actuals'])>32:raise ValueError('preconfigured_benchmark_verifier_required')
        for key,value in a['actuals'].items():
            if not isinstance(key,str) or not isinstance(value,dict) or set(value)-{'path','sha256','artifact_id','resource_uri'} or not isinstance(value.get('sha256'),str) or len(value['sha256'])!=64:raise ValueError('captured_actual_artifact_required')
            value['path']=str(b.actual_paths.resolve(value.get('path')))
        if 'output' in a:a['output']=str(b.output_paths.resolve(a['output'],write=True))
        a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id;return json.loads(json.dumps(a,allow_nan=False))
    def _run(self,b,a):
        result=verify_case(b,next(c for c in b.cases if c.case_id==a['case_id']),a['actuals'])
        if 'output' in a:
            data=json.dumps(result,ensure_ascii=False,allow_nan=False).encode()
            result['report_artifact']=atomic_output(b.output_paths,a['output'],lambda p:p.write_bytes(data),
                lambda p:json.loads(p.read_text(encoding='utf-8')),max_output_bytes=2*1024*1024)
        return result


def declare_benchmark_verifier_machine(*,machine_id,owner_principal_id,bindings,policy=None):
    executor=BenchmarkVerifierExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings=bindings,policy=policy)
    return declaration(executor,bindings,'Independent pinned artifact verifier with structured composite criteria')


@dataclass(frozen=True)
class ReceiptField:
    step_id:str
    keys:tuple[str|int,...]


@dataclass(frozen=True)
class AcceptanceStep:
    step_id:str
    machine_id:str
    capability_id:str
    arguments:dict
    phase:str='execute'  # reset, prepare, execute, collect, verify, cleanup


@dataclass(frozen=True)
class AcceptanceCasePlan:
    case_id:str
    work_item_id:str
    environment_version:str
    observation_mode:str
    steps:tuple[AcceptanceStep,...]
    reset_snapshot_id:str
    def __post_init__(self):
        if not self.case_id or not self.work_item_id or not self.environment_version or self.observation_mode not in {'uia','hybrid'} or not self.reset_snapshot_id:
            raise ValueError('versioned_fixture_case_required')
        if not 1<=len(self.steps)<=64 or len({s.step_id for s in self.steps})!=len(self.steps) or self.steps[0].phase!='reset' or not any(s.phase=='verify' for s in self.steps):raise ValueError('reset_and_independent_verifier_steps_required')
        if any(s.phase not in {'reset','prepare','execute','collect','verify','cleanup'} for s in self.steps):raise ValueError('invalid_acceptance_phase')
        if self.observation_mode=='hybrid' and not any(s.arguments.get('action')=='screenshot' for s in self.steps):raise ValueError('hybrid_requires_real_image_observation_step')


class AcceptanceRunner:
    """Host wiring must dispatch EACH step through the central factory.

    Runner cannot invent Run/grants or independently perform hardware I/O.
    Stops on UNCERTAIN. Cleanup is a distinct freshly authorized operation.
    """
    def __init__(self,dispatch,*,prepare_after_reset=None,after_step=None):
        if not callable(dispatch):raise ValueError('central_acceptance_dispatch_required')
        self.dispatch=dispatch;self.prepare=prepare_after_reset;self.after_step=after_step
    def _resolve(self,value,evidence):
        if isinstance(value,ReceiptField):
            item=evidence[value.step_id]
            for key in value.keys:item=item[key]
            return item
        if isinstance(value,dict):return {k:self._resolve(v,evidence) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [self._resolve(v,evidence) for v in value]
        return value
    async def run(self,*,run_id,plans):
        if not run_id or not 1<=len(plans)<=100:raise ValueError('bounded_acceptance_run_required')
        if len({p.case_id for p in plans})!=len(plans):raise ValueError('duplicate_acceptance_case')
        reports=[]
        for plan in plans:
            started=time.perf_counter();history=[];receipts={};state='INCOMPLETE';verdict=None
            for step in plan.steps:
                operation=run_id+':acceptance:'+uuid.uuid4().hex
                phase_start=time.perf_counter()
                try:
                    arguments=self._resolve(step.arguments,receipts)
                    result=await self.dispatch(run_id=run_id,work_item_id=plan.work_item_id,machine_id=step.machine_id,
                        capability_id=step.capability_id,operation_id=operation,arguments=arguments)
                    event={'step_id':step.step_id,'phase':step.phase,'operation_id':operation,'state':result.state,
                           'error':result.error,'evidence':dict(result.evidence),'latency_ms':round((time.perf_counter()-phase_start)*1000,3)}
                    history.append(event)
                    if result.state!='SUCCEEDED':state='EXECUTOR_'+result.state;break
                    receipts[step.step_id]=dict(result.evidence)
                    if self.after_step:
                        value=self.after_step(plan,step,result.evidence)
                        if inspect.isawaitable(value):await value
                    if step.phase=='reset':
                        if result.evidence.get('snapshot_id')!=plan.reset_snapshot_id:state='FIXTURE_MISMATCH';break
                        if self.prepare:
                            value=self.prepare(plan,result.evidence)
                            if inspect.isawaitable(value):await value
                    if step.phase=='verify':
                        verdict=result.evidence
                        if (verdict.get('executor_success_used_as_score') is not False or verdict.get('deterministic') is not True or
                                not isinstance(verdict.get('criteria'),list) or not verdict['criteria'] or verdict.get('state') not in {'PASS','FAIL','EVALUATOR_ERROR'}):
                            state='VERIFIER_CONTRACT_ERROR';break
                        if verdict.get('state')=='EVALUATOR_ERROR':state='EVALUATOR_ERROR';break
                        state='PASS' if verdict.get('passed') is True else 'FAIL'
                except Exception as exc:
                    history.append({'step_id':step.step_id,'phase':step.phase,'operation_id':operation,'state':'DISPATCH_ERROR','exception_type':type(exc).__name__})
                    state='DISPATCH_ERROR';break
            reports.append({'case_id':plan.case_id,'state':state,'verifier':verdict,'trajectory':history,
                'environment_version':plan.environment_version,'observation_mode':plan.observation_mode,'reset_snapshot_id':plan.reset_snapshot_id,
                'latency_ms':round((time.perf_counter()-started)*1000,3)})
        passed=sum(c['state']=='PASS' for c in reports)
        return {'run_id':run_id,'total':len(reports),'passed':passed,'success_rate':passed/len(reports),'cases':reports,
                'central_dispatch_required':True,'provider_runtime_attestation':'not_inferred_from_dispatch_state'}


def forms_acceptance_plan(*,case_id,work_item_id,environment_version,snapshot_id,fixture_machine_id,fixture_capability_id,
                          uia_machine_id,uia_capability_id,collector_machine_id,collector_capability_id,
                          verifier_machine_id,verifier_capability_id,result_output,identity_output,expected_value,
                          observation_mode='uia',screenshot_output=None,report_output=None):
    """Fixed host-owned recipe; selector order InputValue/SaveResult/ResultStatus.

    after_step on identity collection must commission the live UIA binding from
    the protected guest receipt and invalidate all prior references after reset.
    """
    steps=[
        AcceptanceStep('reset',fixture_machine_id,fixture_capability_id,{'action':'reset'},'reset'),
        AcceptanceStep('prepare',fixture_machine_id,fixture_capability_id,{'action':'prepare'},'prepare'),
        AcceptanceStep('identity',collector_machine_id,collector_capability_id,{'action':'collect','artifact_key':'fixture_identity','output':identity_output},'prepare'),
        AcceptanceStep('baseline',uia_machine_id,uia_capability_id,{'action':'wait','selector_key':'status','expected':{'text':'Not saved'},'wait_seconds':5}),
        AcceptanceStep('observe-input',uia_machine_id,uia_capability_id,{'action':'observe'}),
        AcceptanceStep('fill',uia_machine_id,uia_capability_id,{'action':'set_value','reference':ReceiptField('observe-input',('elements',0,'reference')),'value':expected_value}),
        AcceptanceStep('observe-save',uia_machine_id,uia_capability_id,{'action':'observe'}),
        AcceptanceStep('save',uia_machine_id,uia_capability_id,{'action':'invoke','reference':ReceiptField('observe-save',('elements',1,'reference'))}),
        AcceptanceStep('semantic-result',uia_machine_id,uia_capability_id,{'action':'wait','selector_key':'status','expected':{'text':'Saved: '+expected_value},'wait_seconds':5}),
    ]
    if observation_mode=='hybrid':
        if not screenshot_output:raise ValueError('hybrid_screenshot_output_required')
        steps.append(AcceptanceStep('image',uia_machine_id,uia_capability_id,{'action':'screenshot','output':screenshot_output}))
    steps.append(AcceptanceStep('collect',collector_machine_id,collector_capability_id,{'action':'collect','artifact_key':'result_csv','output':result_output},'collect'))
    actual={key:ReceiptField('collect',(key,)) for key in ('path','sha256','artifact_id','resource_uri')}
    arguments={'action':'verify','case_id':case_id,'actuals':{'result_csv':actual}}
    if report_output:arguments['output']=report_output
    steps.append(AcceptanceStep('independent-verifier',verifier_machine_id,verifier_capability_id,arguments,'verify'))
    return AcceptanceCasePlan(case_id,work_item_id,environment_version,observation_mode,tuple(steps),snapshot_id)
