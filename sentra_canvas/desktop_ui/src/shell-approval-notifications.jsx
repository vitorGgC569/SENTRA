import React, { useEffect, useRef, useState } from 'react';
import { BellRing, ShieldAlert } from 'lucide-react';
import { canvasMaintenanceActive } from './shell-maintenance.js';

// Owner-visible persisted requests. Neither polling nor mounting grants access.
export function ShellApprovalNotifications({ bridge, projectId, onOpenConversation, shellError = '' }) {
  const [items, setItems] = useState([]), [busy, setBusy] = useState(''), [error, setError] = useState('');
  const pendingKeys = useRef(new Map());
  const alive = useRef(true);
  async function refresh() {
    if (!projectId) return;
    const result = await bridge({ action:'coordinator_approval_list', project_id:projectId, limit:30 });
    if (alive.current) setItems(result.items || []);
  }
  useEffect(() => {
    alive.current = true;
    let loading = false;
    async function poll() {
      if (!projectId || document.hidden || loading) return;
      loading = true;
      try { await refresh(); if (alive.current) setError(''); }
      catch (e) {
        if (alive.current) setError(e.reauthorizing === true || e.maintenance === true || canvasMaintenanceActive() ? '' : e.message);
      }
      finally { loading = false; }
    }
    void poll();
    const interval = setInterval(poll, 3000);
    window.addEventListener('focus', poll);
    return () => { alive.current = false; clearInterval(interval); window.removeEventListener('focus', poll); };
  }, [projectId]);
  async function decide(item, answer) {
    if (busy) return;
    const token = item.approval_id + ':' + answer;
    let request = pendingKeys.current.get(token);
    if (!request) {
      request = { action:'coordinator_approval_reply', project_id:projectId,
        approval_id:item.approval_id, answer, request_key:crypto.randomUUID() };
      pendingKeys.current.set(token, request);
    }
    setBusy(item.approval_id); setError('');
    try {
      const result = await bridge(request);
      if (result.state === 'uncertain') {
        setError('A decisão ainda não foi confirmada; consulte a mesma solicitação.');
        return;
      }
      if (result.state === 'expired') {
        setError('Este turno terminou. Não é possível autorizar sua execução anterior. Rejeite/dispense este aviso ou solicite uma nova ação.');
        return;
      }
      pendingKeys.current.delete(token);
      await refresh();
    } catch (e) { setError(e.message); if (!e.uncertain) pendingKeys.current.delete(token); }
    finally { if (alive.current) setBusy(''); }
  }
  if (!items.length && !error) return null;
  return <aside className="shell-approval-popup" aria-label="Aprovações pendentes do SENTRA" role="region" aria-live="polite">
    <header><BellRing size={17}/><strong>Solicitações de aprovação</strong><span>{items.length || ''}</span></header>
    {items.map(item => <article key={item.approval_id}>
      <div className="shell-approval-popup-title"><ShieldAlert size={16}/><strong>{item.summary?.name || item.summary?.kind || 'Ação do Dot'}</strong></div>
      <p>O Dot solicitou <code>{item.capability}</code>. Acesso completo ao computador não autoriza automaticamente coordenação.</p>
      <small>Solicitação: {item.approval_id}</small>
      {item.activity !== 'active' && <p className="shell-approval-expired">O turno original terminou. Nenhuma execução será repetida; peça ao Dot para tentar novamente se necessário.</p>}
      <div className="shell-approval-popup-actions">
        <button disabled={Boolean(busy) || item.activity !== 'active'} onClick={() => decide(item, 'approve')}>Autorizar somente este turno</button>
        <button disabled={Boolean(busy)} onClick={() => decide(item, 'reject')}>{item.activity === 'active' ? 'Rejeitar' : 'Dispensar aviso'}</button>
        <button disabled={Boolean(busy)} onClick={() => onOpenConversation?.(item.conversation_id, item.space_id)}>Ver conversa</button>
      </div>
    </article>)}
    {error && error !== shellError && <p className="shell-error" role="alert">{error}</p>}
  </aside>;
}
