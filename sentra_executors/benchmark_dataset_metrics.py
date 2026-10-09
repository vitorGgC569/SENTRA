"""Pinned independent metrics over captured artifacts, not agent testimony."""
from __future__ import annotations
import hashlib
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from .benchmark_dataset import canonical,fingerprint,asset_requirements
from .documents import DocumentBinding,verify_artifact,read_verifier_table,compare_tables
from .rpa import AuthorizedPaths,ExecutorFailure,effect_checkpoint


@dataclass(frozen=True)
class DatasetAssetPin:
    ref:str
    path:str
    sha256:str
    purpose:str='expected'
    def __post_init__(self):
        if not self.ref or not Path(self.path).is_absolute() or len(self.sha256)!=64 or any(c not in '0123456789abcdef' for c in self.sha256):raise ValueError('dataset_asset_pin_required')


@dataclass(frozen=True)
class DatasetMetricContract:
    metric_id:str
    source_function:str
    source_spec_sha256:str
    actual_key:str
    expected_ref:str
    kind:str
    options_json:str='{}'
    inline_expected_json:str|None=None
    origin:str='native_subset'
    def __post_init__(self):
        if self.kind not in {'json_subset','saved_text','csv_lines','bytes','json','table','excel','pdf','table_sorted'} or self.origin not in {'native_subset','host_reviewed'}:
            raise ValueError('unsupported_dataset_metric_contract')
        json.loads(self.options_json)
    @property
    def options(self):return json.loads(self.options_json)


def source_metric_specs(task):
    if task.source.layout=='osworld-v2-python':
        p=task.payload;method=p.get('_python_methods',{}).get('evaluate')
        return [{'func':'python_evaluate','source_sha256':p.get('_python_source_sha256'),'method_ast_sha256':method}] if method else []
    evaluator=task.evaluator
    if task.source.layout=='windowsworld-array':
        specs=[{'func':'semantic_final','goal':evaluator.get('success_criterion'),'expected_final_state':evaluator.get('expected_final_state')}]
        specs.extend({'func':'semantic_intermediate','goal':goal,'index':i} for i,goal in enumerate(evaluator.get('intermediate_checks',[])))
        return specs
    functions=evaluator.get('func');functions=functions if isinstance(functions,list) else [functions]
    if not functions or functions==[None]:return []
    fields={name:evaluator.get(name) for name in ('result','expected','options')}
    specs=[]
    for index,function in enumerate(functions):
        spec={'func':function,'index':index}
        for name,value in fields.items():
            if isinstance(evaluator.get('func'),list):
                if value is not None and (not isinstance(value,list) or len(value)!=len(functions)):raise ExecutorFailure('upstream_metric_parallel_arrays_mismatch')
                spec[name]=value[index] if value is not None else None
            else:spec[name]=value
        specs.append(spec)
    return specs


def compile_source_metrics(task,*,reviewed=()):
    """Translate only exact known semantics; unknown rules retain unsupported."""
    contracts=[];reasons=[];reviews={c.source_spec_sha256:c for c in reviewed}
    specs=source_metric_specs(task)
    if not specs:return (),('source_has_no_declarative_metric_requires_reviewed_python_adapter',)
    for index,spec in enumerate(specs):
        sha=fingerprint(spec);function=spec['func'];result=spec.get('result') or {};expected=spec.get('expected') or {};options=spec.get('options') or {}
        actual_key='metric-'+str(index);metric_id='source-metric-'+str(index)
        if sha in reviews:
            c=reviews[sha]
            if c.origin!='host_reviewed' or c.source_function!=function:raise ValueError('reviewed_metric_does_not_cover_source_spec')
            contracts.append(c);continue
        if not all(isinstance(v,dict) for v in (result,expected,options)):
            reasons.append('metric_getter_or_options_shape_requires_adapter:'+str(function));continue
        ref=expected.get('path',expected.get('url')) if isinstance(expected,dict) else None
        inline=None
        if isinstance(expected,dict) and expected.get('type')=='rule':
            rules=expected.get('rules',{});ref='inline://'+task.key+'/'+fingerprint(rules)
            inline=canonical(rules.get('expected'))
        if function=='check_json_settings' and result.get('type')=='vm_file' and expected.get('type')=='rule' and isinstance(expected.get('rules',{}).get('expected'),dict) and not options:
            c=DatasetMetricContract(metric_id,function,sha,actual_key,ref,'json_subset',inline_expected_json=inline)
        elif function=='exact_match' and result.get('type')=='is_file_saved_desktop' and type(result.get('textcontent')) is str and inline=='"true"' and not options:
            c=DatasetMetricContract(metric_id,function,sha,actual_key,ref,'saved_text',canonical({'required_text':result['textcontent']}),inline)
        elif function=='compare_csv' and result.get('type')=='vm_file' and ref and set(options)<={'strict','ignore_case'} and all(type(v) is bool for v in options.values()):
            c=DatasetMetricContract(metric_id,function,sha,actual_key,ref,'csv_lines',canonical(options))
        else:
            reasons.append('metric_requires_configured_adapter:'+str(function)+':'+sha);continue
        contracts.append(c)
    return tuple(contracts),tuple(reasons)


