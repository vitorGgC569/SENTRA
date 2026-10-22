/*!
 * SENTRA compact decisions — pure presentation helpers.
 * Visual inspiration only: Coucou (MIT). Characters and data are SENTRA's own.
 * This module never reads the clock and never talks to the host:
 * approval authority stays in the coordinator APIs.
 */

export const DECISION_PREVIEW_LIMITS = Object.freeze({ lines: 12, chars: 1200 });

const KIND_LABELS = Object.freeze({
  create_dot: 'Criar um Dot',
  dot_create: 'Criar um Dot',
  create_team: 'Organizar uma equipe',
  connect: 'Conectar Dots',
  delegate: 'Delegar trabalho',
  handoff: 'Enviar uma instrução',
  pause: 'Pausar o trabalho',
  resume: 'Retomar o trabalho',
  cancel: 'Cancelar o trabalho',
});

const CAPABILITY_LABELS = Object.freeze({
  dot_create: 'criar Dot',
  create_dot: 'criar Dot',
  create_team: 'organizar equipe',
  connect: 'conectar Dots',
  delegate: 'delegar trabalho',
  handoff: 'enviar instrução',
  pause: 'pausar trabalho',
  resume: 'retomar trabalho',
  cancel: 'cancelar trabalho',
  execute: 'executar',
  write: 'escrever arquivo',
});

