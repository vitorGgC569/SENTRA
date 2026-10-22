// Coucou visual layer (Frente 3).
// Padrões visuais inspirados no Coucou (MIT); nenhum personagem ou asset do Coucou é usado.
// Este módulo é puro: não chama bridge, não faz polling e não cria timeline paralela.

import { completionEvidence } from './shell-completion-evidence.js';
import { validatedExecutionIsWorking } from './dot-motion.js';

export const CHAT_PRESENCE_STATES = Object.freeze([
  'idle', 'listening', 'thinking', 'working', 'waiting', 'error', 'done',
]);

const WAITING = new Set([
  'waiting_approval', 'waiting_chatgpt_user_approval', 'needs_input',
  'uncertain', 'unconfirmed', 'interrupted', 'blocked',
]);
const ERRORS = new Set(['failed', 'error', 'expired']);
const STOPPED = new Set(['stop', 'stopped', 'cancelled', 'canceled']);
const ACTIVE = new Set([
  'sending', 'queued', 'pending', 'starting', 'dispatched', 'running',
  'executing', 'working', 'in_progress', 'generating', 'confirming',
]);
const THINKING = new Set(['thinking', 'reasoning', 'preparing']);
const DONE = new Set(['completed', 'succeeded', 'verified']);

function lower(value) {
  return String(value ?? '').trim().toLowerCase();
}

function clean(value) {
  return typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
}

function clip(value, max = 72) {
  const text = clean(value);
  return text.length > max ? text.slice(0, Math.max(0, max - 1)).trimEnd() + '…' : text;
}

function statusOf(value) {
  if (!value || typeof value !== 'object') return '';
  return lower(value.status || value.state || value.task_lifecycle?.stage ||
    value.lifecycle?.stage || value.task_status || value.operation_state || value.work_item_state);
}

function executionStatusOf(value) {
  if (!value || typeof value !== 'object') return '';
  return lower(value.operationState || value.operation_state || value.workItemState ||
    value.work_item_state || value.status || value.state);
}

function operationOf(value) {
  if (!value || typeof value !== 'object') return '';
  return clean(value.operation_id || value.operationId);
}

function receiptOf(value) {
  if (!value || typeof value !== 'object') return '';
  return clean(value.receipt_id || value.receiptId || value.receipt?.receipt_id);
}

/** Delivery, hook completion and file lists alone are not verification. */
export const hasCompletionEvidence = completionEvidence;

function lastActionOf(messages, livePreview) {
  const step = deriveChatTicker({ messages, livePreview, limit: 1 }).at(-1);
  return step ? clip([step.step, step.detail].filter(Boolean).join(' · '), 96) : '';
}

function connectionDetail(connectionState) {
  return {
    connecting: 'Conectando ao fluxo da conversa.',
    connected: '',
    reconnecting: 'Reconectando; o texto já recebido foi preservado.',
    unavailable: 'Modo de compatibilidade; a conversa continua legível.',
    reauth_required: 'Sessão expirada; reabra a janela para continuar.',
  }[lower(connectionState)] || '';
}

function startedAtOf(messages, livePreview) {
  const previewStamp = livePreview?.started_at || livePreview?.startedAt || livePreview?.received_at;
  if (typeof previewStamp === 'string' && previewStamp) return previewStamp;
  if (Number.isFinite(livePreview?.received_at_ms)) {
    try { return new Date(livePreview.received_at_ms).toISOString(); } catch { /* fall through */ }
  }
  const list = Array.isArray(messages) ? messages : [];
  for (let index = list.length - 1; index >= 0; index -= 1) {
    const message = list[index];
    if (message?.role === 'user' && !message.optimistic && message.created_at) return message.created_at;
  }
  return undefined;
}

function presenceResult(state, detail, { verified = false, lastAction = '', startedAt } = {}) {
  const labels = {
    idle: 'Presente',
    listening: 'Ouvindo',
    thinking: 'Pensando',
    working: 'Trabalhando',
    waiting: 'Aguardando você',
    error: 'Precisa de atenção',
    done: 'Concluído',
  };
  return {
    state,
    label: labels[state] || labels.idle,
    detail: clean(detail),
    verified: state === 'done' ? verified === true : false,
    lastAction: clean(lastAction),
    ...(startedAt ? { startedAt } : {}),
  };
}

