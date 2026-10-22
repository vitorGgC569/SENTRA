/*!
 * SENTRA compact decisions — glass cards for owner-visible approvals.
 * Visual inspiration only: Coucou (MIT). Characters and data are SENTRA's own.
 * Cards only transport a decision to `coordinator_approval_reply`; they never
 * grant, retry or execute anything on their own.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BellRing, ChevronDown, MessageCircle } from 'lucide-react';
import { DotMascot } from './shell-mascot';
import { canvasMaintenanceActive } from './shell-maintenance.js';
import {
  DECISION_PREVIEW_LIMITS, decisionExpiry, formatRemaining, summarizeDecision,
} from './shell-decisions.js';
import './shell-decisions.css';
import { DecisionRequests } from './shell-decision-requests.js';

export { DECISION_PREVIEW_LIMITS, decisionExpiry, decisionFingerprint, formatRemaining, summarizeDecision } from './shell-decisions.js';

const LIST_LIMIT = 30;
const ANSWERS = Object.freeze(['approve', 'reject']);

function decisionErrorText(error) {
  if (!error) return '';
  if (error.reauthorizing === true || error.maintenance === true || canvasMaintenanceActive()) return '';
  return typeof error.message === 'string' ? error.message : '';
}

function asDecision(value) {
  if (value && typeof value === 'object' && typeof value.title === 'string' && typeof value.approvalId === 'string') return value;
  return summarizeDecision(value);
}

// One read-only inbox. Pending decisions survive reload as scoped selectors.
export function useDecisionInbox({ bridge, projectId, inlineConversationId, pollMs = 3000 } = {}) {
  const [all, setAll] = useState([]), [pending, setPending] = useState([]);
  const [error, setError] = useState(''), [busy, setBusy] = useState('');
  const bridgeRef = useRef(bridge), generation = useRef(0), requestLock = useRef(false);
  bridgeRef.current = bridge;
  const journalSetup = useMemo(() => {
    try {
      return { client: projectId ? new DecisionRequests(projectId, {
        bridge: request => bridgeRef.current(request),
      }) : null, error: null };
    } catch (cause) { return { client: null, error: cause }; }
  }, [projectId]);
  const requests = journalSetup.client;
  const current = expected => generation.current === expected;
  const readPending = useCallback(() => requests?.pending() || [], [requests]);
  const load = useCallback(async () => {
    if (journalSetup.error) throw Error('O diário de decisões está indisponível. Nenhuma resposta será enviada.');
    const expected = generation.current;
    const rows = readPending();
    if (current(expected)) setPending(rows);
    if (!projectId || typeof bridgeRef.current !== 'function') return;
    const result = await bridgeRef.current({ action: 'coordinator_approval_list', project_id: projectId, limit: LIST_LIMIT });
    if (current(expected)) setAll(Array.isArray(result?.items) ? result.items : []);
  }, [projectId, readPending, journalSetup.error]);
  const refresh = useCallback(async () => {
    const expected = generation.current;
    try { await load(); if (current(expected)) setError(''); }
    catch (cause) { if (current(expected)) setError(decisionErrorText(cause)); }
  }, [load]);
  useEffect(() => {
    generation.current += 1;
    setAll([]); setPending([]); setError(''); setBusy('');
    let loading = false;
    async function poll() {
      if (!projectId || (document.hidden && !window.sentraDesktopPresence?.available) || loading) return;
      loading = true;
      try { await refresh(); } finally { loading = false; }
    }
    void poll();
    const timer = setInterval(poll, Math.max(1000, Number(pollMs) || 3000));
    window.addEventListener('focus', poll);
    window.addEventListener('storage', poll);
    return () => {
      generation.current += 1;
      clearInterval(timer);
      window.removeEventListener('focus', poll);
      window.removeEventListener('storage', poll);
    };
  }, [projectId, pollMs, refresh]);
  const perform = useCallback(async (item, answer, inspect = false) => {
    if (!requests || requestLock.current || !item?.approval_id || (!inspect && !ANSWERS.includes(answer))) return;
    requestLock.current = true;
    const expected = generation.current;
    setBusy(item.approval_id);
    try {
      const result = inspect ? await requests.inspect(item.approval_id) : await requests.send(item, answer);
      if (current(expected)) {
        setPending(readPending());
        setError(result?.resolved === true ? '' : 'A decisão ainda não foi confirmada. Consulte sem repetir.');
        await load();
      }
    } catch (cause) {
      if (current(expected)) {
        try { setPending(readPending()); } catch { /* Keep existing recovery cards. */ }
        setError(decisionErrorText(cause) || 'Consulte a confirmação antes de continuar.');
      }
    } finally {
      requestLock.current = false;
      if (current(expected)) setBusy('');
    }
  }, [requests, readPending, load]);
  const pendingIds = new Set(pending.map(row => row.approval_id));
  const items = all.filter(item => pendingIds.has(item.approval_id) || !inlineConversationId || item.conversation_id !== inlineConversationId);
  for (const row of pending) {
    if (!items.some(item => item.approval_id === row.approval_id)) items.push({
      approval_id: row.approval_id, conversation_id: row.conversation_id, space_id: row.space_id,
      summary: { name: 'Decisão aguardando confirmação' }, activity: 'unknown',
    });
  }
  const total = new Set([...all.map(row => row.approval_id), ...pendingIds].filter(Boolean)).size;
  return { items, total, error, busy, uncertain: [...pendingIds], expired: [], refresh,
    decide: (item, answer) => perform(item, answer), consult: item => perform(item, null, true) };
}

