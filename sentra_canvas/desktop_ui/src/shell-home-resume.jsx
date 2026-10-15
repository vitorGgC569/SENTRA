import React, { useMemo } from 'react';
import { ArrowRight, MessageCircle, CircleAlert } from 'lucide-react';
import { resumableWorkSurface } from './shell-navigation.js';
import { conversationInstant } from './shell-dates.js';

const ATTENTION = { waiting_approval: 'Aguardando aprovação', needs_input: 'Precisa da sua resposta',
  uncertain: 'Envio não confirmado', unconfirmed: 'Envio não confirmado', interrupted: 'Trabalho interrompido', failed: 'Falha registrada', blocked: 'Trabalho bloqueado' };
const VIEWS = { canvas: 'Canvas', documents: 'Documentos', network: 'Equipe', space: 'Space', spaces: 'Spaces', dots: 'Dots', conversations: 'Conversas' };

export function HomeResumePanel({ home, surface, onNavigate, onConversation }) {
  const rows = useMemo(() => (home.conversations || []).filter(row => row.project_id === home.project_id)
    .sort((a, b) => (conversationInstant(b.updated_at) || 0) - (conversationInstant(a.updated_at) || 0)), [home.conversations, home.project_id]);
  const resume = resumableWorkSurface(surface, home);
  const current = resume?.view === 'chat' ? rows.find(row => row.conversation_id === resume.conversation_id) : null;
  const latest = current || (!resume ? rows[0] : null);
  const attention = rows.filter(row => ATTENTION[String(row.status || '').toLowerCase()]);
  if (!resume && !latest && !attention.length) return null;
  const title = latest?.title || VIEWS[resume?.view] || 'Seu trabalho';
  const dot = latest && (home.dots || []).find(item => item.dot_id === latest.dot_id);
  return <section className="shell-home-resume" aria-label="Continuar trabalho" data-resend="false">
    <div className="shell-home-resume-primary"><div><span className="shell-eyebrow">CONTINUAR TRABALHO</span><h2>{title}</h2>
      <p>{dot?.name ? 'Conversa com ' + dot.name : 'Volte ao contexto que você estava usando.'}</p></div>
      <button type="button" className="shell-primary" onClick={() => latest ? onConversation(latest) : onNavigate(resume)}>Continuar <ArrowRight size={16} /></button></div>
    {attention.length > 0 && <details className="shell-home-attention" open><summary><CircleAlert size={16} aria-hidden="true" />Precisa de atenção <span>{attention.length}</span></summary>
      <ul>{attention.slice(0, 3).map(row => <li key={row.conversation_id}><div><strong>{row.title || 'Conversa'}</strong><small>{ATTENTION[String(row.status || '').toLowerCase()]}</small></div>
        <button type="button" onClick={() => onConversation(row)}><MessageCircle size={15} />Consultar</button></li>)}</ul>
      <p>Abra a conversa para consultar o estado e as permissões.</p>
      {attention.length > 3 && <button type="button" onClick={() => onNavigate({ view: 'conversations' })}>Ver todas as conversas</button>}
    </details>}
  </section>;
}
