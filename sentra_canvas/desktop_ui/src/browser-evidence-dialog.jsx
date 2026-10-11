import React, { useEffect, useState } from 'react';
import { api, route } from './api';
import { Modal } from './primitives';

export function BrowserEvidenceDialog({ ws, close }) {
  const [collectors, setCollectors] = useState([]), [error, setError] = useState('');
  const [extension, setExtension] = useState(''), [principal, setPrincipal] = useState('local-operator');
  const [sha, setSha] = useState(''), [busy, setBusy] = useState(false);
  async function refresh() { const result = await api(route('/api/center/browser-evidence', { ws })); setCollectors(result.collectors); }
  useEffect(() => { refresh().catch(e => setError(e.message)); }, [ws]);
  async function configure(configuration) {
    setBusy(true); setError('');
    try { await api('/api/center/browser-evidence', { ws, approve: true, configuration }); await refresh(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  function enroll(event) {
    event.preventDefault();
    const existing = collectors.find(c => c.extension_id === extension);
    configure({ extension_id: extension, principal, source_sha256: sha,
      enabled: true, expected_revision: existing?.revision || 0 });
  }
  return <Modal open onOpenChange={open => { if (!open) close(); }} title="Observação das conversas Web"
    description="Autorize somente a extensão instalada neste perfil. O coletor observa IDs e estados das abas controladas pelo SENTRA.">
    <form onSubmit={enroll} style={{ display: 'grid', gap: 10 }}>
      <label>ID da extensão <input required pattern="[a-p]{32}" value={extension} onChange={e => setExtension(e.target.value)} /></label>
      <label>Principal MCP <input required value={principal} onChange={e => setPrincipal(e.target.value)} /></label>
      <label>SHA-256 da versão instalada <input required pattern="[a-f0-9]{64}" value={sha} onChange={e => setSha(e.target.value)} /></label>
      <small>O ID e a assinatura aparecem nas opções da extensão. Use o principal da sessão MCP que você quer proteger.</small>
      <button disabled={busy}>Autorizar coletor neste workspace</button>
    </form>
    <div style={{ display: 'grid', gap: 10, padding: '16px 0' }}>
      {collectors.map(item => <section key={item.extension_id + ':' + (item.worker || '')}>
        <strong>{item.enabled ? 'Autorizado' : 'Revogado'}</strong> · {item.worker || 'aguardando aba'}
        <p>{item.state === 'awaiting_approval' ? 'WAITING_CHATGPT_USER_APPROVAL — aprove no próprio ChatGPT' : item.state || 'Sem observação'}</p>
        {item.conversation_id && <code>{item.conversation_id}</code>}
        <small style={{ display: 'block' }}>{item.observed ? new Date(item.observed * 1000).toLocaleString() : 'Ainda não observado'}</small>
        <button disabled={busy || !item.enabled} onClick={() => configure({ extension_id: item.extension_id,
          principal: item.principal, source_sha256: item.source_sha256, enabled: false,
          expected_revision: item.revision })}>Revogar coletor</button>
      </section>)}
      <button disabled={busy} onClick={() => refresh().catch(e => setError(e.message))}>Atualizar estado</button>
      {error && <p role="alert">{error}</p>}
    </div>
  </Modal>;
}
