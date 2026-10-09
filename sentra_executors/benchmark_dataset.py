"""Read-only loaders for the ACTUAL local Arena/OSWorld/WindowsWorld formats.

Never imports a task class, executes setup/postconfig, fetches a URL or writes
the clone. Missing gated tasks remain catalog entries, never V1 substitutions.
"""
from __future__ import annotations
import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from .rpa import AuthorizedPaths,ExecutorFailure,effect_checkpoint,digest


SOURCE_REVISIONS={
    'windows-agent-arena':'6d39ed88c545a0d40a7a02e39b928e278df7332b',
    'osworld-v2':'acdd3493808e716825975b0f0208194bb2faf3c3',
    'windowsworld':'fbccd464f94fec9e284e139f97bf96d0b192f580',
}


def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class DatasetSource:
    name:str
    clone_root:str
    revision:str
    layout:str  # arena-json, osworld-v1-json, osworld-v2-python, windowsworld-array
    manifest:str|None=None
    max_tasks:int=10000
    max_file_bytes:int=32*1024*1024
    def __post_init__(self):
        if self.name not in SOURCE_REVISIONS or not Path(self.clone_root).is_absolute() or not re.fullmatch('[0-9a-f]{40}',self.revision):raise ValueError('explicit_local_dataset_source_pin_required')
        if self.layout not in {'arena-json','osworld-v1-json','osworld-v2-python','windowsworld-array'} or not 1<=self.max_tasks<=20000:raise ValueError('unsupported_dataset_layout')


@dataclass(frozen=True)
class DatasetTask:
    key:str
    source:DatasetSource
    task_id:str
    category:str
    source_path:str
    source_file_sha256:str
    source_pointer:str
    payload_json:str
    payload_sha256:str
    memberships:tuple[str,...]=()
    indexing_issues:tuple[str,...]=()
    @property
    def payload(self):return json.loads(self.payload_json)
    @property
    def setup(self):
        p=self.payload
        return p.get('config',p.get('environment_setup',{}))
    @property
    def setup_sha256(self):return fingerprint(self.setup)
    @property
    def evaluator(self):
        p=self.payload
        return p.get('evaluator',p.get('evaluation_metrics',{}))
    @property
    def evaluator_sha256(self):return fingerprint(self.evaluator)
    @property
    def snapshot(self):return self.payload.get('snapshot')
    @property
    def apps(self):return tuple(self.payload.get('related_apps',self.payload.get('involved_apps',[])))
    def view(self,*,include_payload=False):
        data={'key':self.key,'task_id':self.task_id,'dataset':self.source.name,'layout':self.source.layout,
            'category':self.category,'revision':self.source.revision,'revision_authority':'host_pinned_source_declaration',
            'source_path':self.source_path,'source_pointer':self.source_pointer,'source_file_sha256':self.source_file_sha256,
            'payload_sha256':self.payload_sha256,'setup_sha256':self.setup_sha256,'evaluator_sha256':self.evaluator_sha256,
            'instruction':self.payload.get('instruction'),'snapshot':self.snapshot,'apps':self.apps,
            'memberships':self.memberships,'indexing_issues':self.indexing_issues,'evaluated':False,
            'assets':asset_requirements(self)}
        if include_payload:data['payload']=self.payload
        return data


def asset_requirements(task):
    """Raw remote/generated references, NOT silently downloaded ground truth."""
    p=task.payload;assets=[]
    for step in p.get('config',[]):
        if not isinstance(step,dict):continue
        for item in step.get('parameters',{}).get('files',[]):
            if isinstance(item,dict) and item.get('url'):assets.append({'purpose':'fixture','ref':item['url'],'guest_path':item.get('path'),'sha256':None})
    for item in p.get('environment_setup',{}).get('files_to_create',[]):
        if isinstance(item,dict):assets.append({'purpose':'fixture','ref':'generated://'+task.key+'/'+item.get('filename','unknown'),
            'guest_path':item.get('file_path'),'generation_spec':item,'sha256':None})
    expected=task.evaluator.get('expected')
    for item in expected if isinstance(expected,list) else [expected]:
        if not isinstance(item,dict):continue
        if item.get('type') in {'cloud_file','file','local_file'}:
            assets.append({'purpose':'expected','ref':item.get('path',item.get('url')),'sha256':item.get('sha256')})
        elif item.get('type')=='rule':
            assets.append({'purpose':'expected-rule','ref':'inline://'+task.key+'/'+fingerprint(item['rules']),
                           'sha256':fingerprint(item['rules']),'rules':item['rules']})
    return assets


