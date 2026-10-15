import React, { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { DotMascot } from './shell-mascot';
import { setChevron } from './experience/cadencia/set-chevron.js';
import { useReducedMotion } from './experience/cadencia/use-reduced-motion.js';
import { failureMoreLabel } from './shell-home-board.js';

function RecordLines({ items, render }) {
  if (!items.length) return null;
  return items.map(render);
}

function PendingChevron({ open, reduced }) {
  const motion = setChevron({ open, reduced });
  return <ChevronRight className="cadence-set-chevron" size={motion.size} aria-hidden="true"
    style={{ transform: motion.transform, transition: motion.transition }} />;
}

function FailurePanel({ panel, onConsult }) {
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);
  const [groupLimit, setGroupLimit] = useState(panel.pageSize);
  const [openGroups, setOpenGroups] = useState({});
  const [fullGroups, setFullGroups] = useState({});
  const shown = open ? panel.groups.slice(0, groupLimit) : [];
  const restGroups = panel.groups.length - shown.length;
  return <div className="shell-failure-panel" data-panel={panel.id} data-success="false" data-resend="false">
    <button type="button" className="shell-failure-sum" aria-expanded={open ? 'true' : 'false'}
      onClick={() => setOpen(value => !value)}>
      <strong>{panel.title}</strong>
      <span>{panel.countLabel}</span>
      <PendingChevron open={open} reduced={reduced} />
    </button>
    <p>{panel.note}</p>
    <button type="button" className="shell-failure-consult" data-resend="false" onClick={() => onConsult?.(panel)}>{panel.consult}</button>
    {open && <div className="shell-failure-body">
      {shown.map(group => {
        const expanded = Boolean(openGroups[group.key]);
        const limit = fullGroups[group.key] ? group.items.length : group.pageSize;
        const visible = expanded ? group.items.slice(0, limit) : [];
        const rest = group.items.length - visible.length;
        return <div className="shell-failure-group" key={group.key}>
          <button type="button" className="shell-failure-group-sum" aria-expanded={expanded ? 'true' : 'false'}
            onClick={() => setOpenGroups(value => ({ ...value, [group.key]: !value[group.key] }))}>
            <strong>{group.title}</strong>
            <span>{group.countLabel}</span>
            <PendingChevron open={expanded} reduced={reduced} />
          </button>
          {expanded && visible.map(item => <div className="shell-failure-record" key={item.id}>{item.label}</div>)}
          {expanded && rest > 0 && <button type="button" className="shell-failure-more"
            onClick={() => setFullGroups(value => ({ ...value, [group.key]: true }))}>{failureMoreLabel(rest)}</button>}
        </div>;
      })}
      {restGroups > 0 && <button type="button" className="shell-failure-more"
        onClick={() => setGroupLimit(panel.groups.length)}>{failureMoreLabel(restGroups)}</button>}
    </div>}
  </div>;
}

function FailureSet({ panels, onConsult }) {
  if (!panels.length) return null;
  return <div className="shell-home-sheet shell-home-pending">
    {panels.map(panel => <FailurePanel key={panel.id} panel={panel} onConsult={onConsult} />)}
  </div>;
}

export function HomeBoard({ board, query, onQuery, onContinue, onOpenDot, onOpenSpace, onOpenApproval, onConsultGroup }) {
  const nothing = Boolean(query) && !board.recentDots.length && !board.projects.length
    && !board.approvals.length && !board.deliveries.length && !board.failures.length;
  const panels = board.failurePanels || [];
  return <div className="shell-home-board">
    {board.surface && <button type="button" className="shell-continue" onClick={() => onContinue(board.surface)}>
      Continuar em {board.surface.label}
    </button>}
    {board.focus && <div className="shell-home-focus">
      <h1>{board.focus.name}</h1>
      <div className="shell-home-focus-line">
        <p className="shell-home-support">{board.workSupport || 'O que vamos fazer hoje?'}</p>
        <button type="button" className="shell-home-open-space" onClick={() => onOpenSpace(board.focus)}>Abrir o Space</button>
      </div>
    </div>}
    {board.empty && !query && <p className="shell-home-empty">Ainda não há Dots, conversas ou Spaces neste projeto.</p>}
    {nothing && <p className="shell-home-empty">Nada neste trabalho corresponde à busca.</p>}
    {board.recordsQuiet ? <p className="shell-home-quiet">Nenhuma aprovação, entrega ou falha nesta consulta.</p>
      : <>
        {(board.approvals.length > 0 || board.deliveries.length > 0) && <div className="shell-home-sheet shell-home-records">
          <RecordLines items={board.approvals} render={item => <div className="shell-home-record" key={item.id}>
            <strong>{item.title}</strong>
            {item.kind === 'conversation' ? <button type="button" onClick={() => onOpenApproval(item)}>Abrir</button>
              : <small>Consulte a mesma intenção. Ela não será reenviada daqui.</small>}
          </div>} />
          <RecordLines items={board.deliveries} render={item => <div className="shell-home-record" key={item.id}>
            <strong>{item.title}</strong>
            {item.receipt ? <small>recibo {item.receipt}</small> : null}
          </div>} />
        </div>}
        <FailureSet panels={panels} onConsult={onConsultGroup} />
      </>}
    <label className="shell-search shell-home-search">
      <input id="shell-home-search" value={query} onChange={event => onQuery(event.target.value)}
        placeholder="Buscar no trabalho" aria-label="Buscar no trabalho" />
    </label>
    <h2>Dots recentes</h2>
    {board.recentDots.length ? <div className="shell-home-sheet"><div className="shell-home-list">{board.recentDots.slice(0, 6).map(row =>
      <button type="button" key={row.dot_id} data-phase={row.phase} onClick={() => onOpenDot(row)}>
        <DotMascot mascot={row.mascot} identity={row.agent_id || row.dot_id} name={row.name} status={row.status} execution={row.execution} size="nav" decorative />
        <strong>{row.name}</strong>
        <small className="shell-home-dot-context">{row.context}</small>
        <small data-phase={row.phase} style={{ color: row.factColor }}>{row.fact}</small>
        <ChevronRight size={16} aria-hidden="true" />
      </button>)}</div></div>
      : <p className="shell-home-empty">Nenhum Dot recente neste Space.</p>}
  </div>;
}

function ConversationGroup({ group, onOpen }) {
  const reduced = useReducedMotion();
  const [open, setOpen] = useState(false);
  return <div className="shell-home-conversation-group">
    <button type="button" className="shell-home-conversation-sum" aria-expanded={open ? 'true' : 'false'}
      onClick={() => setOpen(value => !value)}>
      <span className="shell-home-conversation-copy">
        <strong>{group.title}</strong>
        <small className="shell-home-conversation-detail">
          {group.dotLabel ? <span className="shell-home-conversation-dot">{group.dotLabel}</span> : null}
          <span className="shell-home-conversation-meta">{group.meta}</span>
        </small>
      </span>
      <PendingChevron open={open} reduced={reduced} />
    </button>
    {open && group.items.map(item => <button type="button" className="shell-home-conversation-item" key={item.conversation_id}
      data-conversation-id={item.conversation_id} onClick={() => onOpen?.(item)}>
      <strong>{item.whenLabel}</strong>
      <small>{item.dotName}</small>
    </button>)}
  </div>;
}

export function HomeConversationGroups({ groups, onOpen }) {
  if (!groups?.length) return null;
  return <div className="shell-home-sheet shell-home-conversations">
    {groups.map(group => <ConversationGroup key={group.key} group={group} onOpen={onOpen} />)}
  </div>;
}
