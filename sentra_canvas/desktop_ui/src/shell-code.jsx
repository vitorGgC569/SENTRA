import React, { useEffect, useRef, useState } from 'react';
import { OperationReceipt, Status } from './shell-receipts';

// Sources/results stay in memory. This surface never configures pins or grants.
export function ShellCode({ bridge, scope, onConfigure, onPendingChange }) {
  const [machines, setMachines] = useState([]), [workItems, setWorkItems] = useState([]);
  const [machineId, setMachineId] = useState(''), [workItemId, setWorkItemId] = useState('');
  const [catalog, setCatalog] = useState(null), [source, setSource] = useState('');
  const [proposalId, setProposalId] = useState(''), [status, setStatus] = useState(null);
  const [receipt, setReceipt] = useState(null), [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const generation = useRef(0), mounted = useRef(true), operationBusy = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; }; }, []);
  useEffect(() => { onPendingChange?.(Boolean(pending) || busy); }, [pending, busy, onPendingChange]);
  useEffect(() => {
    const before = e => { if (pending || source.trim()) { e.preventDefault(); e.returnValue = ''; } };
    addEventListener('beforeunload', before); return () => removeEventListener('beforeunload', before);
  }, [pending, source]);
  async function discover() {
    const token = ++generation.current; setError('');
    try {
      const [value, inventory] = await Promise.all([
        bridge({ ...scope, action: 'code_discovery' }), bridge({ ...scope, action: 'machine_list' })]);
      if (!mounted.current || token !== generation.current) return;
      setMachines(value.items || []); setWorkItems(inventory.work_items || []);
    } catch (e) { if (mounted.current && token === generation.current) setError(e.message); }
  }
  useEffect(() => { void discover(); }, [scope.project_id, scope.space_id, bridge]);
  useEffect(() => {
    let active = true; setCatalog(null); setStatus(null); setReceipt(null); setProposalId(''); setWorkItemId('');
    if (machineId) bridge({ ...scope, action: 'code_discovery', machine_id: machineId })
      .then(value => { if (active) setCatalog(value); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [machineId, scope.project_id, scope.space_id, bridge]);
  async function consult() {
    if (!proposalId || !machineId || busy) return;
    setBusy(true); setError('');
    try { const value = await bridge({ ...scope, action: 'code_status', machine_id: machineId, proposal_id: proposalId });
      if (mounted.current) { setStatus(value); if (value.work_item_id) setWorkItemId(value.work_item_id); }
    } catch (e) { if (mounted.current) setError(e.message); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function mutate(action) {
    if (operationBusy.current) return;
    operationBusy.current = true;
    const payload = pending || { ...scope, action, machine_id: machineId, work_item_id: workItemId,
      ...(action === 'code_propose' ? { source } : { proposal_id: proposalId }), request_key: crypto.randomUUID() };
    setBusy(true); setError('');
    try {
      const value = await bridge(payload);
      if (!mounted.current) return;
      setReceipt(value);
      const uncertain = ['RUNNING', 'PENDING', 'UNCERTAIN', 'RESERVED'].includes(value.state);
      setPending(uncertain ? payload : null);
      if (value.state === 'SUCCEEDED' && value.value?.proposal_id) {
        setProposalId(value.value.proposal_id); setStatus(value.value);
      }
      if (value.state === 'SUCCEEDED' && payload.action === 'code_propose' && !value.value?.proposal_id)
        setError('Receipt concluído sem proposta recuperável. Consulte a operação; não envie outra proposta automaticamente.');
    } catch (e) { if (mounted.current) { setError(e.message); setPending(e.uncertain ? payload : null); } }
    finally { operationBusy.current = false; if (mounted.current) setBusy(false); }
  }
  const availability = catalog?.availability || catalog?.admission;
  const candidates = workItems.filter(item => item.machine_id === machineId);
  const sourceBytes = new TextEncoder().encode(source).length;
  const sourceMax = availability?.limits?.max_source_bytes || 65536;
  const privateValue = receipt?.state === 'SUCCEEDED' ? receipt.value : null;
  return <section className="shell-code" aria-label="Code Mode">
    <div className="shell-section-heading"><h3>Code Mode</h3><button onClick={discover} disabled={busy || Boolean(pending)}>Atualizar</button></div>
    <p>Proponha código para uma máquina configurada. Executar usa o WorkItem e as permissões existentes.</p>
    <label>Máquina<select value={machineId} disabled={busy || Boolean(pending)} onChange={e => { setMachineId(e.target.value); setError(''); }}>
      <option value="">Selecione</option>{machines.map(item => <option key={item.machine_id} value={item.machine_id}>{item.machine_id}</option>)}</select></label>
    {!machines.length && <p className="shell-notice">Nenhuma máquina Code Mode configurada neste projeto.</p>}
    <button type="button" onClick={onConfigure}>Configuração de máquinas</button>
    {machineId && <>
      <p role="status">{availability?.enabled === true ? 'Runtime disponível; nenhuma execução verificada por descoberta.' : availability?.reason || 'Consultando disponibilidade…'}</p>
      <label>WorkItem existente<select value={workItemId} disabled={busy || Boolean(pending) || Boolean(proposalId)} onChange={e => setWorkItemId(e.target.value)}>
        <option value="">Selecione</option>{candidates.map(item => <option key={item.work_item_id} value={item.work_item_id}>{item.objective || item.work_item_id}</option>)}</select></label>
      {!candidates.length && <p className="shell-notice">Nenhum WorkItem vinculado anunciado. Delegue trabalho para esta máquina antes de propor.</p>}
      <details><summary>Tools e limites anunciados</summary><pre>{JSON.stringify({ tools: catalog?.tools || [], limits: availability?.limits || catalog?.signature?.limits_schema }, null, 2)}</pre></details>
      <label>Fonte JavaScript<textarea className="shell-code-source" spellCheck={false} value={source} disabled={busy || Boolean(pending) || Boolean(proposalId)}
        onChange={e => setSource(e.target.value)} aria-describedby="shell-code-source-count" /></label>
      <small id="shell-code-source-count">{sourceBytes} / {sourceMax} bytes · fonte mantida somente nesta janela</small>
      <button disabled={busy || Boolean(pending) || Boolean(proposalId) || !workItemId || !sourceBytes || sourceBytes > sourceMax}
        onClick={() => mutate('code_propose')}>Submeter proposta</button>
      <label>Proposta existente<input value={proposalId} disabled={busy || Boolean(pending)} onChange={e => { setProposalId(e.target.value); setStatus(null); setReceipt(null); }} /></label>
      {proposalId && <div className="shell-code-actions"><button disabled={busy} onClick={consult}>Consultar proposta</button>
        <button disabled={busy || Boolean(pending) || !workItemId || status?.state !== 'PROPOSED' || availability?.enabled !== true}
          onClick={() => mutate('code_execute')}>Executar proposta</button>
        <button disabled={busy || Boolean(pending) || !workItemId || ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(status?.state)}
          onClick={() => mutate('code_cancel')}>Solicitar cancelamento</button></div>}
      {proposalId && ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(status?.state) && <button disabled={busy || Boolean(pending)}
        onClick={() => { setProposalId(''); setStatus(null); setReceipt(null); }}>Preparar nova proposta</button>}
      {pending && <div className="shell-notice"><p>Resposta pendente. A consulta conserva os campos e a chave; execução em andamento não será repetida.</p>
        <button disabled={busy} onClick={() => mutate(pending.action)}>Consultar mesma operação</button></div>}
      {status && <><Status value={status.state} /><p>{status.a08_satisfied === true && status.execution_verified === true ? 'Execução WASM confirmada pelo receipt central.' : 'Execução WASM ainda não verificada.'}</p>
        <details><summary>Estado e execuções</summary><pre>{JSON.stringify(status, null, 2)}</pre></details></>}
      <OperationReceipt value={receipt} />
      {privateValue && <details open><summary>Resultado protegido da operação concluída</summary><pre>{JSON.stringify(privateValue, null, 2)}</pre></details>}
    </>}
    {error && <p className="shell-error" role="alert">{error}</p>}
  </section>;
}
