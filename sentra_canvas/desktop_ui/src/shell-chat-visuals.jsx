// Coucou visual layer (Frente 3).
// Apresentação compacta da conversa: presença do Dot, ticker e pills.
// Nenhuma chamada de bridge, polling ou timeline paralela vive aqui.

import React from 'react';
import {
  Activity, CircleAlert, CircleCheck, Layers, ReceiptText, ShieldCheck, Wrench,
} from 'lucide-react';
import { DotMascot } from './shell-mascot';
import {
  CHAT_PRESENCE_STATES, PILL_KINDS, chatEventPillFor, chatPresenceModel, deriveChatTicker, hasCompletionEvidence,
} from './shell-chat-visuals.js';
import './shell-chat-visuals.css';

const PRESENCE_STATES = new Set(CHAT_PRESENCE_STATES);
const PRESENCE_FALLBACK = Object.freeze({
  state: 'idle', label: 'Presente', detail: '', verified: false, lastAction: '',
});

const TICKER_ICONS = {
  tool: Wrench,
  approval: ShieldCheck,
  receipt: ReceiptText,
  uncertain: CircleAlert,
  error: CircleAlert,
  done: CircleCheck,
  working: Activity,
};

function tickerTime(value) {
  if (value === null || value === undefined || value === '') return '';
  const date = typeof value === 'number' ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

/** Faixa compacta de presença: mascote, nome, estado real, modelo e Canvas. */
export function ChatPresence({ dot, model, onOpenCanvas, onOpenDot, showIdentity = true }) {
  const presence = model && typeof model === 'object' ? model : PRESENCE_FALLBACK;
  const requestedState = presence.state || 'idle';
  const normalizedState = PRESENCE_STATES.has(requestedState) ? requestedState : 'idle';
  const verified = normalizedState === 'done' && presence.verified === true;
  const state = normalizedState === 'done' && !verified ? 'idle' : normalizedState;
  const label = normalizedState === 'done' && !verified ? 'Presente' : (presence.label || 'Presente');
  const name = dot?.name || 'Dot';
  const dotModel = dot?.model;
  const modelName = typeof model === 'string' ? model
    : typeof dotModel === 'string' ? dotModel
      : typeof dotModel?.name === 'string' ? dotModel.name
        : typeof dotModel?.id === 'string' ? dotModel.id : '';
  const avatar = showIdentity ? <DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id}
    name={name} status={dot?.status} execution={dot?.execution} size="presence" decorative /> : null;
  const summary = name + ' · ' + label +
    (presence.detail ? ' · ' + presence.detail : '');
  return <div className="shell-chat-presence" data-state={state}
    data-verified={verified ? 'true' : 'false'} data-identity={showIdentity ? 'true' : 'false'}
    role="group" aria-label={summary}>
    {showIdentity && (onOpenDot ? <button type="button" className="shell-chat-presence-avatar" onClick={onOpenDot}
      aria-label={'Abrir detalhes de ' + name}>{avatar}</button> :
      <span className="shell-chat-presence-avatar">{avatar}</span>)}
    {showIdentity && <span className="shell-chat-presence-name" title={name}>{name}</span>}
    <span className="shell-chat-presence-pill" data-state={state}
      title={presence.detail || label}>
      {verified ? <CircleCheck size={13} aria-hidden="true" /> :
        <span className="shell-chat-presence-dot" aria-hidden="true" />}
      {label}
    </span>
    {presence.detail && <span className="shell-chat-presence-detail" title={presence.detail}>{presence.detail}</span>}
    {modelName && <span className="shell-chat-presence-model" title={modelName}>{modelName}</span>}
    {onOpenCanvas && <button type="button" className="shell-chat-presence-canvas" onClick={onOpenCanvas}
      title="Abrir Canvas"><Layers size={13} aria-hidden="true" /><span>Canvas</span></button>}
  </div>;
}

/** Ticker curto de passos já carregados. Sem polling próprio. */
export function ChatTicker({ items, muted = false }) {
  if (!Array.isArray(items) || !items.length) return null;
  return <section className={'shell-chat-ticker' + (muted ? ' is-muted' : '')}
    aria-label="Passos recentes" data-muted={muted ? 'true' : 'false'}>
    <ol className="shell-chat-ticker-list">
      {items.map((item, index) => {
        const Icon = TICKER_ICONS[item.kind] || Wrench;
        const time = tickerTime(item.at);
        return <li key={item.id || item.keys?.[0] || index} data-kind={item.kind || 'tool'}>
          <span className="shell-chat-ticker-icon" aria-hidden="true"><Icon size={13} /></span>
          <span className="shell-chat-ticker-step" title={item.step}>{item.step}</span>
          {item.detail && <span className="shell-chat-ticker-detail" title={item.detail}>{item.detail}</span>}
          {time && <time className="shell-chat-ticker-time"
            dateTime={typeof item.at === 'string' ? item.at : undefined}>{time}</time>}
        </li>;
      })}
    </ol>
  </section>;
}

/** Pill compacta para tool, aprovação, recibo, incerteza, erro ou conclusão. */
export function ChatEventPill({ kind = 'tool', label, detail }) {
  if (!label) return null;
  const safeKind = PILL_KINDS.has(kind) ? kind : 'tool';
  const Icon = TICKER_ICONS[safeKind] || Wrench;
  const title = [label, detail].filter(Boolean).join(' · ');
  return <span className="shell-chat-event-pill" data-kind={safeKind} title={title}
    aria-label={title} role="note">
    <Icon size={13} aria-hidden="true" />
    <span className="shell-chat-event-pill-label">{label}</span>
    {detail && <span className="shell-chat-event-pill-detail">{detail}</span>}
  </span>;
}

/** Indicador de pensamento com o mascote e três pontos. */
export function ChatThinking({ dot, label = 'Aguardando resposta' }) {
  return <span className="shell-chat-thinking">
    <DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id}
      name={dot?.name} status={dot?.status} execution={dot?.execution} size="message" decorative />
    <span className="shell-thinking-label">{label}</span>
    <span className="shell-chat-thinking-dots" aria-hidden="true"><i /><i /><i /></span>
  </span>;
}

export {
  CHAT_PRESENCE_STATES, PILL_KINDS, chatEventPillFor, chatPresenceModel, deriveChatTicker,
  hasCompletionEvidence,
};
