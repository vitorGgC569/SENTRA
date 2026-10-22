"""Canonical presentation of task facts; a delivery receipt is not acceptance."""
from enum import StrEnum


class TaskStage(StrEnum):
    REQUESTED='requested'
    DELIVERED='delivered'
    RUNNING='running'
    WAITING_APPROVAL='waiting_approval'
    WAITING_CONFIRMATION='waiting_confirmation'
    VERIFIED='verified'
    FAILED='failed'
    CANCELLED='cancelled'
    EXPIRED='expired'
    INTERRUPTED='interrupted'


LABELS={TaskStage.REQUESTED:'Solicitado',TaskStage.DELIVERED:'Entregue ao Dot',
    TaskStage.RUNNING:'Em execução',TaskStage.WAITING_APPROVAL:'Aguardando aprovação',
    TaskStage.WAITING_CONFIRMATION:'Aguardando confirmação',TaskStage.VERIFIED:'Concluído e verificado',
    TaskStage.FAILED:'Falhou',TaskStage.CANCELLED:'Cancelado',TaskStage.EXPIRED:'Expirado',
    TaskStage.INTERRUPTED:'Interrompido'}


def project_task(row, *, verified_evidence=False):
    states={str(row.get(k) or '').upper() for k in ('work_item_state','operation_state','status','state')}
    # A terminal failure or uncertainty cannot be hidden by another success field.
    if states & {'UNCERTAIN','UNCONFIRMED','WAITING_CONFIRMATION'}:stage=TaskStage.WAITING_CONFIRMATION
    elif states & {'FAILED','FAILURE'}:stage=TaskStage.FAILED
    elif states & {'CANCELLED','CANCELED'}:stage=TaskStage.CANCELLED
    elif states & {'EXPIRED'}:stage=TaskStage.EXPIRED
    elif states & {'INTERRUPTED','PAUSED','RECOVERING'}:stage=TaskStage.INTERRUPTED
    elif states & {'WAITING_APPROVAL','BLOCKED'}:stage=TaskStage.WAITING_APPROVAL
    elif verified_evidence is True and states & {'SUCCEEDED','COMPLETED'}:stage=TaskStage.VERIFIED
    elif states & {'RUNNING','EXECUTING'}:stage=TaskStage.RUNNING
    elif states & {'SUCCEEDED','COMPLETED'}:
        stage=TaskStage.VERIFIED if verified_evidence is True else TaskStage.WAITING_CONFIRMATION
    elif states & {'DELIVERED','RECEIVED','STARTING','DISPATCHED','SENT'}:stage=TaskStage.DELIVERED
    else:stage=TaskStage.REQUESTED
    return {'version':1,'stage':stage.value,'label':LABELS[stage],
        'terminal':stage in {TaskStage.VERIFIED,TaskStage.FAILED,TaskStage.CANCELLED,TaskStage.EXPIRED},
        'successful':stage==TaskStage.VERIFIED,'evidence_verified':stage==TaskStage.VERIFIED,
        'automatic_retry':False}
