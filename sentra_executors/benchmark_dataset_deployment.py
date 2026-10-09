"""Host commissioning helpers for LOCAL data/expected assets; no provider boot."""
from __future__ import annotations
import dataclasses
import hashlib
import json
from pathlib import Path
from .benchmark_dataset_metrics import compile_source_metrics,inline_expected_assets,DatasetAssetPin,DatasetVerifierBinding
from .benchmark_dataset import fingerprint,canonical
from .rpa import atomic_output,ExecutorFailure


def dataset_commissioning_template(task):
    contracts,reasons=compile_source_metrics(task)
    return {'task_key':task.key,'source_path':task.source_path,'revision':task.source.revision,'payload_sha256':task.payload_sha256,
        'setup_sha256':task.setup_sha256,'evaluator_sha256':task.evaluator_sha256,'source_snapshot':task.snapshot,'apps':task.apps,
        'contracts':[dataclasses.asdict(c) for c in contracts],'metric_unsupported':list(reasons),
        'assets_required':task.view()['assets'],'fixture_id':None,'snapshot_id':None,'provider_ids':[],
        'environment_version':None,'verifier_machine_id':None,'verifier_capability_id':None,'configured':False,'evaluated':False}


def provision_inline_expected(task,contracts,*,output_directory,paths):
    """Explicit host action only: materialize source rule bytes outside clone."""
    root=Path(output_directory).resolve(strict=True)
    if root.is_relative_to(Path(task.source.clone_root).resolve()):raise ExecutorFailure('dataset_clone_expected_write_denied')
    pins=[];artifacts=[]
    for ref,data in inline_expected_assets(task,contracts).items():
        name=hashlib.sha256(ref.encode()).hexdigest()+'.json';target=paths.resolve(str(root/name),write=True)
        def verify(path):
            if path.read_bytes()!=data:raise ExecutorFailure('inline_expected_bytes_changed')
            json.loads(path.read_text(encoding='utf-8'))
        artifact=atomic_output(paths,str(target),lambda p:p.write_bytes(data),verify,max_output_bytes=1024*1024)
        pins.append(DatasetAssetPin(ref,str(target),hashlib.sha256(data).hexdigest()));artifacts.append(artifact)
    return {'expected_assets':tuple(pins),'artifacts':artifacts,'dataset_originals_changed':False}


def configured_dataset_verifier_binding(*,capability_id,catalog,registrations,actual_paths,expected_paths,output_paths,timeout_seconds=60):
    return DatasetVerifierBinding(capability_id,catalog,{r.task_key:r.contracts for r in registrations},
        {r.task_key:r.assets for r in registrations},actual_paths,expected_paths,output_paths,timeout_seconds)
