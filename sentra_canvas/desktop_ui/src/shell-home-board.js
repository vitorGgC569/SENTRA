import { canvasPhase } from './shell-canvas-state.js';
import { conversationInstant, formatConversationDate, formatConversationDateTime } from './shell-dates.js';

const APPROVAL = new Set(['waiting_approval', 'waiting_chatgpt_user_approval', 'needs_input']);
const FAILURE = new Set(['failed', 'uncertain', 'unconfirmed', 'interrupted', 'blocked']);
const DELIVERED = new Set(['succeeded', 'completed']);
const SURFACE_LABELS = {
  canvas: 'Canvas', chat: 'Conversa', documents: 'Documentos', dots: 'Dots', network: 'Rede',
  conversations: 'Conversas', spaces: 'Spaces', space: 'Space',
};

function includesQuery(query, parts) {
  if (!query) return true;
  return parts.filter(Boolean).join(' ').toLowerCase().includes(query);
}

function statusOf(value) {
  return String(value || '').toLowerCase();
}

function textId(value) {
  if (value == null) return '';
  return String(value).trim();
}

function pickId(source, name) {
  const payload = source?.payload && typeof source.payload === 'object' ? source.payload : {};
  return textId(source?.[name] || payload[name]);
}

export const FAILURE_NOTE = 'Consulte o estado. Não repita o envio.';
export const FAILURE_CONSULT = 'Consultar';
export const FAILURE_PAGE = 6;

export function recordCountLabel(count) {
  return count + (count === 1 ? ' registro' : ' registros');
}

function sameDomainCount(records, name) {
  const keys = records.map(record => textId(record?.[name]));
  if (!keys.length || !keys.every(Boolean)) return null;
  return new Set(keys).size;
}

function sendCountLabel(count) {
  return count === 1 ? '1 envio não confirmado' : count + ' envios não confirmados';
}

export function unconfirmedWorkLabel(records) {
  const list = Array.isArray(records) ? records : [];
  if (!list.length) return '';
  const byMessage = sameDomainCount(list, 'message_id');
  if (byMessage != null) return sendCountLabel(byMessage);
  const byRequest = sameDomainCount(list, 'request_key');
  if (byRequest != null) return sendCountLabel(byRequest);
  return list.length === 1 ? '1 registro de envio não confirmado' : list.length + ' registros de envio não confirmado';
}

export function workSupportLine(records) {
  const list = Array.isArray(records) ? records : [];
  const phrase = unconfirmedWorkLabel(list);
  if (!phrase) return '';
  const domain = sameDomainCount(list, 'message_id') != null || sameDomainCount(list, 'request_key') != null;
  return domain ? phrase + ', em ' + recordCountLabel(list.length) : phrase;
}

function conversationDetail(title, dotName, countLabel, latestLabel) {
  const when = textId(latestLabel);
  const meta = when ? countLabel + ' · ' + when : countLabel;
  const name = textId(dotName);
  const identifiable = Boolean(name) && name.toLowerCase() !== 'dot' && name.toLowerCase() !== textId(title).toLowerCase();
  return {
    dotLabel: identifiable ? name : '',
    meta: identifiable ? ' · ' + meta : meta,
    detail: identifiable ? name + ' · ' + meta : meta,
  };
}

function isUnconfirmedSend(item) {
  const status = statusOf(item?.status);
  if (status === 'failed') return false;
  return status === 'uncertain' || status === 'unconfirmed' || /uncertain|unconfirmed/i.test(item?.kind || '');
}

export function dotContextLine(dot, conversations = [], records = []) {
  const unconfirmed = (records || []).filter(isUnconfirmedSend);
  const dotId = textId(dot?.dot_id);
  const own = (conversations || []).filter(row => dotId && textId(row?.dot_id) === dotId);
  const conversationIds = new Set(own.map(row => textId(row?.conversation_id)).filter(Boolean));
  const linked = unconfirmed.filter(record => {
    if (!dotId) return false;
    if (textId(record?.dot_id) === dotId) return true;
    const conversationId = textId(record?.conversation_id);
    return Boolean(conversationId) && conversationIds.has(conversationId);
  });
  if (linked.length) return unconfirmedWorkLabel(linked);
  if (!own.length) return '';
  const latest = own.reduce((best, row) => (conversationInstant(row?.updated_at) || 0) >= (conversationInstant(best?.updated_at) || 0) ? row : best, own[0]);
  const noun = own.length === 1 ? '1 conversa' : own.length + ' conversas';
  const when = formatConversationDate(latest?.updated_at);
  return when ? noun + ' · ' + when : noun;
}