/**
 * Presença do Dot na conversa. Usa somente os dados recebidos; não consulta
 * relógio, bridge, journal ou status externo.
 */
export function chatPresenceModel({ dot = null, messages = [], livePreview = null,
  connectionState = '', busy = false, now = null } = {}) {
  void now;
  const list = Array.isArray(messages) ? messages : [];
  const latest = list.at(-1) || null;
  const authoritative = [...list].reverse().find(message => message && !message.optimistic) || latest;
  const currentStatus = statusOf(latest);
  const latestStatus = statusOf(authoritative);
  const previewStatus = lower(livePreview?.status);
  const previewVisible = ['generating', 'confirming', 'interrupted', 'preview_unavailable'].includes(previewStatus);
  const previewActivity = clean(livePreview?.activity);
  const previewUncertain = previewStatus === 'interrupted' || previewStatus === 'preview_unavailable' ||
    previewActivity === 'Entrega incerta. Não reenvie.';
  const dotStatus = lower(dot?.status);
  const execution = dot?.execution || {};
  const executionStatus = executionStatusOf(execution);
  const dotWorking = validatedExecutionIsWorking(execution);
  const context = connectionDetail(connectionState);
  const startedAt = startedAtOf(list, livePreview);
  const action = lastActionOf(list, livePreview);

  const waitingDetail = (status) => {
    if (status === 'needs_input') return 'Precisa da sua resposta para continuar.';
    if (status === 'waiting_chatgpt_user_approval') return 'Aprovação necessária no ChatGPT.';
    if (['uncertain', 'unconfirmed'].includes(status)) return 'Resultado ainda não confirmado. Consulte sem reenviar.';
    if (status === 'interrupted') return 'Trabalho interrompido; não há conclusão verificada.';
    if (status === 'blocked') return 'Trabalho bloqueado; uma decisão é necessária.';
    return 'Aprovação necessária para continuar.';
  };
  const waiting = (status) => WAITING.has(status) ? presenceResult('waiting', waitingDetail(status), { lastAction: action, startedAt }) : null;
  const failure = (status, source) => {
    if (!ERRORS.has(status)) return null;
    const reason = clip(source?.reason || source?.error || '', 90);
    return presenceResult('error', reason || (status === 'expired' ? 'Operação expirada.' : 'Falha registrada.'), {
      lastAction: action, startedAt,
    });
  };
  const active = (status) => {
    if (!ACTIVE.has(status)) return null;
    if (['sending', 'queued', 'pending', 'starting'].includes(status)) {
      return presenceResult('thinking', status === 'sending' ? 'Preparando o envio.' : 'Aguardando a vez na fila.', {
        lastAction: action, startedAt,
      });
    }
    return presenceResult('working', action || 'Execução em andamento.', { lastAction: action, startedAt });
  };

  // Sinais da mensagem mais recente têm prioridade sobre estados antigos do Dot.
  const waitingSignal = waiting(currentStatus) || waiting(latestStatus);
  if (waitingSignal) return waitingSignal;
  const errorSignal = failure(currentStatus, latest) || failure(latestStatus, authoritative);
  if (errorSignal) return errorSignal;
  const activeSignal = active(currentStatus) || active(latestStatus);
  if (activeSignal) return activeSignal;
  if (latest?.optimistic || (latest?.role === 'user' && !hasCompletionEvidence(latest) && !STOPPED.has(currentStatus))) {
    return presenceResult('thinking', 'Aguardando o Dot continuar este turno.', { lastAction: action, startedAt });
  }
  if (busy) return presenceResult('thinking', 'Preparando a próxima etapa.', { lastAction: action, startedAt });

  if (previewUncertain) {
    return presenceResult('waiting', 'A prévia não confirma a entrega. Consulte sem reenviar.', {
      lastAction: action, startedAt,
    });
  }
  if (previewVisible) {
    const previewWorking = previewStatus === 'confirming' ||
      (previewStatus === 'generating' && Boolean(clean(livePreview?.content)));
    return presenceResult(previewWorking ? 'working' : 'thinking',
      previewActivity || (previewWorking ? 'Recebendo resposta.' : 'Aguardando a primeira parte da resposta.'),
      { lastAction: action, startedAt });
  }

  if (dotWorking) return presenceResult('working', action || 'Execução em andamento.', { lastAction: action, startedAt });

  const laterWaiting = waiting(latestStatus) || waiting(dotStatus) || waiting(executionStatus);
  if (laterWaiting) return laterWaiting;
  const laterError = failure(dotStatus, dot) || failure(executionStatus, execution);
  if (laterError) return laterError;

  // Um novo turno em pensamento vale mais que uma conclusão antiga do Dot.
  if (THINKING.has(currentStatus) || THINKING.has(latestStatus)) {
    return presenceResult('thinking', 'Preparando a próxima etapa.', { lastAction: action, startedAt });
  }

  const sameTurn = operationOf(authoritative) && operationOf(authoritative) === (operationOf(execution) || operationOf(dot));
  const dotProof = !list.length || sameTurn ? dot : null;
  const completion = [currentStatus, latestStatus, dotStatus, executionStatus].some(status => STOPPED.has(status)) ? null
    : [authoritative, dotProof].find(hasCompletionEvidence);
  if (completion) {
    const receipt = receiptOf(completion) || receiptOf(dot) || receiptOf(execution);
    return presenceResult('done', receipt ? 'Recibo ' + clip(receipt, 52) : 'Verificação explícita registrada.', {
      verified: true,
      lastAction: action || 'Concluído e verificado.',
      startedAt,
    });
  }

  if (THINKING.has(dotStatus)) {
    return presenceResult('thinking', 'Preparando a próxima etapa.', { lastAction: action, startedAt });
  }
  if (dotStatus === 'listening') {
    return presenceResult('listening', 'Aguardando sua mensagem.', { lastAction: action, startedAt });
  }
  return presenceResult('idle', context, { lastAction: action, startedAt });
}