def inline_expected_assets(task,contracts):
    """Return expected bytes for explicit host provisioning OUTSIDE clone."""
    return {c.expected_ref:c.inline_expected_json.encode('utf-8') for c in contracts if c.inline_expected_json is not None}


def validate_asset(asset,paths,*,max_bytes=32*1024*1024):
    effect_checkpoint();path=paths.resolve(asset.path)
    if path.stat().st_size>max_bytes:raise ExecutorFailure('dataset_asset_size_limit')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=asset.sha256:raise ExecutorFailure('dataset_asset_pin_changed',evidence={'ref':asset.ref})
    return path,data


def judge_dataset_task(task,contracts,actuals,assets,*,actual_paths,expected_paths,max_bytes=32*1024*1024):
    """Independent result; absent expected is NOT pass or evaluated failure."""
    pins={a.ref:a for a in assets};records=[];expected_missing=[]
    specs=source_metric_specs(task)
    needed={fingerprint(s) for s in specs}
    if not contracts or {c.source_spec_sha256 for c in contracts}!=needed:
        return {'state':'UNSUPPORTED','evaluated':False,'score':None,'reason':'source_metric_coverage_incomplete','criteria':[]}
    for c in contracts:
        if c.expected_ref not in pins:expected_missing.append(c.expected_ref)
    if expected_missing:return {'state':'UNSUPPORTED','evaluated':False,'score':None,'reason':'expected_assets_not_pinned','missing_expected':expected_missing,'criteria':[]}
    with tempfile.TemporaryDirectory(prefix='sentra-dataset-judge-') as directory:
        root=Path(directory).resolve();document=DocumentBinding('dataset-independent',AuthorizedPaths((str(root),),()),max_input_bytes=max_bytes)
        for index,c in enumerate(contracts):
            record={'criterion_id':c.metric_id,'source_function':c.source_function,'source_spec_sha256':c.source_spec_sha256,
                    'metric_origin':c.origin,'actual_key':c.actual_key,'expected_ref':c.expected_ref}
            try:
                ep,expected=validate_asset(pins[c.expected_ref],expected_paths,max_bytes=max_bytes)
                if c.inline_expected_json is not None and canonical(json.loads(expected))!=c.inline_expected_json:raise ExecutorFailure('inline_expected_differs_from_source_rule')
                item=actuals.get(c.actual_key)
                if item is None:
                    result={'passed':False,'score':0.0,'reason':'actual_artifact_missing'}
                else:
                    effect_checkpoint();ap=actual_paths.resolve(item['path'])
                    if ap.stat().st_size>max_bytes:raise ExecutorFailure('dataset_actual_size_limit')
                    actual=ap.read_bytes();sha=hashlib.sha256(actual).hexdigest()
                    if sha!=item['sha256']:raise ExecutorFailure('dataset_actual_changed_since_capture')
                    if c.kind=='json_subset':
                        a=json.loads(actual);e=json.loads(expected);passed=isinstance(a,dict) and all(k in a and a[k]==v for k,v in e.items())
                        result={'passed':passed,'score':float(passed)}
                    elif c.kind=='saved_text':
                        present=c.options['required_text'] in actual.decode('utf-8-sig');desired=json.loads(expected)
                        passed=('true' if present else 'false')==desired;result={'passed':passed,'score':float(passed)}
                    elif c.kind=='csv_lines':
                        a=actual.decode('utf-8-sig').splitlines();e=expected.decode('utf-8-sig').splitlines()
                        if not c.options.get('strict',True):a=[v.strip() for v in a];e=[v.strip() for v in e]
                        if c.options.get('ignore_case',False):a=[v.lower() for v in a];e=[v.lower() for v in e]
                        passed=a==e;result={'passed':passed,'score':float(passed)}
                    else:
                        left=root/(str(index)+'actual'+ap.suffix);right=root/(str(index)+'expected'+ep.suffix)
                        left.write_bytes(actual);right.write_bytes(expected)
                        if c.kind=='table_sorted':
                            opts=c.options;columns,rows=read_verifier_table(left,document,sheet=opts.get('sheet'),value_mode=opts.get('value_mode','formulas'))
                            ec,er=read_verifier_table(right,document,sheet=opts.get('sheet'),value_mode=opts.get('value_mode','formulas'))
                            keys=opts['columns']
                            if not isinstance(keys,list) or not keys or any(k not in columns for k in keys):raise ExecutorFailure('configured_sort_columns_missing')
                            order=[tuple(str(row[k]) for k in keys) for row in rows]
                            preserved=compare_tables(columns,rows,ec,er,ignore_row_order=True)['passed']
                            sorted_ok=order==sorted(order,reverse=bool(opts.get('descending',False)))
                            result={'passed':preserved and sorted_ok,'score':float(preserved and sorted_ok),'rows_preserved':preserved,'order_verified':sorted_ok,
                                    'ordering_contract':'explicit_lexicographic_unicode','recomputed':False}
                        else:result=verify_artifact(document,str(left),str(right),metric=c.kind,options=c.options,expected_sha256=pins[c.expected_ref].sha256)
                    record.update(actual_sha256=sha,artifact_id=item.get('artifact_id'),resource_uri=item.get('resource_uri'))
                record.update(result,state='PASS' if result['passed'] else 'FAIL',expected_sha256=pins[c.expected_ref].sha256)
            except Exception as exc:
                if isinstance(exc,ExecutorFailure) and exc.code=='effect_checkpoint_denied':raise
                record.update(state='EVALUATOR_ERROR',passed=False,score=None,reason=exc.code if isinstance(exc,ExecutorFailure) else type(exc).__name__)
            records.append(record)
    errors=any(r['state']=='EVALUATOR_ERROR' for r in records)
    conjunction=task.evaluator.get('conj','and');scores=[r['score'] for r in records if r['score'] is not None]
    if conjunction not in {'and','or'}:return {'state':'UNSUPPORTED','evaluated':False,'score':None,'reason':'unsupported_conjunction','criteria':records}
    final_records=[r for r in records if r['source_function']=='semantic_final']
    intermediate=[r for r in records if r['source_function']=='semantic_intermediate']
    score=None if errors or not scores else (final_records[0]['score'] if task.source.layout=='windowsworld-array' and final_records else
        math.prod(scores) if conjunction=='and' else max(scores))
    return {'state':'EVALUATOR_ERROR' if errors else 'PASS' if score==1 else 'FAIL','evaluated':not errors,'score':score,'passed':score==1,
            'criteria':records,'deterministic':True,'executor_success_used_as_score':False,'environment_mutated':False,
            'official_metric_equivalence':'not_certified','source_algorithm_subset':all(c.origin=='native_subset' for c in contracts),
            'intermediate_score':None if errors or not intermediate else sum(r['score'] for r in intermediate)/len(intermediate),
            'source_payload_sha256':task.payload_sha256}