export function groupHomeConversations(conversations = [], dots = []) {
  const names = new Map((dots || []).filter(row => row?.dot_id).map(row => [textId(row.dot_id), textId(row.name) || 'Dot']));
  const groups = new Map();
  for (const row of conversations || []) {
    if (!row?.conversation_id) continue;
    const title = textId(row.title || row.name) || 'Conversa';
    const dotId = textId(row.dot_id);
    const key = title + '\n' + dotId;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  return [...groups.values()].map(items => {
    const sorted = [...items].sort((a, b) => (conversationInstant(b?.updated_at) || 0) - (conversationInstant(a?.updated_at) || 0));
    const latest = sorted[0];
    const title = textId(latest.title || latest.name) || 'Conversa';
    const dotId = textId(latest.dot_id);
    const dotName = names.get(dotId) || 'Dot';
    const countLabel = items.length === 1 ? '1 conversa' : items.length + ' conversas';
    const latestLabel = formatConversationDate(latest.updated_at);
    const summary = conversationDetail(title, dotName, countLabel, latestLabel);
    return {
      key: title + ':' + dotId,
      title,
      dotId,
      dotName,
      count: items.length,
      countLabel,
      latestLabel,
      dotLabel: summary.dotLabel,
      meta: summary.meta,
      detail: summary.detail,
      items: sorted.map(row => ({
        conversation_id: row.conversation_id,
        dot_id: row.dot_id,
        space_id: row.space_id,
        title: textId(row.title || row.name) || title,
        updated_at: row.updated_at,
        whenLabel: formatConversationDateTime(row.updated_at),
        dotName: names.get(textId(row.dot_id)) || dotName,
      })),
    };
  }).sort((a, b) => (conversationInstant(b.items[0]?.updated_at) || 0) - (conversationInstant(a.items[0]?.updated_at) || 0));
}

export function failureMoreLabel(rest) {
  return 'Mostrar os outros ' + rest;
}

function isUncertain(item) {
  return item?.status === 'uncertain' || item?.status === 'unconfirmed' || /uncertain|unconfirmed/i.test(item?.kind || '');
}

function humanKind(item, count) {
  const kind = item?.kind || '';
  const status = item?.status || '';
  if (isUncertain(item) && kind === 'message.uncertain') return count > 1 ? 'Mensagens não confirmadas' : 'Mensagem não confirmada';
  if (isUncertain(item)) return count > 1 ? 'Envios não confirmados' : 'Envio não confirmado';
  if (status === 'interrupted' || /interrupt/i.test(kind)) return count > 1 ? 'Interrompidas' : 'Interrompida';
  if (status === 'blocked' || /block/i.test(kind)) return count > 1 ? 'Bloqueadas' : 'Bloqueada';
  if (status === 'failed' || /fail|error/i.test(kind)) return count > 1 ? 'Falhas' : 'Falha';
  return count > 1 ? 'Registros' : 'Registro';
}

function groupTitle(items, names) {
  const first = items[0] || {};
  const conversationName = first.conversation_id ? names.conversations.get(first.conversation_id) : '';
  const dotName = first.dot_id ? names.dots.get(first.dot_id) : '';
  if (conversationName) return conversationName;
  if (dotName) return dotName;
  if (first.operation_id) return 'Operação ' + first.operation_id;
  if (first.conversation_id) return 'Conversa';
  return humanKind(first, items.length);
}

function recordLabel(item, names) {
  if (item.operation_id) return 'Operação ' + item.operation_id;
  if (item.conversation_id) return names.conversations.get(item.conversation_id) || 'Conversa';
  const stamp = item.event_id || item.seq;
  return stamp ? 'Registro ' + stamp : 'Registro';
}

export function groupFailures(failures, conversations = [], dots = []) {
  const names = {
    conversations: new Map(conversations.filter(row => row?.conversation_id).map(row => [textId(row.conversation_id), textId(row.title || row.name)])),
    dots: new Map(dots.filter(row => row?.dot_id).map(row => [textId(row.dot_id), textId(row.name)])),
  };
  const groups = new Map();
  for (const item of failures) {
    const key = item.conversation_id ? 'conversation:' + item.conversation_id
      : item.operation_id ? 'operation:' + item.operation_id
      : item.dot_id ? 'dot:' + item.dot_id
      : 'kind:' + (item.kind || 'unknown');
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [...groups.entries()].map(([key, items]) => {
    const titled = items.map(item => ({ ...item, label: recordLabel(item, names) }));
    return {
      key, title: groupTitle(titled, names), count: titled.length, countLabel: recordCountLabel(titled.length),
      items: titled, success: false, pageSize: FAILURE_PAGE,
    };
  });
}

export function buildFailurePanels(failures, conversations = [], dots = []) {
  const uncertain = failures.filter(isUncertain);
  const confirmed = failures.filter(item => !isUncertain(item));
  const panel = (id, title, items, note) => ({
    id, title, count: items.length, countLabel: recordCountLabel(items.length), note,
    consult: FAILURE_CONSULT, success: false, pageSize: FAILURE_PAGE,
    groups: groupFailures(items, conversations, dots),
  });
  return [
    ...(uncertain.length ? [panel('uncertain', 'Envios não confirmados', uncertain, FAILURE_NOTE)] : []),
    ...(confirmed.length ? [panel('failed', 'Falhas', confirmed, 'Consulte o estado.')] : []),
  ];
}

function fact(id, label, color) {
  return { id, label, color };
}

export function executionIsWorking(execution) {
  if (!execution || execution.validated !== true) return false;
  return canvasPhase({
    taskStatus: execution.taskStatus || execution.status,
    workItemState: execution.workItemState || execution.work_item_state,
    operationState: execution.operationState || execution.operation_state,
  }) === 'executing';
}

export function dotPhase(status, execution) {
  if (executionIsWorking(execution)) return fact('working', 'Trabalhando', '#8eb6ff');
  const value = statusOf(status);
  if (value === 'active') return fact('active', 'Ativo', '#c5c8ce');
  if (value === 'available' || value === 'ready') return fact('available', 'Disponível', '#9aa0a8');
  if (value === 'idle' || value === '') return fact('idle', 'Ocioso', '#9aa0a8');
  if (APPROVAL.has(value)) return fact('waiting', 'Espera', '#e2b15a');
  if (DELIVERED.has(value)) return fact('done', 'Concluído', '#7dcea8');
  if (['failed', 'cancelled', 'canceled', 'interrupted', 'blocked'].includes(value)) return fact('failed', 'Falha', '#f0a0ae');
  if (value === 'uncertain' || value === 'unconfirmed') return fact('uncertain', 'Incerta', '#e0b56a');
  return fact('idle', 'Ocioso', '#9aa0a8');
}

export function homeBoard(home, options = {}) {
  const query = String(options.query || '').trim().toLowerCase();
  const dots = Array.isArray(home?.dots) ? home.dots : [];
  const conversations = Array.isArray(home?.conversations) ? home.conversations : [];
  const spaces = Array.isArray(home?.spaces) ? home.spaces : [];
  const events = Array.isArray(home?.activity?.items) ? home.activity.items : [];
  const pending = Array.isArray(options.pending) ? options.pending : [];
  const currentSpace = home?.space?.space_id || null;
  const running = home?.run?.state === 'RUNNING';
  const recentOrder = new Map();
  conversations.forEach((row, index) => {
    if (row?.dot_id && !recentOrder.has(row.dot_id)) recentOrder.set(row.dot_id, index);
  });
  const recentDots = dots.filter(row => includesQuery(query, [row?.name, row?.status, dotPhase(row?.status).label, 'dot']))
    .sort((a, b) => (recentOrder.get(a.dot_id) ?? 1000) - (recentOrder.get(b.dot_id) ?? 1000)
      || String(a.name || '').localeCompare(String(b.name || ''), 'pt'))
    .map(row => {
      const phase = dotPhase(row?.status, row?.execution);
      return { ...row, phase: phase.id, fact: phase.label, factColor: phase.color };
    });
  const projects = spaces.filter(row => includesQuery(query, [row?.name, row?.description, 'projeto', 'space']))
    .map(row => ({
      id: row.space_id, space_id: row.space_id, project_id: row.project_id, name: row.name || 'Space',
      description: row.description || '', inProgress: Boolean(running && row.space_id === currentSpace),
    }));
  const approvals = [];
  for (const row of conversations) {
    const status = statusOf(row.status);
    if (!APPROVAL.has(status) || !includesQuery(query, [row.title, status, 'aprovação', 'aprovacao'])) continue;
    approvals.push({ id: 'conversation:' + row.conversation_id, conversation_id: row.conversation_id,
      space_id: row.space_id, dot_id: row.dot_id, title: row.title || 'Conversa', reason: status, kind: 'conversation' });
  }
  for (const event of events) {
    const status = statusOf(event.payload?.status || event.payload?.state);
    const kind = String(event.kind || '');
    if (!APPROVAL.has(status) && !/approval/i.test(kind)) continue;
    if (!includesQuery(query, [kind, event.payload?.summary, status, 'aprovação'])) continue;
    approvals.push({ id: 'event:' + (event.event_id || event.seq), title: event.payload?.summary || kind || 'Aprovação',
      reason: status || kind, kind: 'event' });
  }
  for (const mutation of pending) {
    if (!mutation?.request_key || !includesQuery(query, [mutation.action, 'pendente'])) continue;
    approvals.push({ id: 'pending:' + mutation.request_key, title: mutation.action || 'Operação',
      reason: 'resposta pendente nesta janela', kind: 'pending' });
  }
  const failures = [];
  for (const event of events) {
    const status = statusOf(event.payload?.status || event.payload?.state);
    const kind = String(event.kind || '');
    if (!FAILURE.has(status) && !/fail|uncertain|error/i.test(kind)) continue;
    if (!includesQuery(query, [kind, event.payload?.summary, status, 'falha'])) continue;
    failures.push({
      id: 'failure:' + (event.event_id || event.seq),
      event_id: textId(event.event_id), seq: event.seq ?? '', kind, status: status || 'failed',
      conversation_id: pickId(event, 'conversation_id'), operation_id: pickId(event, 'operation_id'),
      dot_id: pickId(event, 'dot_id'), message_id: pickId(event, 'message_id'),
      request_key: pickId(event, 'request_key'), summary: textId(event.payload?.summary),
    });
  }
  for (const row of conversations) {
    const status = statusOf(row.status);
    if (FAILURE.has(status) && includesQuery(query, [row.title, status, 'falha'])) {
      failures.push({
        id: 'conversation-failure:' + row.conversation_id, event_id: '', seq: '', kind: 'conversation', status,
        conversation_id: textId(row.conversation_id), operation_id: '', dot_id: textId(row.dot_id),
        message_id: pickId(row, 'message_id'), request_key: pickId(row, 'request_key'),
        summary: textId(row.title),
      });
    }
  }
  const failurePanels = buildFailurePanels(failures, conversations, dots);
  const failureGroups = failurePanels.flatMap(panel => panel.groups);
  const unconfirmedSends = failures.filter(isUnconfirmedSend);
  const dotNames = new Map(dots.filter(row => row?.dot_id).map(row => [textId(row.dot_id), textId(row.name)]));
  const visibleConversations = conversations.filter(row => includesQuery(query, [row?.title, row?.name, dotNames.get(textId(row?.dot_id))]));
  const contextualDots = recentDots.map(row => ({ ...row, context: dotContextLine(row, conversations, unconfirmedSends) }));
  const deliveries = [];
  for (const row of conversations) {
    const status = statusOf(row.status);
    if (!DELIVERED.has(status) || !includesQuery(query, [row.title, status, 'entrega'])) continue;
    deliveries.push({ id: 'conversation-delivery:' + row.conversation_id, title: row.title || 'Conversa', status });
  }
  for (const event of events) {
    const status = statusOf(event.payload?.status || event.payload?.state);
    const kind = statusOf(event.kind);
    if (!DELIVERED.has(status) && !['delivery', 'receipt'].includes(kind)) continue;
    if (!includesQuery(query, [event.kind, event.payload?.summary, status, 'entrega'])) continue;
    deliveries.push({ id: 'delivery:' + (event.event_id || event.seq), title: event.payload?.summary || event.kind || 'Entrega',
      status: status || kind, receipt: event.payload?.receipt_id || '' });
  }
  const surface = options.surface && options.surface.view ? { ...options.surface, label: SURFACE_LABELS[options.surface.view] || options.surface.view } : null;
  const focus = spaces.find(row => row.space_id === currentSpace) || null;
  const recordsQuiet = approvals.length === 0 && deliveries.length === 0 && failures.length === 0;
  const workSupport = workSupportLine(unconfirmedSends);
  return { query, surface, focus, recordsQuiet, workSupport, recentDots: contextualDots, projects, approvals, deliveries, failures,
    conversationGroups: groupHomeConversations(visibleConversations, dots),
    failureGroups, failurePanels, failureCount: failures.length,
    inProgress: projects.filter(item => item.inProgress),
    empty: dots.length === 0 && conversations.length === 0 && spaces.length === 0 };
}