const PILL_KINDS = new Set(['tool', 'approval', 'receipt', 'uncertain', 'error', 'done']);
const TICKER_STATUSES = new Set([
  ...ACTIVE, ...THINKING, 'sent', 'delivered', 'paused', 'stopped', 'stop',
  'cancelled', 'canceled',
]);

/**
 * Pill compacta de uma mensagem já carregada. Retorna null quando a mensagem
 * não trouxe status, operação nem recibo.
 */
export function chatEventPillFor(message) {
  if (!message || typeof message !== 'object') return null;
  const status = statusOf(message);
  const operation = operationOf(message);
  const receipt = receiptOf(message);
  if (!status && !operation && !receipt) return null;

  const detail = receipt ? clip(receipt, 48) : operation ? clip(operation, 48) : '';
  if (ERRORS.has(status)) {
    return { kind: 'error', label: status === 'expired' ? 'Expirou' : 'Falhou', detail: detail || clip(status, 24) };
  }
  if (WAITING.has(status)) {
    if (status === 'needs_input') return { kind: 'approval', label: 'Precisa da sua resposta', detail };
    if (status === 'waiting_chatgpt_user_approval') return { kind: 'approval', label: 'Aprovação no ChatGPT', detail };
    if (['uncertain', 'unconfirmed', 'interrupted'].includes(status)) {
      return { kind: 'uncertain', label: status === 'interrupted' ? 'Interrompido' : 'Não confirmado', detail };
    }
    return { kind: 'approval', label: 'Aguardando aprovação', detail };
  }
  if (hasCompletionEvidence(message)) {
    return { kind: 'done', label: 'Concluído e verificado', detail };
  }
  if (receipt) return { kind: 'receipt', label: 'Recibo registrado', detail };
  if (DONE.has(status)) return { kind: 'tool', label: 'Resultado registrado', detail: 'Sem verificação explícita' };
  if (operation) {
    const labels = {
      sending: 'Enviando…', queued: 'Solicitado', pending: 'Pendente', starting: 'Iniciando',
      dispatched: 'Entregue ao Dot', running: 'Em execução', executing: 'Em execução',
      working: 'Trabalhando', in_progress: 'Em andamento', generating: 'Gerando',
      confirming: 'Confirmando', sent: 'Enviado', delivered: 'Entregue',
    };
    return { kind: 'tool', label: labels[status] || 'Operação registrada', detail };
  }
  const labels = {
    sending: 'Enviando…', queued: 'Solicitado', pending: 'Pendente', starting: 'Iniciando',
    dispatched: 'Entregue ao Dot', running: 'Em execução', executing: 'Em execução',
    working: 'Trabalhando', in_progress: 'Em andamento', generating: 'Gerando',
    confirming: 'Confirmando', thinking: 'Pensando', reasoning: 'Raciocinando',
    preparing: 'Preparando', sent: 'Enviado', delivered: 'Entregue',
    paused: 'Interrompido', stopped: 'Parado', stop: 'Parado', cancelled: 'Cancelado',
    canceled: 'Cancelado', idle: 'Ocioso',
  };
  return { kind: 'tool', label: labels[status] || 'Atividade registrada', detail: clip(status, 24) };
}

