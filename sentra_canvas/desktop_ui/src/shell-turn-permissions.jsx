import React, { useEffect, useRef, useState } from 'react';
import { OperationReceipt, Status } from './shell-receipts';

const names = new Set(['model:invoke', 'web:send', 'web:attach',
  ...['dot_create', 'team_create', 'connect', 'delegate', 'handoff', 'pause', 'resume', 'cancel', 'reassign', 'pause_dot', 'resume_dot'].map(name => 'canvas.coordinator.' + name)]);

// Explicit owner clicks request Grants for one server-resolved assignee/WI.
// The browser supplies capability names, never principal/owner/Grant IDs.
export function ShellTurnPermissions({ bridge, scope }) {
  const [inventory, setInventory] = useState(null), [workItemId, setWorkItemId] = useState('');
  const [selected, setSelected] = useState([]), [ttl, setTtl] = useState(900);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [pending, setPending] = useState(null), [result, setResult] = useState(null);
  const alive = useRef(true), lock = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function refresh() {
    const value = await bridge({ ...scope, action: 'turn_permission_list', ...(workItemId ? { work_item_id: workItemId } : {}) });
    if (alive.current) setInventory(value);
    return value;
  }
  useEffect(() => { void refresh().catch(e => { if (alive.current) setError(e.message); }); }, [scope.project_id, scope.space_id, scope.conversation_id, bridge]);
  const items = inventory?.items || inventory?.work_items || (inventory?.work_item_id ? [{ ...inventory,
    state: inventory.work_item_state,
    required_capabilities: (inventory.capabilities || []).map(row => row.capability),
    grants: inventory.capabilities || [] }] : []);
  const item = items.find(row => row.work_item_id === workItemId);
  const required = item?.required_capabilities || [];
  const allowed = (inventory?.capabilities || inventory?.allowed_capabilities || [])
    .map(row => typeof row === 'string' ? row : row.capability).filter(cap => names.has(cap));
  const grants = item?.grants || [];
  const available = [...new Set([...required, ...grants.map(row => row.capability)])].filter(cap => typeof cap === 'string');
  async function change(action) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    const payload = pending || { ...scope, action, work_item_id: workItemId, capabilities: selected,
      ...(action === 'turn_permission_grant' ? { ttl_seconds: Number(ttl) } : {}), request_key: crypto.randomUUID() };
    setPending(payload);
    try {
      const value = await bridge(payload);
      if (!alive.current) return;
      setResult(value);
      if (['RUNNING', 'PENDING', 'UNCERTAIN'].includes(value.state) || value.status === 'uncertain') return;
      setPending(null); setSelected([]); await refresh();
    } catch (e) { if (alive.current) { setError(e.message); if (!e.uncertain) setPending(null); } }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  return <section className="shell-turn-permissions" aria-label="Permissões do turno">
    <div className="shell-section-heading"><h3>Permissões deste trabalho</h3><button disabled={busy} onClick={() => refresh().catch(e => setError(e.message))}>Consultar</button></div>
    <p>A concessão vale para o WorkItem selecionado. Ela não envia mensagens, retoma turnos nem repete ferramentas.</p>
    <label>WorkItem da conversa<select value={workItemId} disabled={busy || Boolean(pending)} onChange={e => { setWorkItemId(e.target.value); setSelected([]); setResult(null); }}>
      <option value="">Selecione o trabalho</option>{items.map(row => <option key={row.work_item_id} value={row.work_item_id}>{row.objective || row.work_item_id}</option>)}</select></label>
    {inventory && !items.length && <p className="shell-notice">Nenhum WorkItem elegível foi anunciado nesta conversa.</p>}
    {item && <><Status value={item.state} /><small>Agente resolvido pelo servidor: {item.agent_id || item.assignee_agent_id || 'não projetado'}</small>
      <fieldset disabled={busy || Boolean(pending)}><legend>Capacidades declaradas</legend>{available.map(cap => <label className="shell-check" key={cap}>
        <input type="checkbox" disabled={!allowed.includes(cap)} checked={selected.includes(cap)} onChange={e => setSelected(old => e.target.checked ? [...old, cap] : old.filter(name => name !== cap))} />
        <span>{cap}{!allowed.includes(cap) && ' · fora deste fluxo de concessão'}
          {grants.find(row => row.capability === cap)?.has_turn_grant ? ' · Grant deste WorkItem observado' : ' · sem Grant deste WorkItem'}
          {grants.find(row => row.capability === cap)?.allowed === false && ' · política ainda nega a execução'}</span></label>)}</fieldset>
      {!available.length && <p className="shell-notice">O servidor não declarou capabilities concedíveis para este WorkItem.</p>}
      <details><summary>Grants e pendências observados</summary><pre>{JSON.stringify({ required_capabilities: required, grants, missing_capabilities: item.missing_capabilities }, null, 2)}</pre></details>
      <label>Validade da concessão<select value={ttl} disabled={busy || Boolean(pending)} onChange={e => setTtl(Number(e.target.value))}>
        <option value={60}>1 minuto</option><option value={300}>5 minutos</option><option value={900}>15 minutos</option><option value={3600}>1 hora</option></select></label>
      <div className="shell-code-actions"><button disabled={busy || Boolean(pending) || !selected.length} onClick={() => change('turn_permission_grant')}>Conceder selecionadas só a este WorkItem</button>
        <button disabled={busy || Boolean(pending) || !selected.length} onClick={() => change('turn_permission_revoke')}>Revogar selecionadas neste WorkItem</button></div>
    </>}
    {pending && <div className="shell-notice">Resposta pendente · {pending.request_key}<button disabled={busy} onClick={() => change(pending.action)}>Consultar mesma intenção</button></div>}
    {result?.permission_change_recorded && <p role="status">Alteração de permissões registrada. O turno mantém seu estado; consulte o trabalho.</p>}
    {result?.permission_operation_id && <OperationReceipt value={{ operation_id: result.permission_operation_id,
      work_item_id: result.permission_work_item_id, state: result.permission_operation_state,
      receipt_id: result.receipt_id }} />}{error && <p className="shell-error" role="alert">{error}</p>}
  </section>;
}