class DatasetCatalog:
    def __init__(self,sources):
        if not sources or len({(s.name,s.layout) for s in sources})!=len(sources):raise ValueError('unique_dataset_sources_required')
        self.sources=tuple(sources);self.tasks={};self.manifest_pins={}
    def _file(self,source,relative):
        paths=AuthorizedPaths((source.clone_root,),())
        path=paths.resolve(str(Path(source.clone_root)/relative))
        if path.stat().st_size>source.max_file_bytes:raise ExecutorFailure('dataset_source_file_limit')
        effect_checkpoint();return path,path.read_bytes()
    def load(self):
        tasks={};self.manifest_pins={}
        for source in self.sources:
            if source.layout=='windowsworld-array':
                path,raw=self._file(source,source.manifest or 'benchmark.json');rows=json.loads(raw)
                if not isinstance(rows,list):raise ExecutorFailure('windowsworld_array_required')
                if len(rows)>source.max_tasks:raise ExecutorFailure('dataset_task_count_limit')
                self.manifest_pins[str(path)]=hashlib.sha256(raw).hexdigest()
                for index,payload in enumerate(rows):
                    if not isinstance(payload,dict):raise ExecutorFailure('windowsworld_task_object_required')
                    task=self._task(source,payload,str(path),hashlib.sha256(raw).hexdigest(),'/'+str(index),payload.get('task_category','uncategorized'))
                    self._add(tasks,task)
                continue
            base='src/win-arena-container/client/evaluation_examples_windows' if source.layout=='arena-json' else 'evaluation_examples'
            manifest=source.manifest or ('test_v2.json' if source.layout=='osworld-v2-python' else 'test_all.json')
            if source.manifest and '/' in source.manifest.replace('\\','/'):
                manifest_relative=source.manifest
            else:manifest_relative=base+'/'+manifest
            manifest_data=None
            try:
                manifest_path,raw=self._file(source,manifest_relative);manifest_data=json.loads(raw)
                if not isinstance(manifest_data,dict):raise ExecutorFailure('category_manifest_required')
                self.manifest_pins[str(manifest_path)]=hashlib.sha256(raw).hexdigest()
            except FileNotFoundError:
                if source.manifest or source.layout=='osworld-v2-python':raise ExecutorFailure('requested_dataset_manifest_missing')
            if manifest_data is None:
                folder=Path(source.clone_root)/base/'examples'
                candidates=sorted(folder.glob('*/*.json'))
                if len(candidates)>source.max_tasks:raise ExecutorFailure('dataset_task_count_limit')
                records=[(path.parent.name,path.stem,path) for path in candidates]
            else:
                records=[]
                for category,ids in manifest_data.items():
                    if not isinstance(ids,list) or any(type(i) is not str for i in ids):raise ExecutorFailure('invalid_dataset_manifest_ids')
                    for task_id in ids:
                        if '/' in task_id or '\\' in task_id or task_id in {'.','..'}:raise ExecutorFailure('dataset_manifest_path_escape')
                        if source.layout=='osworld-v2-python':
                            path=Path(source.clone_root)/base/'task_class'/('task_'+task_id+'.py')
                            if category!='tasks':path=path.parent/category/path.name
                        else:path=Path(source.clone_root)/base/'examples'/category/(task_id+'.json')
                        records.append((category,task_id,path))
                if len(records)>source.max_tasks:raise ExecutorFailure('dataset_task_count_limit')
            for category,task_id,path in records:
                try:
                    resolved,raw=self._file(source,str(path.relative_to(source.clone_root)))
                    if source.layout=='osworld-v2-python':payload,issues=self._python_metadata(raw,task_id)
                    else:payload=json.loads(raw);issues=[]
                    if not isinstance(payload,dict):raise ExecutorFailure('dataset_task_object_required')
                    if payload.get('id',payload.get('task_id'))!=task_id:issues.append('manifest_payload_id_mismatch')
                    task=self._task(source,payload,str(resolved),hashlib.sha256(raw).hexdigest(),'',category,issues,
                                    (manifest_relative,) if manifest_data is not None else ())
                except FileNotFoundError:
                    payload={'id':task_id};issues=['official_gated_task_not_local' if source.layout=='osworld-v2-python' else 'manifest_payload_missing']
                    task=self._task(source,payload,str(path),'','',category,issues,(manifest_relative,))
                except (ValueError,SyntaxError) as exc:
                    task=self._task(source,{'id':task_id},str(path),digest(path),'',category,['invalid_payload:'+type(exc).__name__])
                self._add(tasks,task)
        self.tasks=tasks;return self
    def _task(self,source,payload,path,file_sha,pointer,category,issues=(),memberships=()):
        task_id=payload.get('id',payload.get('task_id'))
        if type(task_id) is not str or not task_id:raise ExecutorFailure('dataset_task_id_required')
        return DatasetTask(f'{source.name}:{source.layout}:{category}:{task_id}',source,task_id,str(category),path,file_sha,pointer,
                           canonical(payload),fingerprint(payload),tuple(memberships),tuple(issues))
    def _add(self,tasks,task):
        if task.key in tasks:raise ExecutorFailure('duplicate_dataset_task_identity')
        tasks[task.key]=task
    def _python_metadata(self,raw,task_id):
        # AST only. No exec/import/call or attempt to run a gated evaluator.
        tree=ast.parse(raw.decode('utf-8-sig'));data={'id':task_id};issues=['python_task_requires_host_reviewed_translation']
        methods={}
        for cls in (node for node in tree.body if isinstance(node,ast.ClassDef)):
            for node in cls.body:
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'setup','evaluate','evaluate_intermediate'}:
                    methods[node.name]=hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
                if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                    name=node.targets[0].id
                    if name in {'id','snapshot','instruction','related_apps','source','intermediate_eval_safe'}:
                        try:data[name]=ast.literal_eval(node.value)
                        except (ValueError,TypeError):issues.append('dynamic_python_metadata:'+name)
        data['_python_source_sha256']=hashlib.sha256(raw).hexdigest();data['_python_methods']=methods;return data,issues
    def get(self,key):return self.tasks[key]
    def select(self,*,dataset=None,category=None,task_ids=None):
        wanted=set(task_ids) if task_ids is not None else None
        return tuple(t for t in self.tasks.values() if (dataset is None or t.source.name==dataset) and
            (category is None or t.category==category) and (wanted is None or t.task_id in wanted))
    def catalog(self,*,include_payload=False):return [t.view(include_payload=include_payload) for t in self.tasks.values()]
    def revalidate(self,task):
        if task.indexing_issues and not task.source_file_sha256:raise ExecutorFailure('dataset_payload_not_local')
        _,raw=self._file(task.source,str(Path(task.source_path).relative_to(task.source.clone_root)))
        if hashlib.sha256(raw).hexdigest()!=task.source_file_sha256:raise ExecutorFailure('dataset_source_bytes_changed')
        for path,sha in self.manifest_pins.items():
            if Path(path).is_relative_to(Path(task.source.clone_root)) and digest(Path(path))!=sha:raise ExecutorFailure('dataset_selection_manifest_changed')
        return True


def local_clone_sources(workspace):
    root=Path(workspace).resolve()
    return (
        DatasetSource('windows-agent-arena',str(root/'third_party/windows-agent-arena'),SOURCE_REVISIONS['windows-agent-arena'],'arena-json'),
        DatasetSource('osworld-v2',str(root/'third_party/osworld-v2'),SOURCE_REVISIONS['osworld-v2'],'osworld-v1-json'),
        DatasetSource('osworld-v2',str(root/'third_party/osworld-v2'),SOURCE_REVISIONS['osworld-v2'],'osworld-v2-python'),
        DatasetSource('windowsworld',str(root/'third_party/windowsworld'),SOURCE_REVISIONS['windowsworld'],'windowsworld-array'),
    )
