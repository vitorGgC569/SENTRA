/*!
 * SENTRA island presence state.
 * Visual inspiration only: Coucou (MIT). Characters and data stay SENTRA-native.
 * Pure helpers: no timers, no DOM, no bridge calls.
 */
import { mascotMotionState, validatedExecutionIsWorking } from './dot-motion.js';
import { completionEvidence } from './shell-completion-evidence.js';

const WAITING = new Set(['waiting_approval', 'waiting_chatgpt_user_approval', 'needs_input', 'uncertain', 'unconfirmed']);
const FAILED = new Set(['failed', 'error', 'expired', 'interrupted', 'cancelled', 'canceled', 'blocked']);
const DONE = new Set(['completed', 'succeeded', 'verified']);
const WORKING = new Set(['running', 'dispatched', 'sending', 'queued', 'pending', 'starting', 'active', 'in_progress', 'reserved']);

const TONE_LABEL = {
  work: 'Trabalhando',
  wait: 'Aguardando você',
  error: 'Falhou',
  done: 'Concluído e verificado',
  review: 'Resultado registrado',
  idle: 'Ocioso',
};

/** Presentation tone for a Dot. Success requires explicit verification. */
export function islandTone(status, execution) {
  if (validatedExecutionIsWorking(execution)) return 'work';
  const value = String(status || '').toLowerCase();
  if (WAITING.has(value)) return 'wait';
  if (FAILED.has(value)) return 'error';
  if (DONE.has(value)) return completionEvidence({ status, execution }) ? 'done' : 'review';
  if (WORKING.has(value)) return 'work';
  const phase = mascotMotionState(status, execution);
  if (phase === 'working') return 'work';
  if (phase === 'needs-input') return 'wait';
  return 'idle';
}

export function islandStatusLabel(status, execution) {
  return TONE_LABEL[islandTone(status, execution)];
}

function millis(value) {
  const raw = typeof value === 'number' || /^\d+(\.\d+)?$/.test(String(value)) ? Number(value) : NaN;
  const parsed = Number.isFinite(raw) ? (raw < 1e11 ? raw * 1000 : raw) : Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function newest(values) {
  let best = 0, chosen = '';
  for (const value of values) {
    const stamp = millis(value);
    if (stamp >= best && value) { best = stamp; chosen = value; }
  }
  return { stamp: best, value: chosen };
}

/** One row per Dot: current tone, last known activity and its conversation. */
export function islandSessions({ dots = [], conversations = [], events = [], limit = 6 } = {}) {
  const conversationByDot = new Map();
  for (const row of conversations) {
    if (!row?.dot_id || conversationByDot.has(row.dot_id)) continue;
    conversationByDot.set(row.dot_id, row);
  }
  const lastEventByDot = new Map();
  for (const event of events) {
    const dotId = event?.payload?.dot_id || event?.dot_id;
    if (!dotId || lastEventByDot.has(dotId)) continue;
    lastEventByDot.set(dotId, event);
  }
  const priority = { wait: 0, error: 1, work: 2, review: 3, done: 4, idle: 5 };
  const sessions = dots.filter(row => row?.dot_id).map(dot => {
    const conversation = conversationByDot.get(dot.dot_id) || null;
    const event = lastEventByDot.get(dot.dot_id) || null;
    const tone = islandTone(dot.status, dot.execution);
    const stamp = newest([dot.updated_at, conversation?.updated_at, event?.created_at]);
    const eventStatus = event?.payload?.status || event?.payload?.state;
    // An old receipt must not contradict the Dot's current state (for example,
    // a verified receipt from another turn while this Dot has failed).
    const eventDetail = event && (!eventStatus || eventStatus === dot.status) ? event.payload?.summary : '';
    return {
      id: dot.dot_id,
      dotId: dot.dot_id,
      conversationId: conversation?.conversation_id || null,
      spaceId: dot.space_id || conversation?.space_id || null,
      name: dot.name || 'Dot',
      mascot: dot.mascot,
      identity: dot.agent_id || dot.dot_id,
      status: dot.status || 'idle',
      tone,
      label: TONE_LABEL[tone],
      detail: eventDetail || conversation?.title || TONE_LABEL[tone],
      updatedAt: stamp.value || '',
      updatedAtMs: stamp.stamp,
      conversation,
      dot,
    };
  }).sort((a, b) => (priority[a.tone] ?? 9) - (priority[b.tone] ?? 9)
    || b.updatedAtMs - a.updatedAtMs
    || String(a.name).localeCompare(String(b.name), 'pt-BR'));
  return sessions.slice(0, Math.max(0, limit));
}

export function islandSummary(sessions = [], decisions = []) {
  const active = sessions.filter(row => ['work', 'wait', 'error'].includes(row.tone));
  return {
    active: active.length,
    working: sessions.filter(row => row.tone === 'work').length,
    waiting: sessions.filter(row => ['wait', 'error'].includes(row.tone)).length,
    decisions: decisionTotal(decisions),
    total: sessions.length,
  };
}

/** Accepts either a summary array or the host's already-counted total. */
export function decisionTotal(value) {
  if (Number.isInteger(value)) return Math.max(0, value);
  return Array.isArray(value) ? value.filter(Boolean).length : 0;
}

/** Attention badge: pending decisions plus sessions that need the owner. */
export function islandBadge(sessions = [], decisions = []) {
  return decisionTotal(decisions)
    + sessions.filter(row => ['wait', 'error'].includes(row.tone)).length;
}

export function islandClock(createdAt) {
  const stamp = millis(createdAt);
  if (!stamp) return '';
  try {
    return new Date(stamp).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
}

/** Recent events for the short ticker. Undated or stale events are skipped. */
export function islandTicker(events = [], { limit = 4, now = 0, maxAgeMs = 15 * 60 * 1000 } = {}) {
  const reference = Number(now) || Date.now();
  const rows = [];
  for (const event of events) {
    const stamp = millis(event?.created_at || event?.timestamp);
    if (!stamp || reference - stamp > maxAgeMs) continue;
    const tone = islandTone(event?.payload?.status || event?.payload?.state, null);
    rows.push({
      id: event.event_id || String(event.seq ?? '') || 'event',
      kind: event.kind || event.type || 'Atividade',
      summary: event.payload?.summary || '',
      status: event.payload?.status || '',
      tone,
      time: islandClock(stamp),
      stamp,
    });
    if (rows.length >= limit * 3) break;
  }
  return rows.sort((a, b) => b.stamp - a.stamp).slice(0, Math.max(0, limit));
}

export function islandGreeting(now = 0) {
  const date = new Date(Number(now) || Date.now());
  const hour = date.getHours();
  if (hour < 5) return 'Boa noite';
  if (hour < 12) return 'Bom dia';
  if (hour < 18) return 'Boa tarde';
  return 'Boa noite';
}

/** The island stays visible while enabled; `hideWhenIdle` makes it work-only. */
export function islandShouldShow({ enabled, sessions = [], decisions = [], hideWhenIdle = false } = {}) {
  if (!enabled) return false;
  if (!hideWhenIdle) return true;
  return sessions.length > 0 || decisionTotal(decisions) > 0;
}
