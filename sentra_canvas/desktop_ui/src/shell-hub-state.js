/**
 * Hub, recap e drop — funções puras de observação.
 * Vocabulário visual inspirado no Coucou (Louis-CFM/coucou, MIT).
 * Nenhum asset, personagem, som ou animação do Coucou/Mochi é usado:
 * os companions continuam sendo os Dots originais do SENTRA.
 *
 * Regra de ouro: nada aqui declara conclusão. Só `execution.verified === true`
 * ou recibo/estado verificado contam como verificado; o resto é observação.
 */
import { completionEvidence } from './shell-completion-evidence.js';
import { BUNDLE_VERSION } from './shell-updates.js';

export const HUB_TABS = [
  { id: 'overview', label: 'Visão geral' },
  { id: 'companions', label: 'Companions' },
  { id: 'activity', label: 'Atividade' },
  { id: 'integrations', label: 'Integrações' },
  { id: 'about', label: 'Sobre' },
];

const APPROVAL_STATES = new Set(['waiting_approval', 'waiting_chatgpt_user_approval', 'needs_input']);
const UNCERTAIN_STATES = new Set(['uncertain', 'unconfirmed', 'unverified']);
const FAILURE_STATES = new Set(['failed', 'cancelled', 'canceled', 'blocked', 'expired']);
const PAUSED_STATES = new Set(['paused', 'stopped', 'interrupted']);
const WORKING_STATES = new Set(['running', 'dispatched', 'starting', 'active', 'thinking', 'working', 'in_progress']);
const COMPLETION_STATES = new Set(['completed', 'succeeded']);
const VERIFIED_STATES = new Set(['verified', 'receipt_verified', 'verified_success']);
const DAY_MS = 86400000;

const APPROVAL_LABELS = {
  waiting_approval: 'aguardando aprovação',
  waiting_chatgpt_user_approval: 'aguardando aprovação no ChatGPT',
  needs_input: 'precisa da sua resposta',
};

function clean(value) {
  if (value === null || value === undefined) return '';
  return String(value).trim();
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function record(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

/** Converte epoch em segundos, epoch em milissegundos, Date ou ISO em milissegundos. */
export function instantOf(value) {
  if (value instanceof Date) {
    const time = value.getTime();
    return Number.isFinite(time) ? time : NaN;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) return NaN;
    return value < 1e11 ? value * 1000 : value;
  }
  if (typeof value === 'string') {
    const raw = value.trim();
    if (!raw) return NaN;
    if (/^\d+(\.\d+)?$/.test(raw)) {
      const numeric = Number(raw);
      if (!Number.isFinite(numeric) || numeric <= 0) return NaN;
      return numeric < 1e11 ? numeric * 1000 : numeric;
    }
    const parsed = Date.parse(raw);
    if (Number.isFinite(parsed)) return parsed;
    // "2026-10-22 10:00:00" sem fuso é horário local.
    const local = Date.parse(raw.replace(' ', 'T'));
    return Number.isFinite(local) ? local : NaN;
  }
  return NaN;
}

function startOfDay(milliseconds) {
  const date = new Date(milliseconds);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

function dayKey(date) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-');
}

function dayLabel(date) {
  try {
    return new Intl.DateTimeFormat('pt-BR', {
      weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric',
    }).format(date);
  } catch {
    return dayKey(date);
  }
}

function shortDay(date) {
  try {
    return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' }).format(date);
  } catch {
    return dayKey(date).slice(5).replace('-', '/');
  }
}

/** Data e hora curtas em pt-BR; devolve '' quando não há data válida. */
export function formatWhen(value) {
  const milliseconds = instantOf(value);
  if (!Number.isFinite(milliseconds)) return '';
  try {
    return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
      .format(new Date(milliseconds));
  } catch {
    return new Date(milliseconds).toLocaleString('pt-BR');
  }
}

/** Tamanho legível e honesto. Sem número válido, não inventa um tamanho. */
export function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return 'tamanho não informado';
  if (bytes < 1024) return Math.round(bytes) + ' B';
  const units = ['KB', 'MB', 'GB', 'TB'];
  let size = bytes;
  let index = -1;
  do {
    size /= 1024;
    index += 1;
  } while (size >= 1024 && index < units.length - 1);
  const rounded = size >= 10 ? Math.round(size) : Math.round(size * 10) / 10;
  return String(rounded).replace('.', ',') + ' ' + units[index];
}

