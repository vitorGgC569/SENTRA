import React, { useEffect, useRef, useState } from 'react';

export function ShellInteractions({ bridge, projectId, visible }) {
  const [items, setItems] = useState([]), [error, setError] = useState(''), [lastReply, setLastReply] = useState(null);
  const alive = useRef(true), fetching = useRef(false);
  const retained = useRef(new Set());
  const bridgeRef = useRef(bridge); bridgeRef.current = bridge;
  useEffect(() => {
    alive.current = true;
    const read = async () => {
      if (!visible || document.hidden || fetching.current || !projectId) return;
      fetching.current = true;
      try { const value = await bridgeRef.current({ project_id: projectId, action: 'interaction_list', limit: 100 });
        if (alive.current) { const incoming = Array.isArray(value) ? value : value.items || [];
          setItems(old => [...incoming, ...old.filter(row => retained.current.has(row.interaction_id) && !incoming.some(v => v.interaction_id === row.interaction_id))]); setError(''); }
      } catch (e) { if (alive.current) setError(e.message); }
      finally { fetching.current = false; }
    };
    void read(); const timer = setInterval(read, 4000);
    return () => { alive.current = false; clearInterval(timer); };
  }, [projectId, visible]);
  return <section className="shell-interactions" aria-label="Solicitações de entrada">
    <h3>Solicitações de entrada</h3>
    {!items.length && <p>Nenhuma solicitação pendente anunciada.</p>}
    {items.map(item => <Interaction key={item.interaction_id} item={item} bridge={bridge} projectId={projectId}
      onPending={pending => { if (pending) retained.current.add(item.interaction_id); else retained.current.delete(item.interaction_id); }} onAnswered={value => {
      setLastReply(value); setItems(old => old.filter(row => row.interaction_id !== value.interaction_id));
    }} />)}
    {lastReply && <p role="status">Resposta registrada para {lastReply.interaction_id}. Nenhum Grant foi concedido por esta resposta.</p>}
    {error && <p className="shell-error" role="alert">{error}</p>}
  </section>;
}

function Interaction({ item, bridge, projectId, onAnswered, onPending }) {
  const [values, setValues] = useState({}), [raw, setRaw] = useState('{}');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [pending, setPending] = useState(null);
  const [now, setNow] = useState(Date.now());
  const lock = useRef(false);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const question = item.question || {}, schema = question.requestedSchema;
  const properties = schema?.properties || {};
  const flat = schema?.type === 'object' && Object.keys(properties).length <= 32 &&
    Object.values(properties).every(value => value && ['string', 'number', 'integer', 'boolean'].includes(value.type));
  const expired = now >= item.expires_at * 1000;
  function field(name, definition) {
    const required = schema.required?.includes(name), current = values[name];
    const change = value => setValues(old => ({ ...old, [name]: value }));
    const label = definition.title || name;
    if (definition.enum) return <label key={name}>{label}<select value={current === undefined ? '' : String(definition.enum.indexOf(current))} required={required} onChange={e => {
      const index = e.target.value; change(index === '' ? undefined : definition.enum[Number(index)]);
    }}><option value="">Selecione</option>{definition.enum.map((value, index) => <option key={index} value={index}>{String(value)}</option>)}</select></label>;
    if (definition.type === 'boolean') return <label key={name}>{label}<select value={current === undefined ? '' : String(current)} required={required}
      onChange={e => change(e.target.value === '' ? undefined : e.target.value === 'true')}><option value="">Selecione</option><option value="true">Sim</option><option value="false">Não</option></select></label>;
    return <label key={name}>{label}<input type={definition.type === 'string' ? (definition.format === 'password' ? 'password' : 'text') : 'number'}
      step={definition.type === 'integer' ? 1 : 'any'} required={required} value={current ?? ''} maxLength={definition.maxLength || 8000}
      min={definition.minimum} max={definition.maximum} onChange={e => change(e.target.value === '' ? undefined : definition.type === 'string' ? e.target.value : Number(e.target.value))} />
      {definition.description && <small>{definition.description}</small>}</label>;
  }
  async function answer(value) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    const payload = pending || { project_id: projectId, action: 'interaction_reply', interaction_id: item.interaction_id,
      answer: value, request_key: crypto.randomUUID() };
    setPending(payload);
    onPending(true);
    try { const result = await bridge(payload);
      if (result.status !== 'answered') { setError('Resposta ainda não confirmada. Consulte a mesma intenção.'); return; }
      setPending(null); onPending(false); onAnswered(result);
    } catch (e) { setError(e.message); if (!e.uncertain) { setPending(null); onPending(false); } }
    finally { lock.current = false; setBusy(false); }
  }
  return <article><strong>{item.method === 'elicitation/create' ? 'Formulário MCP' : 'Permissão de uma chamada ACP'}</strong>
    <p>{question.message || question.toolCall?.title || 'O provider solicita uma decisão explícita.'}</p>
    <small>Operação {item.operation_id} · prazo {new Date(item.expires_at * 1000).toLocaleString('pt-BR')}</small>
    {expired && <p role="status">Prazo encerrado. O servidor decide a validade; nenhuma resposta será enviada automaticamente.</p>}
    {item.method === 'elicitation/create' ? <form onSubmit={e => {
      e.preventDefault(); try { void answer({ action: 'accept', content: flat ? values : JSON.parse(raw) }); } catch { setError('Informe JSON válido para o schema solicitado.'); }
    }}><fieldset disabled={busy || expired || Boolean(pending)}>
      {flat ? Object.entries(properties).map(([name, definition]) => field(name, definition)) : <>
        <details><summary>Schema solicitado</summary><pre>{JSON.stringify(schema, null, 2)}</pre></details>
        <label>Conteúdo JSON<textarea value={raw} maxLength={30000} onChange={e => setRaw(e.target.value)} /></label></>}
      <button type="submit">Enviar estes valores</button><button type="button" onClick={() => answer({ action: 'decline' })}>Recusar formulário</button>
      <button type="button" onClick={() => answer({ action: 'cancel' })}>Cancelar solicitação</button>
    </fieldset></form> : <fieldset disabled={busy || expired || Boolean(pending)}>
      {(question.options || []).filter(option => ['allow_once', 'reject_once'].includes(option.kind)).map(option => <button key={option.optionId}
        onClick={() => answer({ outcome: { outcome: 'selected', optionId: option.optionId } })}>{option.name || (option.kind === 'allow_once' ? 'Permitir esta chamada' : 'Recusar esta chamada')}</button>)}
      <button onClick={() => answer({ outcome: { outcome: 'cancelled' } })}>Cancelar solicitação</button>
    </fieldset>}
    {pending && <p className="shell-notice">Resposta preservada · {pending.request_key}<button disabled={busy} onClick={() => answer(pending.answer)}>Consultar mesma resposta</button></p>}
    {error && <p className="shell-error" role="alert">{error}</p>}
  </article>;
}
