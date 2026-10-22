import pytest
from sentra_runtime.task_lifecycle import project_task

@pytest.mark.parametrize('state,stage',[('QUEUED','requested'),('RECEIVED','delivered'),('RUNNING','running'),
    ('WAITING_APPROVAL','waiting_approval'),('UNCERTAIN','waiting_confirmation'),('FAILED','failed'),
    ('CANCELLED','cancelled'),('EXPIRED','expired'),('PAUSED','interrupted')])
def test_formal_states(state,stage):
    row=project_task({'state':state})
    assert row['stage']==stage and not row['successful'] and row['automatic_retry'] is False

def test_completion_requires_verified_evidence_and_does_not_hide_failure():
    assert project_task({'state':'SUCCEEDED'})['stage']=='waiting_confirmation'
    assert project_task({'state':'SUCCEEDED'},verified_evidence=True)['stage']=='verified'
    assert project_task({'work_item_state':'COMPLETED','operation_state':'UNCERTAIN'},verified_evidence=True)['stage']=='waiting_confirmation'
    assert project_task({'work_item_state':'COMPLETED','operation_state':'FAILED'},verified_evidence=True)['stage']=='failed'
