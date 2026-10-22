import hashlib,json
from types import SimpleNamespace
import pytest
from orchestrator.engine import OMAEngine
from orchestrator.models import Candidate,Task


def fixture(tmp_path):
    engine=SimpleNamespace(persistence=SimpleNamespace(run_dir=tmp_path))
    task=Task('task','run','Verify exact candidate')
    candidate=Candidate(candidate_id='candidate',task_id=task.id,patch='patch bytes')
    evidence={'candidate_id':candidate.candidate_id,'task_id':task.id,'all_passed':True,
              'source_unchanged':True,'checks_ran':1,'results':[{'passed':True,'command':'[[TEST|all]]'}],
              'patch_hash':hashlib.sha256(candidate.patch.encode()).hexdigest(),
              'base_hash':'a'*64,'candidate_hash':'b'*64}
    path=tmp_path/'verification.json'
    return engine,task,candidate,evidence,path


def test_gate_evidence_is_bound_to_saved_bytes_and_failed_candidate_retires_it(tmp_path):
    engine,task,candidate,evidence,path=fixture(tmp_path)
    path.write_text(json.dumps(evidence),encoding='utf-8')
    OMAEngine._record_objective_evidence(engine,task,candidate,evidence,path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    assert task.metadata['evidence_ids']==['verification:'+digest]
    assert task.metadata['objective_evidence']['patch_hash']==evidence['patch_hash']
    evidence['all_passed']=False
    OMAEngine._record_objective_evidence(engine,task,candidate,evidence,path)
    assert task.metadata['evidence_ids']==[] and 'objective_evidence' not in task.metadata


@pytest.mark.parametrize('change',[{'patch_hash':'0'*64},{'task_id':'other'},
    {'candidate_id':'other'},{'source_unchanged':False},{'checks_ran':0},
    {'results':[]},{'results':[{'passed':True,'refused':True}]}])
def test_report_shape_or_model_claims_do_not_mint_a_reference(tmp_path,change):
    engine,task,candidate,evidence,path=fixture(tmp_path);evidence.update(change)
    path.write_text(json.dumps(evidence),encoding='utf-8')
    OMAEngine._record_objective_evidence(engine,task,candidate,evidence,path)
    assert task.metadata['evidence_ids']==[]


def test_tampering_with_the_persisted_report_is_refused(tmp_path):
    engine,task,candidate,evidence,path=fixture(tmp_path)
    path.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='changed before gate'):
        OMAEngine._record_objective_evidence(engine,task,candidate,evidence,path)
    assert task.metadata['evidence_ids']==[]
