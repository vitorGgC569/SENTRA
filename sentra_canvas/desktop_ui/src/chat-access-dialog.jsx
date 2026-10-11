import React, { useEffect, useState } from 'react';
import { api, route } from './api';
import { Modal } from './primitives';

/** Local-operator controls for exact-chat *denials*. Trust never grants tools. */
export function ChatAccessDialog({ ws, agents, close }) {
  const chats = (agents || []).filter(a => typeof a.conversation_id === 'string' && a.conversation_id.length >= 8);
  const [conversation, setConversation] = useState(chats[0]?.conversation_id || '');
  const [strict, setStrict] = useState(null);
  const [policy, setPolicy] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    setPolicy(null); setError('');
    api(route('/api/center/chat-access', { ws, conversation_id: conversation }))
      .then(value => { if (alive) { setStrict(value.strict_policy); setPolicy(value.chat || null); } })
      .catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [ws, conversation]);
  async function setChat(trusted, blocked) {
    if (!policy || !conversation) return;
    setBusy(true); setError('');
    try {
      const value = await api('/api/center/chat-access', {
        ws, change: { operation: 'chat', conversation_id: conversation,
          trusted, blocked, expected_revision: policy.revision },
      });
      setPolicy(value);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function setMode(enabled) {
    if (!strict) return;
    setBusy(true); setError('');
    try {
      const value = await api('/api/center/chat-access', {
        ws, change: { operation: 'strict', enabled, expected_revision: strict.revision },
      });
      setStrict(value);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <Modal open onOpenChange={value => { if (!value) close(); }}
    title="Acesso das conversas" description="Controle adicional para conversas vinculadas a agentes neste workspace.">
    <div style={{ display: 'grid', gap: 13, padding: '4px 2px 14px', maxWidth: 420 }}>
      <label style={{ fontSize: 12, color: '#b8b8be' }}>Conversa do agente
        <select aria-label="Conversa" value={conversation} onChange={e => setConversation(e.target.value)}
          style={{ display: 'block', marginTop: 7, width: '100%', padding: 9, background: '#202024',
            border: '1px solid #44444b', color: 'white', borderRadius: 8 }}>
          {chats.map(a => <option key={a.id} value={a.conversation_id}>{a.name}</option>)}
        </select>
      </label>
      {!chats.length && <p>Nenhuma conversa de agente vinculada. Crie um agente primeiro.</p>}
      {policy && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button disabled={busy || policy.blocked} onClick={() => setChat(true, false)}>Confiar neste chat</button>
        <button disabled={busy || !policy.blocked} onClick={() => setChat(false, true)}>Bloquear ferramentas</button>
        <button disabled={busy || (!policy.blocked && !policy.trusted)}
          onClick={() => setChat(false, false)}>Limpar política</button>
      </div>}
      <small>{policy ? (policy.blocked ? 'Bloqueio configurado' : policy.trusted ? 'Confiável (ainda requer grants)' : 'Sem confiança explícita') : 'Aguardando…'}</small>
      {policy && !policy.verified_origin_available && <small role="status" style={{ color: '#d7ac85' }}>
        Identidade MCP→chat ainda sem prova. Este bloqueio só atinge requisições cuja origem for comprovada; o modo estrito nega chamadas não atribuídas.
      </small>}
      <hr style={{ border: '0', borderTop: '1px solid #34343a', width: '100%' }} />
      <label style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <input type="checkbox" checked={Boolean(strict?.strict)} disabled={busy || !strict}
          onChange={e => setMode(e.target.checked)} />
        Exigir conversa comprovada e explicitamente confiável
      </label>
      <small style={{ color: '#a5a5ae' }}>O modo estrito nega chamadas sem identidade comprovada. Desativado por padrão. Aprovar um chat não concede acesso à máquina.</small>
      {error && <p role="alert" style={{ color: '#ff9d95' }}>{error}</p>}
    </div>
  </Modal>;
}
