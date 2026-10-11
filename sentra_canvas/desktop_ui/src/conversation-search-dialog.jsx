import React, { useState } from 'react';
import { api, route } from './api';
import { Modal } from './primitives';

/** Owner-scoped history search; all data remains in the local protected store. */
export function ConversationSearchDialog({ ws, close }) {
  const [query, setQuery] = useState(''), [items, setItems] = useState([]);
  const [summary, setSummary] = useState(''), [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function search() {
    if (!query.trim()) return;
    setBusy(true); setError('');
    try {
      const result = await api(route('/api/center/conversation-search', { ws, q: query }));
      setItems(result.items || []);
      setSummary(result.has_more ? 'Mais resultados disponíveis. Refine a busca.' : `${result.items?.length || 0} resultados`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function exportSession(id) {
    setBusy(true); setError('');
    try {
      const response = await api('/api/center/conversation-export', { ws, conversation_id: id });
      const link = document.createElement('a');
      const url = URL.createObjectURL(new Blob([response.content], { type: 'text/markdown;charset=utf-8' }));
      try {
        link.href = url; link.download = response.filename;
        document.body.appendChild(link); link.click(); link.remove();
      } finally { setTimeout(() => URL.revokeObjectURL(url), 3000); }
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <Modal open onOpenChange={v => { if (!v) close(); }} title="Histórico de conversas"
    description="Pesquisa local no histórico protegido deste workspace.">
    <div style={{ display: 'grid', gap: 12, maxWidth: 520, padding: '5px 2px 15px' }}>
      <form onSubmit={e => { e.preventDefault(); search(); }} style={{ display: 'flex', gap: 8 }}>
        <input aria-label="Palavras no histórico" placeholder="Pesquisar mensagens…" value={query}
          onChange={e => setQuery(e.target.value)} maxLength={200} style={{ flex: 1, minWidth: 0,
            padding: 10, borderRadius: 8, color: 'white', background: '#202024', border: '1px solid #44444b' }}/>
        <button disabled={busy || !query.trim()} type="submit">Buscar</button>
      </form>
      <small style={{ color: '#a4a4ab' }}>{summary || 'Somente as conversas deste usuário e workspace.'}</small>
      <div style={{ display: 'grid', gap: 7, maxHeight: 370, overflowY: 'auto' }}>
        {items.map((entry, index) => <div key={entry.session_id+':'+entry.seq+':'+index}
          style={{ padding: 12, background: '#202024', border: '1px solid #36363b', borderRadius: 9 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <small style={{ color: '#a3a3ad' }}>{entry.role === 'user' ? 'Você' : entry.role === 'assistant' ? 'Agente' : entry.role} · {entry.kind}</small>
            <button disabled={busy} onClick={() => exportSession(entry.session_id)}>Exportar conversa</button>
          </div>
          <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', marginBottom: 0 }}>{entry.excerpt}</p>
        </div>)}
      </div>
      {error && <p role="alert" style={{ color: '#ff9d95' }}>{error}</p>}
    </div>
  </Modal>;
}