function eventKind(event) {
  return clean(event?.kind || event?.type) || 'sem tipo';
}

function eventState(event) {
  const payload = record(event?.payload);
  const value = clean(payload.status || payload.state || payload.stage || event?.status || event?.state);
  return value ? value.toLowerCase() : 'sem estado';
}

/**
 * Um evento só é verificado com recibo/estado explícito.
 * `completed`/`succeeded` são resultado registrado, não conclusão verificada.
 * Hook, stop, saída de CLI e idle são observação — nunca prova de conclusão.
 */
export function eventVerification(event) {
  const payload = record(event?.payload);
  const lifecycle = record(payload.task_lifecycle);
  const legacyLifecycle = record(payload.lifecycle);
  const status = clean(payload.status || payload.state || payload.stage).toLowerCase();
  const stage = clean(lifecycle.stage || legacyLifecycle.stage).toLowerCase();
  const verification = record(payload.task_verification);
  const execution = record(payload.execution || event?.execution);
  const receipt = [payload.receipt_id, event?.receipt_id, verification.receipt_id]
    .map(clean).find(Boolean) || '';
  const refuted = UNCERTAIN_STATES.has(status) || FAILURE_STATES.has(status) || APPROVAL_STATES.has(status) ||
    UNCERTAIN_STATES.has(stage) || FAILURE_STATES.has(stage);
  if (refuted) return { verified: false, reason: 'estado refutado' };
  const explicit = completionEvidence({ ...payload, execution });
  if (explicit) {
    return {
      verified: true,
      reason: VERIFIED_STATES.has(status) || VERIFIED_STATES.has(stage) ? 'estado verificado' : 'recibo verificado',
    };
  }
  // A delivery receipt is useful evidence, but never completion on its own.
  const kind = clean(event?.kind || event?.type);
  if (/hook|stop|session[._-]?end|session[._-]?idle|cli[._-]?exit|process[._-]?exit/i.test(kind)) {
    return { verified: false, reason: 'observação, não conclusão' };
  }
  return { verified: false, reason: 'sem recibo verificado' };
}

function emptyBucket(key, label, short, undated) {
  return {
    key, label, short,
    date: undated ? null : key,
    count: 0,
    verified: 0,
    byKind: {},
    byState: {},
    latest: null,
    undated,
  };
}

/**
 * Recap observado, não produtividade oficial.
 * Agrupa por dia local (pt-BR), ordena do mais recente para o mais antigo,
 * limita a janela a `days` dias e manda timestamps ausentes para "Sem data".
 * `total` inclui os eventos sem data; `verified` só conta recibo/estado verificado.
 */
export function activityRecap(events, options = {}) {
  const requested = Number(options?.days ?? 7);
  const days = Number.isFinite(requested) ? Math.min(31, Math.max(1, Math.trunc(requested))) : 7;
  const nowMs = instantOf(options?.now ?? Date.now());
  const reference = Number.isFinite(nowMs) ? nowMs : Date.now();
  const todayStart = startOfDay(reference);

  const byKey = new Map();
  const ordered = [];
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const date = new Date(todayStart - offset * DAY_MS);
    const key = dayKey(date);
    const bucket = emptyBucket(key, dayLabel(date), shortDay(date), false);
    byKey.set(key, bucket);
    ordered.push(bucket);
  }
  const undated = emptyBucket('sem-data', 'Sem data', '—', true);

  const byKind = {};
  const byState = {};
  let total = 0;
  let verified = 0;

  for (const event of list(events)) {
    if (!event || typeof event !== 'object') continue;
    const time = instantOf(event.created_at ?? event.timestamp ?? event.at);
    let bucket = undated;
    if (Number.isFinite(time)) {
      bucket = byKey.get(dayKey(new Date(startOfDay(time))));
      // Fora da janela (inclusive dias futuros) não entra no recap.
      if (!bucket) continue;
    }
    const kind = eventKind(event);
    const state = eventState(event);
    const proof = eventVerification(event);

    bucket.count += 1;
    bucket.byKind[kind] = (bucket.byKind[kind] || 0) + 1;
    bucket.byState[state] = (bucket.byState[state] || 0) + 1;
    if (proof.verified) {
      bucket.verified += 1;
      verified += 1;
    }
    if (Number.isFinite(time) && (bucket.latest === null || time > bucket.latest)) bucket.latest = time;
    byKind[kind] = (byKind[kind] || 0) + 1;
    byState[state] = (byState[state] || 0) + 1;
    total += 1;
  }

  const sortedDays = ordered.sort((a, b) => b.key.localeCompare(a.key));
  return {
    days: sortedDays,
    undated,
    total,
    byKind,
    byState,
    verified,
    window: {
      days,
      from: sortedDays.length ? sortedDays[sortedDays.length - 1].key : null,
      to: sortedDays.length ? sortedDays[0].key : null,
    },
  };
}

