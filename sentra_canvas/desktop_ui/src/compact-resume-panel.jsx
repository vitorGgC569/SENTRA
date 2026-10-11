import React, { useRef, useState } from 'react';
import { api } from './api';

export function CompactResumePanel({ ws }) {
  const [fields, setFields] = useState({ chat_id: '', work_item_id: '', principal_id: '', request_key: '', summary: '', target_url: '' });
  const [reviewed, setReviewed] = useState(false), [busy, setBusy] = useState(false);
  const [kind, setKind] = useState('allocation_id'), [identity, setIdentity] = useState('');
  const [result, setResult] = useState(null), [error, setError] = useState('');
  const pending = useRef(false), uncertainPrepare = useRef(false);
  const update = (key, value) => { setFields(previous => ({ ...previous, [key]: value })); setReviewed(false); };
  const resumeAllowed = result?.account_identity_attested === true && result?.collector_message_attested === true
    && (result?.receipt_exact === true || result?.target_receipt_exact === true);
  async function execute(action) {
    if (pending.current) return;
    if (action === 'prepare' && (!reviewed || uncertainPrepare.current)) return;
    if (action === 'resume' && !resumeAllowed) return;
    pending.current = true; setBusy(true); setError('');
    const arguments_ = action === 'prepare' ? {
      chat_id: fields.chat_id.trim(), work_item_id: fields.work_item_id.trim(), principal_id: fields.principal_id.trim(),
      request_key: fields.request_key.trim(), summary: fields.summary,
      ...(fields.target_url.trim() ? { target_url: fields.target_url.trim() } : {}),
    } : { [kind]: identity.trim() };
    try {
      const snapshot = await api('/api/center/compact-resume', { ws, action, arguments: arguments_ });
      setResult(snapshot);
      if (snapshot.allocation_id || snapshot.continuation_id) {
        setKind(snapshot.allocation_id ? 'allocation_id' : 'continuation_id');
        setIdentity(snapshot.allocation_id || snapshot.continuation_id);
      }
    } catch (failure) {
      setError(failure.message);
      // Lost mutation ACK is not permission to repeat prepare. Existing IDs can still be inspected.
      if (action === 'prepare' && !failure.status) uncertainPrepare.current = true;
    } finally { pending.current = false; setBusy(false); }
  }
  return <section aria-label="Compactar e retomar" aria-busy={busy}>
    <h3>Compact&Resume</h3>
    <p>Use o chat, WorkItem e agente já vinculados a este workspace. Revise o resumo antes de preparar o sucessor.</p>
    <form onSubmit={event => { event.preventDefault(); execute('prepare'); }}>
      <fieldset disabled={busy}><legend>Bindings existentes e resumo revisado</legend>
        <label>Chat ID existente <input required value={fields.chat_id} onChange={event => update('chat_id', event.target.value)} /></label>
        <label>WorkItem ID existente <input required value={fields.work_item_id} onChange={event => update('work_item_id', event.target.value)} /></label>
        <label>Agente / principal existente <input required value={fields.principal_id} onChange={event => update('principal_id', event.target.value)} /></label>
        <label>Chave estável deste pedido <input required maxLength={128} value={fields.request_key} onChange={event => update('request_key', event.target.value)} /></label>
        <label>Resumo para o sucessor <textarea required maxLength={16000} value={fields.summary} onChange={event => update('summary', event.target.value)} /></label>
        <label>URL de destino (opcional) <input type="url" value={fields.target_url} onChange={event => update('target_url', event.target.value)} /></label>
        <details><summary>Inspecionar o resumo antes de preparar</summary><pre>{fields.summary || 'Resumo não informado.'}</pre></details>
        <label><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)} />Revisei o resumo e os bindings existentes</label>
        <button disabled={!reviewed || !fields.summary.trim() || uncertainPrepare.current}>Preparar Compact&Resume</button>
      </fieldset>
    </form>
    <fieldset disabled={busy}><legend>Inspecionar transferência existente</legend>
      <label>Tipo do identificador <select value={kind} onChange={event => { setKind(event.target.value); setResult(null); }}>
        <option value="allocation_id">Allocation ID</option><option value="continuation_id">Continuation ID</option>
      </select></label>
      <label>Identificador existente <input value={identity} onChange={event => { setIdentity(event.target.value); setResult(null); }} /></label>
      <button type="button" disabled={!identity.trim()} onClick={() => execute('status')}>Consultar Compact&Resume</button>
      <button type="button" disabled={!identity.trim() || !resumeAllowed} onClick={() => execute('resume')}>Retomar sucessor confirmado</button>
    </fieldset>
    {error && <p role="alert">{error}</p>}
    {uncertainPrepare.current && <p role="status">Preparação não confirmada. Consulte o journal por um ID existente antes de qualquer novo pedido.</p>}
    {result && <div role="status">
      <strong>{result.state || result.stage || 'Estado indisponível'}</strong>
      <p>{result.successor_ready === true && result.account_identity_attested === true && result.collector_message_attested === true
        ? 'Sucessor confirmado pela autoridade central.' : 'Sucessor não confirmado.'}</p>
      {result.reason && <p>{result.reason}</p>}
      {['checkpoint_id', 'allocation_id', 'continuation_id'].map(key => result[key] && <p key={key}>{key}: <code>{result[key]}</code></p>)}
    </div>}
  </section>;
}
