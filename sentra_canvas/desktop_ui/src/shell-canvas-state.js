export const PHASES = [
  { id: 'planning', label: 'Planejamento', meaning: 'O trabalho foi admitido e ainda não está em execução.', safeNext: 'Acompanhe pela conversa ou pelo Canvas. Nenhum efeito é reenviado daqui.' },
  { id: 'executing', label: 'Execução', meaning: 'Há uma operação em andamento, com responsável e recibo ainda abertos.', safeNext: 'Acompanhe o progresso. Não inicie a mesma operação outra vez.' },
  { id: 'waiting', label: 'Espera', meaning: 'O fluxo parou à espera de uma pessoa ou de outro Dot.', safeNext: 'A ação disponível é decidir ou consultar. Não reenvie a operação.' },
  { id: 'review', label: 'Revisão', meaning: 'O resultado existe e aguarda consolidação. Aceitar não é concluir.', safeNext: 'Revise o recibo. A conclusão continua com o coordenador.' },
  { id: 'completed', label: 'Conclusão', meaning: 'O WorkItem ou a operação chegou a um estado terminal de sucesso.', safeNext: 'Consulte o recibo. Não há repetição automática.' },
  { id: 'failed', label: 'Falha', meaning: 'A operação terminou sem o efeito pedido.', safeNext: 'Leia o motivo e escolha uma correção nova. A tentativa anterior não é reenviada.' },
  { id: 'uncertain', label: 'Operação incerta', meaning: 'Não há confirmação de que o efeito ocorreu.', safeNext: 'Consulte o recibo original. Não reenvie.' },
];

const BY_ID = Object.fromEntries(PHASES.map(item => [item.id, item]));

export function phaseCopy(id) {
  return BY_ID[id] || BY_ID.planning;
}

export function canvasPhase(input = {}) {
  const operation = String(input.operationState || '').toUpperCase();
  const work = String(input.workItemState || '').toUpperCase();
  const task = String(input.taskStatus || '').toLowerCase();
  if (operation === 'UNCERTAIN' || work === 'UNCERTAIN' || task === 'uncertain' || task === 'unconfirmed') return 'uncertain';
  if (work === 'IN_REVIEW' || task === 'in_review') return 'review';
  if (['FAILED', 'CANCELLED', 'CANCELED'].includes(operation) || ['FAILED', 'CANCELLED', 'CANCELED'].includes(work) || ['failed', 'cancelled', 'canceled'].includes(task)) return 'failed';
  if (operation === 'SUCCEEDED' || ['SUCCEEDED', 'COMPLETED'].includes(work) || ['completed', 'succeeded'].includes(task)) return 'completed';
  if (task === 'waiting_approval' || task === 'waiting_chatgpt_user_approval' || work === 'WAITING_APPROVAL' || operation === 'WAITING_APPROVAL') return 'waiting';
  if (['running', 'dispatched'].includes(task) || ['RUNNING', 'DISPATCHED'].includes(work) || ['RUNNING', 'PENDING', 'RESERVED'].includes(operation)) return 'executing';
  return 'planning';
}

export function taskPresentation(task = {}, extra = {}) {
  const phase = canvasPhase({ taskStatus: task.status, workItemState: task.work_item_state, operationState: task.operation_state });
  const copy = phaseCopy(phase);
  return {
    phase, label: copy.label, meaning: copy.meaning, safeNext: copy.safeNext, resend: false,
    owner: extra.owner || task.agent_id || 'Responsável não informado',
    dependency: task.depends_on || task.parent_work_item_id || null,
    progress: task.progress || task.status || 'sem progresso informado',
    receipt: task.work_item_id || task.operation_id || null,
  };
}

export function summarizePhases(tasks = [], deliveries = []) {
  const counts = Object.fromEntries(PHASES.map(item => [item.id, 0]));
  for (const task of tasks) counts[canvasPhase({ taskStatus: task.status, workItemState: task.work_item_state, operationState: task.operation_state })] += 1;
  for (const receipt of deliveries) counts[canvasPhase({ taskStatus: receipt.status, workItemState: receipt.work_item_state, operationState: receipt.operation_state })] += 1;
  return PHASES.map(item => ({ ...item, count: counts[item.id] }));
}