function tickerKindFor(status) {
  if (ERRORS.has(status)) return 'error';
  if (WAITING.has(status)) return ['uncertain', 'unconfirmed', 'interrupted'].includes(status) ? 'uncertain' : 'approval';
  if (DONE.has(status)) return 'done';
  return 'tool';
}

function tickerStepFor(message, index) {
  if (!message || typeof message !== 'object' || message.optimistic) return null;
  const status = statusOf(message);
  const operation = operationOf(message);
  const receipt = receiptOf(message);
  if (!status && !operation && !receipt) return null;
  if (!operation && !receipt && !TICKER_STATUSES.has(status) &&
      !ERRORS.has(status) && !WAITING.has(status) && !DONE.has(status)) return null;

  const keys = [];
  if (receipt) keys.push('receipt:' + receipt);
  if (operation) keys.push('operation:' + operation);
  if (!keys.length) keys.push('message:' + (message.message_id || index));
  const at = message.created_at || message.createdAt || null;
  const detail = receipt ? clip(receipt, 56) : operation ? clip(operation, 56) : '';

  if (ERRORS.has(status)) {
    return { id: keys[0], keys, kind: 'error', step: status === 'expired' ? 'Operação expirou' : 'Falha registrada',
      detail: detail || clip(status, 32), at };
  }
  if (WAITING.has(status)) {
    const step = status === 'needs_input' ? 'Precisa da sua resposta'
      : status === 'waiting_chatgpt_user_approval' ? 'Aprovação no ChatGPT'
        : status === 'interrupted' ? 'Trabalho interrompido'
          : ['uncertain', 'unconfirmed'].includes(status) ? 'Resultado não confirmado'
            : status === 'blocked' ? 'Trabalho bloqueado' : 'Aguardando aprovação';
    return { id: keys[0], keys, kind: tickerKindFor(status), step, detail, at };
  }
  if (hasCompletionEvidence(message)) {
    return { id: keys[0], keys, kind: 'done', step: 'Concluído e verificado', detail, at };
  }
  if (receipt) {
    return { id: keys[0], keys, kind: 'receipt', step: 'Recibo registrado', detail, at };
  }
  if (DONE.has(status)) {
    return { id: keys[0], keys, kind: 'tool', step: 'Resultado registrado',
      detail: detail || 'Sem verificação explícita', at };
  }
  if (operation) {
    const step = {
      sending: 'Enviando mensagem', queued: 'Solicitação na fila', pending: 'Envio pendente',
      starting: 'Iniciando', dispatched: 'Entregue ao Dot', running: 'Em execução',
      executing: 'Em execução', working: 'Trabalhando', in_progress: 'Em andamento',
      generating: 'Gerando resposta', confirming: 'Confirmando entrega',
      sent: 'Mensagem enviada', delivered: 'Mensagem entregue',
    }[status] || 'Operação registrada';
    return { id: keys[0], keys, kind: 'tool', step, detail, at };
  }
  const step = {
    sending: 'Enviando mensagem', queued: 'Solicitação na fila', pending: 'Envio pendente',
    starting: 'Iniciando', dispatched: 'Entregue ao Dot', running: 'Em execução',
    executing: 'Em execução', working: 'Trabalhando', in_progress: 'Em andamento',
    generating: 'Gerando resposta', confirming: 'Confirmando entrega',
    thinking: 'Pensando', reasoning: 'Raciocinando', preparing: 'Preparando',
    sent: 'Mensagem enviada', delivered: 'Mensagem entregue',
    paused: 'Interrompido', stopped: 'Parado', stop: 'Parado', cancelled: 'Cancelado', canceled: 'Cancelado',
  }[status] || 'Atividade registrada';
  return { id: keys[0], keys, kind: 'tool', step, detail: clip(status, 32), at };
}

