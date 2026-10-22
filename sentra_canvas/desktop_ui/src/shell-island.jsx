/*!
 * SENTRA island presence. Visual inspiration only: Coucou (MIT).
 * All state comes from SENTRA props; this surface never approves or executes.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Layers, Pin, PinOff, ShieldAlert, Sparkles, X } from 'lucide-react';
import { DotMascot } from './shell-mascot';
import {
  islandBadge, islandGreeting, islandSessions, islandShouldShow, islandSummary, islandTicker,
} from './shell-island-state.js';
import './shell-island.css';

export function ShellIsland({
  enabled, onToggle, dots = [], conversations = [], events = [], decisions = [],
  decisionSlot = null, projectName = '', onOpenConversation, onOpenCanvas, onOpenHub, onReviewDecisions,
  hideWhenIdle = false,
}) {
  const root = useRef(null);
  const hoverTimer = useRef(0);
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const sessions = useMemo(() => islandSessions({ dots, conversations, events, limit: 6 }), [dots, conversations, events]);
  const pending = Array.isArray(decisions) ? decisions.length : Number.isInteger(decisions) ? Math.max(0, decisions) : 0;
  const ticker = useMemo(() => islandTicker(events, { limit: 4, now: Date.now() }), [events]);
  const visible = islandShouldShow({ enabled, sessions, decisions: pending, hideWhenIdle });
  const summary = islandSummary(sessions, pending);
  const badge = islandBadge(sessions, pending);
  const current = sessions[0] || null;
  const activeSessions = sessions.filter(row => row.tone !== 'idle');

  useEffect(() => {
    if (!visible) { setOpen(false); setPinned(false); }
  }, [visible]);
  useEffect(() => {
    const openEvent = () => { setOpen(true); setPinned(true); };
    const toggleEvent = () => { setOpen(value => !value); setPinned(true); };
    window.addEventListener('sentra:island-open', openEvent);
    window.addEventListener('sentra:island-toggle', toggleEvent);
    return () => {
      window.removeEventListener('sentra:island-open', openEvent);
      window.removeEventListener('sentra:island-toggle', toggleEvent);
    };
  }, []);
  useEffect(() => {
    if (!open) return undefined;
    const down = event => {
      if (event.target instanceof Element && event.target.closest('[data-island-toggle]')) return;
      if (!root.current?.contains(event.target)) { setOpen(false); setPinned(false); }
    };
    const key = event => { if (event.key === 'Escape') { event.preventDefault(); setOpen(false); setPinned(false); } };
    document.addEventListener('pointerdown', down);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('pointerdown', down); document.removeEventListener('keydown', key); };
  }, [open]);
  useEffect(() => () => window.clearTimeout(hoverTimer.current), []);
  function scheduleOpen() {
    if (!visible || open) return;
    window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => setOpen(true), 260);
  }
  function scheduleClose() {
    window.clearTimeout(hoverTimer.current);
    if (pinned) return;
    hoverTimer.current = window.setTimeout(() => setOpen(false), 420);
  }
  function toggle() {
    window.clearTimeout(hoverTimer.current);
    if (!open) { setOpen(true); setPinned(true); return; }
    if (pinned) { setPinned(false); setOpen(false); return; }
    setPinned(true);
  }
  if (!visible) return null;
  const tone = current?.tone || 'idle';
  return <div ref={root} className={'shell-island' + (open ? ' is-open' : '')} data-tone={tone} data-pinned={pinned ? 'true' : 'false'}>
    <div className="shell-island-anchor" onMouseEnter={scheduleOpen} onMouseLeave={scheduleClose}>
      <button type="button" className="shell-island-pill" aria-expanded={open} aria-haspopup="dialog"
        aria-label={(open ? 'Recolher' : 'Abrir') + ' a ilha do Oxta. ' + (current?.name || 'Oxta') + ' · ' + (current?.label || 'Observando')}
        title={(current?.name || 'Oxta') + ' · ' + (current?.label || 'Observando')} onClick={toggle}>
        <span className="shell-island-avatar">
          <DotMascot mascot={current?.mascot} identity={current?.identity || 'oxta'} name={current?.name || 'Oxta'}
            status={current?.status} execution={current?.dot?.execution} size="island" decorative />
        </span>
        <span className="shell-island-copy">
          <strong>{current?.name || 'Oxta'}</strong>
          <small>{current?.label || 'Observando'}</small>
        </span>
        {badge > 0 && <span className="shell-island-badge" aria-label={badge + ' itens precisam de atenção'}>{badge}</span>}
        <ChevronDown size={14} className="shell-island-caret" aria-hidden="true" />
      </button>
      {open && <div className="shell-island-panel" role="dialog" aria-label="Ilha do Oxta">
        <header className="shell-island-head">
          <div>
            <span className="shell-island-eyebrow">ILHA DO OXTA</span>
            <strong>{islandGreeting()}{projectName ? ', ' + projectName : ''}</strong>
            <small>{summary.active
              ? summary.active + ' em atividade' + (summary.waiting ? ' · ' + summary.waiting + ' precisam de você' : '')
              : 'Tudo tranquilo por aqui'}</small>
          </div>
          <div className="shell-island-head-actions">
            <button type="button" className="shell-island-icon" onClick={() => setPinned(value => !value)}
              aria-pressed={pinned} title={pinned ? 'Desafixar a ilha' : 'Manter a ilha aberta'}>
              {pinned ? <Pin size={14} aria-hidden="true" /> : <PinOff size={14} aria-hidden="true" />}
            </button>
            <button type="button" className="shell-island-icon" title="Ocultar a ilha"
              onClick={() => { setOpen(false); setPinned(false); onToggle?.(); }}>
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        </header>
        {activeSessions.length > 0
          ? <section className="shell-island-section" aria-label="Dots em atividade">
            <h3>Agora</h3>
            <div className="shell-island-sessions">
              {activeSessions.slice(0, 3).map(row => <button type="button" key={row.id} className="shell-island-session"
                data-tone={row.tone} onClick={() => { onOpenConversation?.(row); setOpen(false); setPinned(false); }}>
                <span className="shell-island-session-avatar">
                  <DotMascot mascot={row.mascot} identity={row.identity} name={row.name} status={row.status}
                    execution={row.dot?.execution} size="nav" decorative />
                </span>
                <span className="shell-island-session-copy"><strong>{row.name}</strong><small>{row.detail}</small></span>
                <span className="shell-island-session-tone" data-tone={row.tone} aria-label={row.label} title={row.label} />
              </button>)}
            </div>
            {activeSessions.length > 3 && <p className="shell-island-more">+{activeSessions.length - 3} outros Dots em atividade</p>}
          </section>
          : <section className="shell-island-section shell-island-quiet">
            <DotMascot mascot="oxta" name="Oxta" size="intro" decorative />
            <p>Tudo tranquilo. O Oxta observa o seu trabalho.</p>
          </section>}
        {(pending > 0 || decisionSlot) && <section className="shell-island-section shell-island-decisions" aria-label="Decisões pendentes">
          <h3>Precisa de você{pending > 0 && <span>{pending}</span>}</h3>
          {decisionSlot || <p className="shell-island-more">{pending === 1
            ? '1 solicitação aguardando decisão do proprietário.'
            : pending + ' solicitações aguardando decisão do proprietário.'}</p>}
          <button type="button" className="shell-island-link" onClick={() => { onReviewDecisions?.(); setOpen(false); }}>
            Revisar decisões <ShieldAlert size={13} aria-hidden="true" />
          </button>
        </section>}
        {ticker.length > 0 && <section className="shell-island-section" aria-label="Atividade recente">
          <h3>Atividade recente</h3>
          <ol className="shell-island-ticker">
            {ticker.map(row => <li key={row.id} data-tone={row.tone}>
              <time>{row.time}</time>
              <span><strong>{row.summary || row.kind}</strong><small>{row.kind}</small></span>
            </li>)}
          </ol>
        </section>}
        <footer className="shell-island-foot">
          <button type="button" onClick={() => { onOpenHub?.(); setOpen(false); }}>
            <Sparkles size={14} aria-hidden="true" />Central do Oxta
          </button>
          <button type="button" onClick={() => { onOpenCanvas?.(); setOpen(false); }}>
            <Layers size={14} aria-hidden="true" />Canvas
          </button>
        </footer>
      </div>}
    </div>
  </div>;
}
