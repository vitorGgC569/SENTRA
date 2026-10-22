"""Guest import mapping is derived from the existing central receipt only."""
import pytest

from sentra_canvas.shell_dot_canvas import _imported_guest_workspace
from sentra_canvas.shell_dot_vm import project_vm_execution


def _receipt(**changes):
    return {'state':'SUCCEEDED','evidence':{
        'status':'project_imported','receipt_state':'SUCCEEDED','vm_id':'owned-vm',
        'guest_path':'/home/dotuser/Imports/projects/captured/project',
        'host_folder':r'C:\host\project','guest_copy_proven':True,
        'execution_surface':'guest','host_subprocess':False,
        'physical_effects_performed':True,'reconciled_uncertain':True,
        **changes,
    }}


@pytest.mark.parametrize('action',['project.import','project.import.reconcile'])
def test_successful_explicit_import_reconciliation_restores_same_guest_mapping(action):
    record={'vm_id':'owned-vm','username':'dotuser','provisioning_status':'installation_launch_sent'}
    update=project_vm_execution(record,{'action':action},_receipt())
    assert 'provisioning_status' not in update
    imported=update['last_project_import']
    assert imported['vm_id']=='owned-vm'
    assert imported['reconciled_uncertain'] is True
    assert imported['bidirectional_sync'] is False
    assert imported['replays_duplicate_operation'] is False
    assert _imported_guest_workspace({**record,**update},'linux')==imported['guest_path']


@pytest.mark.parametrize('changes',[
    {'vm_id':'different-vm'},
    {'receipt_state':'UNCERTAIN'},
    {'guest_path':r'C:\host\project'},
    {'guest_path':'/home/dotuser/../../etc'},
])
def test_unconfirmed_or_different_guest_mapping_does_not_replace_prior_import(changes):
    record={'vm_id':'owned-vm','username':'dotuser'}
    assert 'last_project_import' not in project_vm_execution(record,{'action':'project.import.reconcile'},_receipt(**changes))


def test_uncertain_central_operation_cannot_publish_successful_nested_mapping():
    receipt=_receipt()
    receipt['state']='UNCERTAIN'
    assert project_vm_execution({'vm_id':'owned-vm'},{'action':'project.import.reconcile'},receipt)=={}


def test_mapped_path_cannot_follow_a_replaced_vm_registry_identity():
    record={'vm_id':'owned-vm','username':'dotuser'}
    update=project_vm_execution(record,{'action':'project.import'},_receipt())
    assert _imported_guest_workspace({**record,**update,'vm_id':'replacement-vm'},'linux') is None