function previewStep(livePreview) {
  if (!livePreview || typeof livePreview !== 'object') return null;
  const status = lower(livePreview.status);
  const activity = clean(livePreview.activity);
  const operation = operationOf(livePreview);
  const content = clean(livePreview.content);
  const known = ['generating', 'confirming', 'interrupted', 'preview_unavailable'].includes(status);
  const uncertain = status === 'interrupted' || status === 'preview_unavailable' ||
    activity === 'Entrega incerta. Não reenvie.';
  if (!known && !uncertain) return null;

  const keys = [];
  if (operation) keys.push('operation:' + operation);
  keys.push('preview:current');
  const at = livePreview.received_at || livePreview.started_at || livePreview.received_at_ms || null;

  if (status === 'interrupted' || status === 'preview_unavailable' ||
      activity === 'Entrega incerta. Não reenvie.') {
    return { id: keys[0], keys, kind: 'uncertain',
      step: status === 'preview_unavailable' ? 'Prévia indisponível' : 'Entrega incerta',
      detail: activity || 'A prévia não confirma a entrega.', at };
  }
  if (status === 'confirming') {
    return { id: keys[0], keys, kind: 'working', step: 'Confirmando entrega',
      detail: activity && activity !== 'Confirmando entrega' ? activity : '', at };
  }
  if (status === 'generating') {
    return { id: keys[0], keys, kind: 'working', step: content ? 'Recebendo resposta' : 'Preparando resposta',
      detail: activity || '', at };
  }
  return { id: keys[0], keys, kind: 'working', step: clip(activity || 'Resposta em andamento', 52),
    detail: content && content !== activity ? clip(content, 56) : '', at };
}

/**
 * Até quatro passos recentes, derivados apenas de mensagens carregadas e da
 * prévia viva. A saída é cronológica (mais antigo primeiro) e sem duplicatas.
 */
export function deriveChatTicker({ messages = [], livePreview = null, limit = 4 } = {}) {
  const list = Array.isArray(messages) ? messages : [];
  const bounded = Math.min(4, Math.max(1, Number.isInteger(limit) ? limit : 4));
  const messageOperations = new Set();
  for (const message of list) {
    if (!message || message.optimistic) continue;
    const operation = operationOf(message);
    if (operation) messageOperations.add(operation);
  }

  const candidates = [];
  const preview = previewStep(livePreview);
  const previewOperation = operationOf(livePreview);
  if (preview && (!previewOperation || !messageOperations.has(previewOperation))) candidates.push(preview);
  for (let index = list.length - 1; index >= 0; index -= 1) {
    const step = tickerStepFor(list[index], index);
    if (step) candidates.push(step);
  }

  const seen = new Set();
  const newest = [];
  for (const step of candidates) {
    if (step.keys.some(key => seen.has(key))) continue;
    for (const key of step.keys) seen.add(key);
    newest.push(step);
    if (newest.length >= bounded) break;
  }
  return newest.reverse();
}

export { PILL_KINDS };