// Local countdown: display only, paused while the tab is hidden, never a decision gate.
// `seed` is the remaining time already produced by decisionExpiry on the host list.
function useDecisionCountdown(expiresAt, seed) {
  const [remaining, setRemaining] = useState(() => {
    if (Number.isFinite(seed)) return Math.max(0, seed);
    return expiresAt ? Math.max(0, expiresAt - Date.now()) : null;
  });
  useEffect(() => {
    if (!expiresAt) { setRemaining(null); return undefined; }
    let timer = 0;
    const tick = () => setRemaining(Math.max(0, expiresAt - Date.now()));
    const start = () => {
      if (timer) return;
      tick();
      timer = window.setInterval(tick, 1000);
    };
    const stop = () => {
      if (!timer) return;
      window.clearInterval(timer);
      timer = 0;
    };
    const onVisibility = () => { if (document.hidden) stop(); else start(); };
    if (document.hidden) tick(); else start();
    document.addEventListener('visibilitychange', onVisibility);
    return () => { stop(); document.removeEventListener('visibilitychange', onVisibility); };
  }, [expiresAt]);
  return remaining;
}

function DecisionPreview({ label, text, truncated, hiddenLines, compact }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return <div className="shell-decisions-preview" data-open={open ? 'true' : 'false'} data-compact={compact ? 'true' : 'false'}>
    <div className="shell-decisions-preview-head">
      <span>{label}</span>
      <button type="button" className="shell-decisions-toggle" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        {open ? 'Recolher' : 'Ver completo'}<ChevronDown size={12} aria-hidden="true" />
      </button>
    </div>
    <pre tabIndex={0} aria-label={label}>{text}</pre>
    {truncated && !open && hiddenLines > 0 && <small className="shell-decisions-hidden">+{hiddenLines} linhas fora da prévia</small>}
    {truncated && open && <small className="shell-decisions-hidden">Prévia limitada a {DECISION_PREVIEW_LIMITS.lines} linhas / {DECISION_PREVIEW_LIMITS.chars} caracteres. O conteúdo original fica no host.</small>}
  </div>;
}

