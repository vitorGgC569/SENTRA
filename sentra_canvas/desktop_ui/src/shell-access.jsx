import React, { useEffect, useState } from 'react';
import { Check, ChevronDown, Shield } from 'lucide-react';
import { Modal } from './primitives';

const presets = [
  ['ask', 'Solicitar aprovação', 'Pedir aprovação para editar, executar comandos e acessar arquivos externos.'],
  ['auto', 'Aprovar por mim', 'Editar no projeto; pedir aprovação para exclusões, comandos e acessos externos.'],
  ['full', 'Acesso completo', 'Este Dot pode criar e coordenar subagentes, preparar os acessos do trabalho e executar arquivos e comandos. Vale enquanto este modo estiver ativo.'],
];
const capabilities = [['computer:file.read', 'Ler arquivos'], ['computer:file.write', 'Criar e editar arquivos'], ['computer:file.delete', 'Excluir arquivos'], ['computer:execute', 'Executar comandos']];
export function ShellAccess({ bridge, scope, onCustomize, inlineRequests=false }) {
  const [value, setValue] = useState({ mode: 'ask', requests: [] }), [open, setOpen] = useState(false);
  const [custom, setCustom] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [target, setTarget] = useState('workspace'), [approval, setApproval] = useState('ask');
  const [pending, setPending] = useState(null);
  const [selected, setSelected] = useState(capabilities.map(row => row[0]));
  useEffect(() => {
    let alive = true;
    async function load() { try { const result = await bridge({ ...scope, action: 'access_status' }); if (alive) setValue(result); } catch (e) { if (alive) setError(e.message); } }
    void load(); const timer = setInterval(load, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, [scope.project_id, scope.conversation_id]);
  async function change(action, fields) {
    setBusy(true); setError('');
    const payload = pending || { ...scope, action, ...fields, request_key: crypto.randomUUID() };
    setPending(payload);
    try { const result = await bridge(payload);
      if (result.status === 'uncertain' || ['RUNNING', 'PENDING', 'UNCERTAIN'].includes(result.state)) return;
      setValue(result); setPending(null); setOpen(false); setCustom(false);
    } catch (e) { setError(e.message); if (!e.uncertain) setPending(null); }
    finally { setBusy(false); }
  }
  const name = presets.find(row => row[0] === value.mode)?.[1] || 'Personalizado';
  return <div className="shell-access-control">
    <button type="button" className={'shell-access-trigger ' + (value.mode === 'full' ? 'full' : '')} onClick={() => setOpen(old => !old)} aria-expanded={open} aria-label={'Acesso: ' + name}>
      <Shield size={14} /><span>{name}</span>{value.requests?.length > 0 && <b>{value.requests.length}</b>}<ChevronDown size={12} /></button>
    {open && <div className="shell-access-popover" role="group" aria-label="Como as ações do Dot devem ser aprovadas?">
      <p>Como as ações do Dot devem ser aprovadas?</p>
      {presets.map(([mode, label, description]) => <button key={mode} type="button" disabled={busy || Boolean(pending)} className={mode === 'full' ? 'full' : ''} onClick={() => void change('access_set', { mode })}>
        <Shield size={15} /><span><strong>{label}</strong><small>{description}</small></span>{value.mode === mode && <Check size={15} />}</button>)}
      <button type="button" onClick={() => { setTarget(value.scope || 'workspace'); setApproval(value.approval || 'ask'); setSelected(value.capabilities || capabilities.map(row => row[0])); setCustom(true); setOpen(false); }}>Personalizar…</button>
      <button type="button" onClick={() => { setOpen(false); onCustomize(); }}>Detalhes e trabalhos…</button>
      {!inlineRequests&&value.requests?.map(row => <div className="shell-access-request" key={row.operation_id}><strong>Aprovação necessária</strong><pre>{row.arguments.command || (row.arguments.action + ' · ' + row.arguments.path)}</pre>
        <button type="button" disabled={busy} onClick={() => void change('access_approve', { target_operation_id: row.operation_id })}>Aprovar esta ação</button>
        <button type="button" disabled={busy} onClick={() => void change('access_reject', { target_operation_id: row.operation_id })}>Recusar</button></div>)}
      {pending && <button type="button" disabled={busy} onClick={() => void change(pending.action, pending)}>Consultar alteração pendente</button>}
      {error && <p className="shell-error" role="alert">{error}</p>}
    </div>}
    {custom && <Modal open title="Personalizar acesso" className="shell-modal" onOpenChange={setCustom}><div className="shell-form">
      <label>Alcance<select value={target} onChange={e => setTarget(e.target.value)}><option value="workspace">Projeto e aprovação para acessos externos</option><option value="computer">Computador inteiro</option></select></label>
      <label>Aprovação<select value={approval} onChange={e => setApproval(e.target.value)}><option value="ask">Solicitar para alterações e comandos</option><option value="auto">Aprovar ações conhecidas no projeto</option><option value="never">Autorizar todas as ações</option></select></label>
      <fieldset><legend>Permitir ao Dot</legend>{capabilities.map(([id, label]) => <label className="shell-check" key={id}><input type="checkbox" checked={selected.includes(id)} disabled={busy} onChange={e => setSelected(old => e.target.checked ? [...old, id] : old.filter(cap => cap !== id))} />{label}</label>)}</fieldset>
      <details><summary>WorkItem e máquina desta conversa</summary><pre>{JSON.stringify({ work_item_id: value.work_item_id, machine_id: value.machine_id, scope: value.scope, approval: value.approval }, null, 2)}</pre><button type="button" onClick={() => { setCustom(false); onCustomize(); }}>Gerenciar trabalhos e Grants</button></details>
      <footer><button type="button" disabled={busy} onClick={() => void change('access_set', { mode: 'custom', scope: target, approval, capabilities: selected })}>Aplicar</button></footer>{error && <p role="alert">{error}</p>}
    </div></Modal>}
  </div>;
}