function workingExecution(execution) {
  if (execution?.validated !== true) return false;
  const work = clean(execution.workItemState || execution.work_item_state).toUpperCase();
  const operation = clean(execution.operationState || execution.operation_state).toUpperCase();
  return ['RUNNING', 'DISPATCHED'].includes(work) ||
    ['RUNNING', 'PENDING', 'RESERVED'].includes(operation);
}

/**
 * Estado de apresentação do Dot. `completed`/`succeeded` continuam sendo
 * "resultado registrado", nunca "concluído": só `execution.verified === true`
 * promove a verificado.
 */
export function dotObservation(dot) {
  const row = record(dot);
  const execution = record(row.execution);
  if (completionEvidence(row) && execution.verified === true) {
    return { label: 'concluído · recibo verificado', tone: 'verified', verified: true };
  }
  const status = clean(row.status).toLowerCase();
  const stage = clean(execution.stage || execution.state).toLowerCase();
  if (completionEvidence(row)) {
    return { label: 'concluído · estado verificado', tone: 'verified', verified: true };
  }
  if (APPROVAL_STATES.has(status)) return { label: 'aguardando decisão', tone: 'waiting', verified: false };
  if (UNCERTAIN_STATES.has(status)) return { label: 'incerto · consulte o estado', tone: 'uncertain', verified: false };
  if (FAILURE_STATES.has(status)) return { label: 'falhou · observado', tone: 'failed', verified: false };
  if (COMPLETION_STATES.has(status)) {
    return { label: 'resultado registrado · sem recibo verificado', tone: 'observed', verified: false };
  }
  if (PAUSED_STATES.has(status)) return { label: 'interrompido · observado', tone: 'waiting', verified: false };
  if (WORKING_STATES.has(status) || workingExecution(execution)) {
    return { label: 'em execução · observado', tone: 'observed', verified: false };
  }
  if (!status || ['idle', 'available', 'ready'].includes(status)) {
    return { label: 'ocioso · observado', tone: 'observed', verified: false };
  }
  return { label: 'observado · ' + status, tone: 'observed', verified: false };
}

function card(id, label, value, detail, tone, extra = {}) {
  const verified = extra.verified === true;
  const { verified: ignored, ...rest } = extra;
  return { id, label, value, detail, tone, ...rest, verified };
}

function presentDot(dot) {
  const row = record(dot);
  const observation = dotObservation(row);
  return {
    dot_id: clean(row.dot_id),
    name: clean(row.name) || 'Dot',
    mascot: clean(row.mascot),
    status: clean(row.status),
    role: clean(row.role),
    execution: record(row.execution),
    tone: observation.tone,
    verified: observation.verified,
    observation: observation.label,
  };
}

function providerFrom(id) {
  const value = clean(id);
  const slash = value.indexOf('/');
  return slash > 0 ? value.slice(0, slash) : '';
}

function normalizeModels(models) {
  return list(models).map(item => {
    if (typeof item === 'string') {
      const id = clean(item);
      return id ? { id, label: id, provider: providerFrom(id), available: null } : null;
    }
    if (!item || typeof item !== 'object') return null;
    const id = clean(item.id || item.model_id || item.name);
    if (!id) return null;
    return {
      id,
      label: clean(item.label || item.name || id),
      provider: clean(item.provider || item.provider_id) || providerFrom(id),
      available: item.available === false ? false : item.available === true ? true : null,
    };
  }).filter(Boolean);
}

