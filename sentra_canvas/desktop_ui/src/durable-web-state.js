export const DELIVERY_LABELS = Object.freeze({
  QUEUED: 'Na fila', PREFLIGHT: 'Verificando autorização', READY: 'Pronta', SENDING: 'Enviando',
  UNCONFIRMED: 'Entrega não confirmada', SENT: 'Mensagem observada', ANSWERING: 'Respondendo',
  ANSWERED: 'Resposta confirmada', REJECTED: 'Recusada', CANCELLED: 'Cancelada', FAILED: 'Falhou',
});
export const MODEL_STATES = ['UNKNOWN', 'DISCOVERING', 'ADVERTISED', 'OBSERVED', 'VERIFIED', 'UNAVAILABLE', 'STALE'];
export function deliveryView(message) {
  const state = Object.hasOwn(DELIVERY_LABELS, message.state) ? message.state : 'UNKNOWN';
  return { ...message, state, label: DELIVERY_LABELS[state] || 'Estado indisponível',
    model_state: MODEL_STATES.includes(message.model_state) ? message.model_state : 'UNKNOWN',
    requires_reconciliation: state === 'UNCONFIRMED' };
}
export function loopRequest(ws, goal, limits) {
  const max_steps = Number(limits.steps), max_cost_usd = Number(limits.cost), deadline_seconds = Number(limits.seconds);
  if (!goal?.goal_id || !Number.isSafeInteger(max_steps) || max_steps < 1 || max_steps > 16
    || limits.cost === '' || !Number.isFinite(max_cost_usd) || max_cost_usd < 0
    || !Number.isSafeInteger(deadline_seconds) || deadline_seconds < 1 || deadline_seconds > 86400) {
    throw Error('Informe os limites de passos, custo e duração.');
  }
  return { ws, action: 'start', goal_id: goal.goal_id, max_steps, max_cost_usd, deadline_seconds };
}
export function goalCost(goal) {
  return typeof goal.cost_usd === 'number' && Number.isFinite(goal.cost_usd)
    ? `$${goal.cost_usd.toFixed(4)}` : 'Indisponível';
}