export function DecisionCard({
  decision, busy = false, uncertain = false, expired,
  onDecide, onConsult, onOpenConversation, compact = false,
}) {
  const summary = decision || {};
  const remaining = useDecisionCountdown(summary.expiresAt, summary.remainingMs);
  const isExpired = (expired === undefined ? !summary.active : Boolean(expired)) || remaining === 0;
  const pill = busy ? { tone: 'busy', label: 'Enviando…' }
    : uncertain ? { tone: 'uncertain', label: 'Não confirmado' }
    : isExpired ? { tone: 'expired', label: 'Expirado' }
    : { tone: 'active', label: 'Aguardando você' };
  const command = summary.command
    ? { key: 'command', label: 'Prévia do comando (não verificada)', text: summary.command, truncated: summary.commandTruncated, hiddenLines: summary.commandHiddenLines }
    : null;
  const diff = summary.diff
    ? { key: 'diff', label: 'Prévia de diff (não verificada)', text: summary.diff, truncated: summary.diffTruncated, hiddenLines: summary.diffHiddenLines }
    : null;
  const previews = compact ? [command || diff].filter(Boolean) : [command, diff].filter(Boolean);
  const sentence = summary.capabilityLabel
    ? 'O Dot pediu para ' + summary.capabilityLabel + '. A autorização vale somente neste turno e não repete a instrução anterior.'
    : 'A autorização vale somente neste turno e não repete a instrução anterior.';
  return <article className="shell-decisions-card" data-compact={compact ? 'true' : 'false'}
    data-state={pill.tone} aria-label={'Decisão: ' + (summary.title || 'Ação do Dot')}>
    <header className="shell-decisions-head">
      <span className="shell-decisions-avatar">
        <DotMascot mascot={summary.mascot || undefined} identity={summary.identity || 'oxta'}
          name={summary.title || 'Dot'} size="nav" decorative />
      </span>
      <span className="shell-decisions-headings">
        <strong className="shell-decisions-title">{summary.title || 'Ação do Dot'}</strong>
        <span className="shell-decisions-meta">
          {summary.capability && <code>{summary.capability}</code>}
          {summary.expiresAt && <span className="shell-decisions-validity" aria-hidden="true">{isExpired ? 'Prazo encerrado' : formatRemaining(remaining)}</span>}
        </span>
      </span>
      <span className="shell-decisions-pill" data-tone={pill.tone}>{pill.label}</span>
    </header>
    <p className="shell-decisions-summary">{sentence}</p>
    {previews.map(preview => <DecisionPreview key={preview.key} label={preview.label} text={preview.text}
      truncated={preview.truncated} hiddenLines={preview.hiddenLines} compact={compact} />)}
    {uncertain && <p className="shell-decisions-note" role="status">
      A decisão ainda não foi confirmada pelo host. Consulte sem repetir; o pedido original será consultado, nunca reenviado automaticamente.
    </p>}
    {isExpired && !uncertain && <p className="shell-decisions-note" data-tone="expired">
      O turno original terminou. Nenhuma execução será repetida; peça uma nova ação ao Dot se precisar.
    </p>}
    <footer className="shell-decisions-actions">
      {!isExpired && !uncertain && <button type="button" className="shell-decisions-button is-primary" disabled={busy}
        onClick={() => onDecide?.('approve')}>Autorizar</button>}
      {!uncertain && <button type="button" className="shell-decisions-button" disabled={busy}
        onClick={() => onDecide?.('reject')}>{isExpired ? 'Dispensar aviso' : 'Rejeitar'}</button>}
      {uncertain && <button type="button" className="shell-decisions-button" disabled={busy}
        onClick={() => onConsult?.()}>Consultar sem repetir</button>}
      {summary.conversationId && <button type="button" className="shell-decisions-button is-quiet" disabled={busy}
        onClick={() => onOpenConversation?.()}><MessageCircle size={12} aria-hidden="true" />Ver conversa</button>}
    </footer>
  </article>;
}