function providerPills(models) {
  const byId = new Map();
  for (const model of models) {
    const provider = clean(model.provider);
    if (!provider) continue;
    const row = byId.get(provider) || { id: provider, label: provider, count: 0 };
    row.count += 1;
    byId.set(provider, row);
  }
  return [...byId.values()].sort((a, b) => a.label.localeCompare(b.label, 'pt'));
}

function normalizeCapabilities(value) {
  let rows;
  if (Array.isArray(value)) rows = value;
  else if (value && typeof value === 'object') {
    rows = Object.entries(value).map(([id, item]) => ({ id, ...record(item) }));
  } else rows = [];
  return rows.map(item => {
    if (typeof item === 'string') {
      const id = clean(item);
      return id ? { id, label: id, state: '' } : null;
    }
    if (!item || typeof item !== 'object') return null;
    const id = clean(item.capability_id || item.id || item.name || item.label);
    if (!id) return null;
    return {
      id,
      label: clean(item.label || item.name || item.capability_id || item.id) || id,
      state: clean(item.state || item.status || (item.enabled === false ? 'não habilitada' : '')),
    };
  }).filter(Boolean);
}

function collectApprovals(home, events) {
  const rows = [];
  const seen = new Set();
  const add = item => {
    if (!item || !item.id || seen.has(item.id)) return;
    seen.add(item.id);
    rows.push(item);
  };

  for (const conversation of list(home?.conversations)) {
    const state = clean(conversation?.status).toLowerCase();
    if (!APPROVAL_STATES.has(state)) continue;
    const conversationId = clean(conversation?.conversation_id);
    add({
      id: 'conversation:' + (conversationId || rows.length),
      title: clean(conversation?.title || conversation?.name) || 'Conversa',
      reason: state,
      reasonLabel: APPROVAL_LABELS[state] || state,
      label: 'aguardando decisão',
      tone: 'waiting',
      conversation_id: conversationId,
      space_id: clean(conversation?.space_id),
      dot_id: clean(conversation?.dot_id),
      source: 'conversa',
    });
  }

  for (const approval of list(home?.approvals)) {
    const state = clean(approval?.activity || approval?.state || approval?.status).toLowerCase();
    if (['approved', 'rejected', 'resolved'].includes(state)) continue;
    const summary = record(approval?.summary);
    const title = clean(summary.name || summary.kind || summary.summary || approval?.summary);
    const active = state === 'active' || state === 'pending';
    const expired = ['expired', 'stale', 'closed'].includes(state);
    add({
      id: 'approval:' + (clean(approval?.approval_id) || rows.length),
      title: title || 'Solicitação de aprovação',
      reason: state || 'estado não informado',
      reasonLabel: active ? 'aguardando decisão' : expired ? 'expirada' : 'estado não confirmado',
      label: active ? 'aguardando decisão' : expired ? 'expirada' : 'estado não confirmado',
      tone: active ? 'waiting' : 'uncertain',
      conversation_id: clean(approval?.conversation_id),
      space_id: clean(approval?.space_id),
      dot_id: clean(approval?.dot_id),
      source: 'aprovação',
    });
  }

  for (const event of list(events)) {
    const status = clean(event?.payload?.status || event?.payload?.state).toLowerCase();
    const kind = clean(event?.kind);
    const approvalish = /approval/i.test(kind);
    const resolved = /replied|resolved|decided|approved|rejected|denied|expired|cancelled|canceled/i.test(kind);
    if (!APPROVAL_STATES.has(status) && !(approvalish && !resolved)) continue;
    const uncertain = UNCERTAIN_STATES.has(status);
    const eventId = clean(event?.event_id || event?.seq);
    add({
      id: 'event:' + (eventId || rows.length),
      title: clean(event?.payload?.summary) || kind || 'Aprovação',
      reason: status || kind,
      reasonLabel: uncertain ? 'resultado incerto' : (APPROVAL_LABELS[status] || 'aguardando decisão'),
      label: uncertain ? 'incerta' : 'aguardando decisão',
      tone: uncertain ? 'uncertain' : 'waiting',
      conversation_id: clean(event?.payload?.conversation_id || event?.conversation_id),
      space_id: clean(event?.payload?.space_id || event?.space_id),
      dot_id: clean(event?.payload?.dot_id || event?.dot_id),
      source: 'evento',
    });
  }

  return rows;
}