@dataclass(frozen=True)
class DatasetVerifierBinding:
    capability_id:str
    catalog:object
    task_contracts:dict
    task_assets:dict
    actual_paths:AuthorizedPaths
    expected_paths:AuthorizedPaths
    output_paths:AuthorizedPaths
    timeout_seconds:float=60
    def __post_init__(self):
        if not self.capability_id or set(self.task_contracts)!=set(self.task_assets):raise ValueError('configured_dataset_verifier_inventory_required')
        for pins in self.task_assets.values():
            for asset in pins:
                path=self.expected_paths.resolve(asset.path)
                if any(path.is_relative_to(Path(root)) for root in self.output_paths.write_roots):raise ValueError('expected_dataset_asset_is_agent_writable')


def declare_dataset_verifier_machine(*,machine_id,owner_principal_id,bindings,policy=None):
    from .identity_sessions import SessionExecutor
    from .guest_process import declaration
    from .rpa import atomic_output
    class DatasetVerifierExecutor(SessionExecutor):
        kind='benchmark_dataset_verifier'
        def _validate(self,request,b):
            a=dict(request.arguments)
            if set(a)-{'action','task_key','actuals','output'} or a.get('action')!='verify' or a.get('task_key') not in b.task_contracts or not isinstance(a.get('actuals'),dict) or len(a['actuals'])>64:raise ValueError('configured_dataset_metric_required')
            for value in a['actuals'].values():
                if not isinstance(value,dict) or set(value)-{'path','sha256','artifact_id','resource_uri'} or not isinstance(value.get('sha256'),str) or len(value['sha256'])!=64:raise ValueError('captured_dataset_actual_required')
                value['path']=str(b.actual_paths.resolve(value.get('path')))
            if 'output' in a:
                target=b.output_paths.resolve(a['output'],write=True)
                if any(target.is_relative_to(Path(s.clone_root).resolve()) for s in b.catalog.sources):raise ValueError('dataset_source_output_denied')
                a['output']=str(target)
            a['_operation_id']=request.operation_id;return json.loads(json.dumps(a,allow_nan=False))
        def _run(self,b,a):
            task=b.catalog.get(a['task_key']);b.catalog.revalidate(task)
            result=judge_dataset_task(task,b.task_contracts[task.key],a['actuals'],b.task_assets[task.key],
                actual_paths=b.actual_paths,expected_paths=b.expected_paths)
            if 'output' in a:
                raw=canonical(result).encode();result['report_artifact']=atomic_output(b.output_paths,a['output'],lambda p:p.write_bytes(raw),
                    lambda p:json.loads(p.read_text(encoding='utf-8')),max_output_bytes=4*1024*1024)
            return result
    executor=DatasetVerifierExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings={b.capability_id:b for b in bindings},policy=policy)
    return declaration(executor,bindings,'Independent pinned dataset metrics over authorized captured artifacts')