// Values after these keys are masked before any preview reaches the renderer.
const SECRET_ASSIGNMENT = /(^|[\s"'`(+-])((?:authorization|proxy-authorization|token|access[_-]?token|refresh[_-]?token|secret|client[_-]?secret|password|passwd|api[_-]?key|access[_-]?key|private[_-]?key))(\s*[:=]\s*)(?:(?:bearer|basic)\s+)?("[^"\n]*"|'[^'\n]*'|[^\s,;&|]+)/gi;
const SECRET_FLAG = /(^|\s)(--?(?:token|secret|password|passwd|api-key|apikey|authorization))(\s+|=)("[^"\n]*"|'[^'\n]*'|[^\s,;&|]+)/gi;
const SECRET_BEARER = /\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}/gi;

export function redactSecrets(value) {
  return String(value ?? '')
    .replace(SECRET_ASSIGNMENT, (match, prefix, key, separator) => prefix + key + separator + '•••')
    .replace(SECRET_FLAG, (match, prefix, flag, separator) => prefix + flag + separator + '•••')
    .replace(SECRET_BEARER, (match, scheme) => scheme + ' •••');
}

function scalar(value) {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return '';
}

function cleanId(value) {
  return redactSecrets(scalar(value)).trim().slice(0, 160);
}

function cleanInline(value, max = 160) {
  return redactSecrets(scalar(value)).replace(/\s+/g, ' ').trim().slice(0, max);
}

function firstText(...values) {
  for (const value of values) {
    const text = scalar(value).trim();
    if (text) return text;
  }
  return '';
}

function parseInstant(value) {
  if (value === null || value === undefined || value === '') return null;
  const numeric = typeof value === 'number' || (typeof value === 'string' && /^\d+(?:\.\d+)?$/.test(value.trim()));
  if (!numeric) {
    const parsed = Date.parse(String(value));
    return Number.isFinite(parsed) ? parsed : null;
  }
  const timestamp = Number(value);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return null;
  // SENTRA stores Unix seconds; other providers may send milliseconds.
  return Math.abs(timestamp) < 1e11 ? timestamp * 1000 : timestamp;
}

function capabilityLabel(capability) {
  if (!capability) return '';
  const tail = capability.split(/[.:/]/).filter(Boolean).pop() || capability;
  return CAPABILITY_LABELS[tail] || tail.replace(/[_-]+/g, ' ');
}

export function limitPreview(value, limits = DECISION_PREVIEW_LIMITS) {
  const maxLines = Math.max(1, Number(limits?.lines) || DECISION_PREVIEW_LIMITS.lines);
  const maxChars = Math.max(1, Number(limits?.chars) || DECISION_PREVIEW_LIMITS.chars);
  const full = redactSecrets(scalar(value)).replace(/\r\n?/g, '\n').replace(/^\n+|\s+$/g, '');
  if (!full) return { text: '', truncated: false, totalLines: 0, hiddenLines: 0 };
  const lines = full.split('\n');
  let text = lines.slice(0, maxLines).join('\n');
  let hiddenLines = Math.max(0, lines.length - maxLines);
  if (text.length > maxChars) {
    text = text.slice(0, maxChars).replace(/[\uD800-\uDBFF]$/, '');
    hiddenLines = Math.max(hiddenLines, lines.length - text.split('\n').length);
  }
  return { text, truncated: hiddenLines > 0 || text.length < full.length, totalLines: lines.length, hiddenLines };
}

// Stable, non-sensitive identity for React keys and duplicate guards.
// Format: `approval_id|capability|kind|conversation_id`, each part capped at 160 chars.
export function decisionFingerprint(item) {
  const summary = item?.summary && typeof item.summary === 'object' ? item.summary : {};
  return [
    cleanId(item?.approval_id),
    cleanId(item?.capability),
    cleanId(summary.kind ?? item?.kind),
    cleanId(item?.conversation_id ?? item?.conversationId),
  ].join('|');
}

// `now` is epoch milliseconds. `expires_at` accepts Unix seconds or milliseconds;
// `activity !== 'active'` always counts as expired. Never reads the clock itself.
export function decisionExpiry(item, now) {
  const summary = item?.summary && typeof item.summary === 'object' ? item.summary : {};
  const expiresAt = parseInstant(item?.expires_at ?? item?.expiresAt ?? summary.expires_at ?? summary.expiresAt);
  const instant = typeof now === 'number' ? now : Number(now);
  const hasNow = Number.isFinite(instant);
  const remainingMs = expiresAt === null || !hasNow ? null : Math.max(0, expiresAt - instant);
  const activityExpired = item?.activity !== 'active';
  const timeExpired = expiresAt !== null && hasNow && instant >= expiresAt;
  return { expiresAt, remainingMs, expired: activityExpired || timeExpired };
}

export function formatRemaining(remainingMs) {
  if (remainingMs === null || remainingMs === undefined || !Number.isFinite(remainingMs)) return '';
  if (remainingMs <= 0) return 'tempo esgotado';
  const total = Math.ceil(remainingMs / 1000);
  if (total < 60) return 'expira em ' + total + ' s';
  if (total < 3600) {
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return 'expira em ' + minutes + ':' + String(seconds).padStart(2, '0');
  }
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return 'expira em ' + hours + ' h ' + String(minutes).padStart(2, '0') + ' min';
}

// Presentation model for one durable request. Whitelisted fields only; command and
// diff are redacted and bounded to DECISION_PREVIEW_LIMITS before leaving this module.
export function summarizeDecision(item) {
  const source = item && typeof item === 'object' ? item : {};
  const summary = source.summary && typeof source.summary === 'object' ? source.summary : {};
  const kind = cleanInline(summary.kind ?? source.kind, 80);
  const capability = cleanInline(source.capability, 160);
  const name = cleanInline(summary.name, 120);
  const label = capabilityLabel(capability);
  const title = name || KIND_LABELS[kind] || (label ? label.charAt(0).toUpperCase() + label.slice(1) : '') || 'Ação do Dot';
  const command = limitPreview(firstText(summary.command, source.command,
    summary.arguments?.command, source.arguments?.command));
  const diff = limitPreview(firstText(summary.diff, source.diff, summary.diff_text, source.diff_text,
    summary.patch, source.patch, summary.arguments?.diff, source.arguments?.diff, source.arguments?.patch));
  const arguments_ = source.arguments && typeof source.arguments === 'object' ? source.arguments : {};
  return {
    approvalId: cleanId(source.approval_id ?? summary.approval_id),
    fingerprint: decisionFingerprint(source),
    kind,
    title,
    capability,
    capabilityLabel: label,
    command: command.text,
    commandTruncated: command.truncated,
    commandHiddenLines: command.hiddenLines,
    diff: diff.text,
    diffTruncated: diff.truncated,
    diffHiddenLines: diff.hiddenLines,
    conversationId: cleanId(source.conversation_id ?? source.conversationId ?? summary.conversation_id),
    spaceId: cleanId(source.space_id ?? source.spaceId ?? summary.space_id),
    expiresAt: parseInstant(source.expires_at ?? source.expiresAt ?? summary.expires_at ?? summary.expiresAt),
    createdAt: parseInstant(source.created_at ?? source.createdAt ?? summary.created_at),
    active: source.activity === 'active',
    automaticExecution: source.automatic_execution === true,
    mascot: cleanId(source.mascot ?? summary.mascot),
    identity: cleanId(source.identity ?? summary.identity ?? arguments_.dot_id ?? source.dot_id ?? source.agent_id),
  };
}