/**
 * Resumo puro das cinco abas do hub. Lê apenas as props; nunca escreve.
 * Retorna arrays de cartões prontos para os cartões de vidro do ShellHub,
 * mais os detalhes que a interface usa (aprovações, Dots, capacidades, pills).
 */
export function hubSections(input = {}) {
  const source = record(input);
  const home = record(source.home);
  const project = record(source.project);
  const space = record(home.space);
  const run = record(home.run);
  const dots = source.dots === undefined ? list(home.dots) : list(source.dots);
  const events = source.events === undefined ? list(record(home.activity).items) : list(source.events);
  const models = list(source.models);

  const capabilities = normalizeCapabilities(home.capabilities);
  const modelPills = normalizeModels(models);
  const providers = providerPills(modelPills);
  const approvals = collectApprovals(home, events);
  const recap = activityRecap(events, { days: 7 });
  const activeDots = dots.slice(0, 6).map(presentDot);

  const projectName = clean(project.name || project.title);
  const projectId = clean(project.project_id || project.id || home.project_id);
  const spaceName = clean(space.name || space.title);
  const spaceId = clean(space.space_id);
  const runState = clean(run.state).toUpperCase();

  const overview = [
    card('project', 'Projeto',
      projectName || 'Não informado nesta leitura',
      projectName
        ? (projectId ? 'Seu projeto selecionado.' : 'Projeto atual.')
        : 'A janela do shell não informou o nome do projeto.',
      projectName ? 'observed' : 'unknown'),
    card('space', 'Space atual',
      spaceName || 'Não informado nesta leitura',
      spaceId ? 'Seu contexto de trabalho atual.' : 'Escolha um Space para começar.',
      spaceName ? 'observed' : 'unknown'),
    card('run', 'Estado do projeto',
      ({ RUNNING: 'Em andamento', PAUSED: 'Pausado', STOPPED: 'Parado', COMPLETED: 'Encerrado', FAILED: 'Precisa de atenção' }[runState] || runState || 'aguardando leitura'),
      runState ? 'Estado atual do projeto.' : 'Atualizando o estado do projeto.',
      runState ? 'observed' : 'unknown'),
    card('dots', 'Dots neste Space', String(dots.length),
      dots.length ? 'Personagens e estados observados; até 6 aparecem abaixo.' : 'Nenhum Dot foi informado nesta leitura.',
      dots.length ? 'observed' : 'unknown'),
    card('approvals', 'Aprovações pendentes',
      approvals.length ? String(approvals.length) : 'nenhuma nesta leitura',
      approvals.length
        ? 'Aguardando decisão humana; o hub não aprova, não rejeita e não repete a operação.'
        : 'Nenhuma solicitação pendente chegou nesta leitura.',
      approvals.length ? 'waiting' : 'info'),
    card('capabilities', 'Capacidades concedidas', String(capabilities.length),
      capabilities.length ? 'Concedidas pelo host; exibidas como observação.' : 'Nenhuma capacidade concedida foi informada nesta leitura.',
      capabilities.length ? 'observed' : 'info'),
  ];

  const companions = dots.length
    ? dots.map(presentDot).map(row => card(
      'companion:' + (row.dot_id || row.name),
      row.name,
      row.observation,
      (row.mascot ? 'Companion ' + row.mascot : 'Companion não informado') +
        (row.status ? ' · estado ' + row.status : ''),
      row.tone,
      { dotId: row.dot_id, mascot: row.mascot, dot: row, verified: row.verified },
    ))
    : [card('companion:none', 'Companions', 'nenhum Dot neste Space',
      'A grade mostra os 17 personagens; nenhum está em uso nesta leitura.', 'info')];

  const datedLatest = recap.days
    .map(day => day.latest)
    .filter(value => Number.isFinite(value))
    .sort((a, b) => b - a)[0];
  const topKinds = Object.entries(recap.byKind)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'pt'))
    .slice(0, 4);

  const activity = [
    card('window', 'Janela observada', 'últimos ' + recap.window.days + ' dias',
      recap.total + (recap.total === 1 ? ' evento observado' : ' eventos observados') +
        ' · ' + recap.verified + ' com recibo ou estado verificado.',
      'observed'),
    card('verified', 'Recibos verificados',
      recap.verified ? String(recap.verified) : 'nenhum nesta janela',
      'Somente recibo registrado ou estado verificado conta. Hook, stop, idle e saída de CLI não são conclusão.',
      recap.verified ? 'verified' : 'info', { verified: recap.verified > 0 }),
    card('undated', 'Eventos sem data',
      recap.undated.count ? String(recap.undated.count) : 'nenhum',
      recap.undated.count
        ? 'Sem created_at/timestamp; ficam fora do agrupamento por dia.'
        : 'Todos os eventos desta janela têm data.',
      recap.undated.count ? 'uncertain' : 'info'),
    card('kinds', 'Tipos observados',
      topKinds.length ? topKinds.map(([kind, count]) => kind + ' · ' + count).join(' · ') : 'nenhum',
      'Contagem por tipo de evento na janela. Não é produtividade oficial.',
      topKinds.length ? 'observed' : 'info'),
    card('latest', 'Evento mais recente',
      datedLatest ? formatWhen(datedLatest) : 'nenhum evento datado',
      datedLatest ? 'Data do evento mais recente nesta janela.' : 'Nenhum evento datado chegou nesta janela.',
      datedLatest ? 'observed' : 'info'),
  ];

  const integrations = [
    card('models', 'Modelos anunciados',
      modelPills.length ? modelPills.length + (modelPills.length === 1 ? ' modelo' : ' modelos') : 'nenhum anunciado',
      modelPills.length
        ? 'Anúncio do catálogo; acesso e execução não estão verificados.'
        : 'Nenhum modelo foi informado nesta leitura.',
      modelPills.length ? 'observed' : 'info'),
    card('providers', 'Provedores observados',
      providers.length ? providers.map(item => item.label).join(' · ') : 'nenhum',
      providers.length
        ? 'Derivados dos identificadores anunciados; não é uma conexão verificada.'
        : 'Nenhum provedor pôde ser derivado dos dados desta leitura.',
      providers.length ? 'observed' : 'info'),
    card('capabilities', 'Capacidades',
      capabilities.length ? String(capabilities.length) : 'nenhuma',
      capabilities.length
        ? 'Concedidas pelo host; o hub não altera permissões.'
        : 'Nenhuma capacidade concedida foi informada nesta leitura.',
      capabilities.length ? 'observed' : 'info'),
    card('readonly', 'Somente leitura', 'sem campos de chave',
      'O hub não lê, não exibe e não armazena credenciais.', 'info'),
  ];

  const about = [
    card('version', 'Versão', BUNDLE_VERSION || 'local',
      'Marcador do bundle desta janela; não é a versão instalada.', 'info'),
    card('attribution', 'Atribuição',
      'Visual inspirado no Coucou (MIT); personagens originais do SENTRA',
      'Nenhum asset, personagem, som ou animação do Coucou/Mochi é copiado.', 'info'),
    card('limits', 'Limites do hub', 'observa e navega; não escreve',
      'O hub chama apenas callbacks do shell e não cria Grants, aprovações ou recibos.', 'info'),
  ];

  return {
    tabs: HUB_TABS,
    overview,
    companions,
    activity,
    integrations,
    about,
    approvals,
    activeDots,
    capabilities,
    models: modelPills,
    providers,
    recap,
    counts: {
      dots: dots.length,
      activeDots: activeDots.length,
      approvals: approvals.length,
      capabilities: capabilities.length,
      models: modelPills.length,
      verifiedEvents: recap.verified,
      verifiedDots: companions.filter(item => item.verified).length,
      totalEvents: recap.total,
    },
  };
}