export function DecisionStack({
  decisions = [], busyId = '', uncertainIds = [], expiredIds = [],
  onDecide, onConsult, onOpenConversation, compact = false, maxVisible = 3, emptyLabel = '',
}) {
  const [expanded, setExpanded] = useState(false);
  const rows = useMemo(() => (Array.isArray(decisions) ? decisions : []).map(asDecision), [decisions]);
  const uncertainSet = useMemo(() => new Set(uncertainIds), [uncertainIds]);
  const expiredSet = useMemo(() => new Set(expiredIds), [expiredIds]);
  const limit = Math.max(1, Number(maxVisible) || 3);

  useEffect(() => { if (rows.length <= limit) setExpanded(false); }, [rows.length, limit]);
  if (!rows.length) return emptyLabel ? <p className="shell-decisions shell-decisions-empty" role="status">{emptyLabel}</p> : null;
  const shown = expanded ? rows : rows.slice(0, limit);
  const hidden = rows.length - shown.length;
  return <div className={'shell-decisions shell-decisions-stack' + (compact ? ' is-compact' : '')}>
    <ul className="shell-decisions-list">
      {shown.map(decision => <li key={decision.fingerprint || decision.approvalId}>
        <DecisionCard decision={decision} compact={compact}
          busy={busyId === decision.approvalId}
          uncertain={uncertainSet.has(decision.approvalId)}
          expired={expiredSet.has(decision.approvalId) || decision.expired}
          onDecide={answer => onDecide?.(decision, answer)}
          onConsult={() => onConsult?.(decision)}
          onOpenConversation={() => onOpenConversation?.(decision)} />
      </li>)}
    </ul>
    {(hidden > 0 || (expanded && rows.length > limit)) && <div className="shell-decisions-more">
      {hidden > 0
        ? <button type="button" aria-expanded="false" onClick={() => setExpanded(true)}>+{hidden} outras</button>
        : <button type="button" aria-expanded="true" onClick={() => setExpanded(false)}>Mostrar menos</button>}
    </div>}
  </div>;
}

export function ShellDecisionCenter({
  bridge, projectId, inlineConversationId, onOpenConversation, pollMs = 3000,
  shellError = '', title = 'Decisões pendentes', compact = false, maxVisible = 3, className = '',
  onCount,
}) {
  const [revealed, setRevealed] = useState(false);
  const inbox = useDecisionInbox({ bridge, projectId, inlineConversationId: revealed ? undefined : inlineConversationId, pollMs });
  const itemsById = useMemo(() => {
    const map = new Map();
    for (const item of inbox.items) if (item?.approval_id) map.set(item.approval_id, item);
    return map;
  }, [inbox.items]);
  const now = Date.now();
  const decisions = inbox.items.map(item => {
    const model = summarizeDecision(item);
    const expiry = decisionExpiry(item, now);
    return { ...model, expired: expiry.expired, remainingMs: expiry.remainingMs };
  });
  const visibleError = inbox.error && inbox.error !== shellError ? inbox.error : '';
  const onCountRef = useRef(onCount); onCountRef.current = onCount;
  const regionRef = useRef(null);
  useEffect(() => {
    const reveal = () => {
      setRevealed(true);
      requestAnimationFrame(() => { regionRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }); regionRef.current?.focus(); });
    };
    window.addEventListener('sentra:decisions:reveal', reveal);
    return () => window.removeEventListener('sentra:decisions:reveal', reveal);
  }, []);
  const decisionCount = decisions.length;
  useEffect(() => { onCountRef.current?.(inbox.total); }, [inbox.total]);
  if (!decisionCount && !visibleError && !revealed) return null;
  const decide = (decision, answer) => {
    const item = itemsById.get(decision.approvalId);
    if (item) void inbox.decide(item, answer);
  };
  const consult = decision => {
    const item = itemsById.get(decision.approvalId);
    if (item) void inbox.consult(item);
  };
  const openConversation = decision => {
    if (decision.conversationId) onOpenConversation?.(decision.conversationId, decision.spaceId);
  };
  return <div ref={regionRef} tabIndex={-1} className={('shell-decisions shell-decisions-center ' + className).trim()}
    role="region" aria-live="polite" aria-label="Decisões pendentes do SENTRA">
    <div className="shell-decisions-panel">
      <header className="shell-decisions-center-head">
        <BellRing size={16} aria-hidden="true" />
        <strong>{title}</strong>
        <span className="shell-decisions-count" aria-label={decisions.length + ' solicitações pendentes'}>{decisions.length}</span>
      </header>
      {!decisionCount && !visibleError && <p className="shell-decisions-empty">Nenhuma aprovação pendente neste projeto.</p>}
      <DecisionStack decisions={decisions} compact={compact} maxVisible={maxVisible}
        busyId={inbox.busy} uncertainIds={inbox.uncertain} expiredIds={inbox.expired}
        onDecide={decide} onConsult={consult} onOpenConversation={openConversation} />
      {visibleError && <p className="shell-decisions-error" role="alert">{visibleError}</p>}
    </div>
  </div>;
}
