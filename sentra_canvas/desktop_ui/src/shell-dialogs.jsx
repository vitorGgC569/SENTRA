import React, { useRef, useState } from 'react';
import { Field, Modal } from './primitives';
import { OperationReceipt } from './shell-receipts';
import { DOT_MASCOTS, DotMascot, mascotFor } from './shell-mascot';
import { UserRound, SlidersHorizontal, FileText, Check } from 'lucide-react';

export function ShellEntityDialog({ kind, dot, canvasRoot, initialModel, space, projectId, models, bridge, onClose, onCreated }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [name, setName] = useState(dot?.name || ''), [role, setRole] = useState(dot?.role || 'specialist');
  const [model, setModel] = useState(initialModel || dot?.model || ''), [effort, setEffort] = useState(dot?.effort || '');
  const [description, setDescription] = useState('');
  const [instructions, setInstructions] = useState(dot?.instructions || '');
  const [mascot, setMascot] = useState(dot?.mascot || mascotFor(dot?.agent_id || dot?.dot_id));
  const [pending, setPending] = useState(null), key = useRef(crypto.randomUUID());
  const [editorTab, setEditorTab] = useState(kind === 'model' ? 'model' : 'identity');
  const editing = Boolean(dot);
  async function submit(e) {
    e.preventDefault(); if (busy) return;
    setBusy(true); setError('');
    const payload = pending || { action: kind === 'space' ? 'space_create' : editing ? 'dot_update' : 'dot_create',
      project_id: projectId, request_key: key.current, ...(kind !== 'model' ? { name } : {}),
      ...(kind === 'space' ? { description } : { space_id: space.space_id, model, effort: effort || null,
        ...(kind !== 'model' ? { role, instructions, mascot } : {}),
        ...(canvasRoot ? { canvas_root_dot_id: canvasRoot } : {}),
        ...(editing ? { dot_id: dot.dot_id, expected_revision: dot.revision } : {}) }) };
    try {
      const result = await bridge(payload);
      if (result.status === 'uncertain') { setPending(payload); setError('Resultado ainda não confirmado. Consulte a mesma operação.'); return; }
      setPending(null); await onCreated(result); onClose();
    } catch (e) { setError(e.message); if (e.uncertain) setPending(payload); else key.current = crypto.randomUUID(); }
    finally { setBusy(false); }
  }
  const choices = models.map(item => typeof item === 'string' ? { id: item, name: item } :
    { ...item, id: item.id || item.model_id || item.name, name: item.label || item.name || item.id }).filter(item => item.id);
  if (model && !choices.some(item => item.id === model)) choices.unshift({ id: model, name: model + ' (atual)' });
  const selected = choices.find(item => item.id === model);
  return <Modal open onOpenChange={value => { if (!value && !pending) onClose(); }} busy={busy || Boolean(pending)}
    className={'shell-modal' + (kind !== 'space' ? ' shell-dot-editor' : '')} title={kind === 'space' ? 'Novo Space' : kind === 'model' ? 'Modelo de ' + dot?.name : editing ? 'Editar Dot' : canvasRoot ? 'Novo subagente' : 'Novo Dot'}
    description={kind === 'space' ? 'Organize o trabalho no projeto selecionado.' : kind === 'model' ? 'O modelo escolhido será usado nas próximas mensagens deste Dot.' : canvasRoot ? 'Este agente pertence ao canvas do Dot selecionado.' : 'Personalize seu Dot e escolha o modelo.'}>
    {kind !== 'space' && <div className="shell-dot-editor-profile"><DotMascot mascot={mascot} identity={dot?.agent_id} name={name || 'Seu Dot'} size="intro" decorative /><div><strong>{name || 'Seu próximo Dot'}</strong><span>{editing ? 'Do seu jeito, pronto para continuar.' : 'Dê personalidade ao seu novo parceiro.'}</span></div></div>}
    {kind !== 'space' && kind !== 'model' && <div className="shell-dot-editor-tabs" role="tablist" aria-label="Configurações do Dot">{[['identity', 'Identidade', UserRound], ['model', 'Modelo', SlidersHorizontal], ['instructions', 'Instruções', FileText]].map(([id,label,Icon], index, tabs) => <button type="button" key={id} id={'dot-editor-tab-' + id} role="tab" aria-selected={editorTab === id} aria-controls={'dot-editor-panel-' + id} tabIndex={editorTab === id ? 0 : -1} onClick={() => setEditorTab(id)} onKeyDown={event => { const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : null; if (next !== null) { event.preventDefault(); setEditorTab(tabs[next][0]); event.currentTarget.parentElement.children[next].focus(); } }}><Icon size={15} />{label}</button>)}</div>}
    <form className="shell-form" onSubmit={submit} onInvalidCapture={event => { const panel = event.target.closest('[data-editor-tab]'); if (panel && panel.hidden) { event.preventDefault(); const input = event.target; setEditorTab(panel.dataset.editorTab); requestAnimationFrame(() => input.focus()); } }}>
      {kind === 'space' && <Field label="Nome"><input required maxLength={80} value={name} disabled={Boolean(pending)} onChange={e => setName(e.target.value)} autoFocus /></Field>}
      {kind === 'space' ? <Field label="Descrição"><textarea maxLength={4000} value={description} disabled={Boolean(pending)} onChange={e => setDescription(e.target.value)} /></Field> : <>
        {kind !== 'model' && <><section role="tabpanel" id="dot-editor-panel-identity" aria-labelledby="dot-editor-tab-identity" data-editor-tab="identity" hidden={editorTab !== 'identity'}>
        <Field label="Nome"><input required maxLength={80} value={name} disabled={Boolean(pending)} onChange={e => setName(e.target.value)} autoFocus /></Field>
        <fieldset className="shell-mascot-picker" disabled={Boolean(pending)}><legend>Escolha seu Dot</legend><div>{DOT_MASCOTS.map(item => <button type="button" key={item.id} aria-label={'Dot ' + item.label} aria-pressed={mascot === item.id} onClick={() => setMascot(item.id)}><img src={item.image} alt="" width="60" height="60" /><span>{item.label}</span>{mascot === item.id && <Check size={12} className="shell-mascot-check" />}</button>)}</div></fieldset>
        <Field label="Papel"><input required maxLength={80} value={role} disabled={Boolean(pending)} onChange={e => setRole(e.target.value)} /></Field>
        </section><section role="tabpanel" id="dot-editor-panel-instructions" aria-labelledby="dot-editor-tab-instructions" data-editor-tab="instructions" hidden={editorTab !== 'instructions'}><Field label="Como este Dot deve trabalhar?"><textarea maxLength={16000} value={instructions} placeholder="Descreva seu estilo, especialidade e o que ele deve considerar…" disabled={Boolean(pending)} onChange={e => setInstructions(e.target.value)} /></Field><p className="shell-dot-editor-hint">Estas instruções orientam as próximas conversas.</p></section></>}
        <section role={kind === 'model' ? undefined : 'tabpanel'} id="dot-editor-panel-model" aria-labelledby={kind === 'model' ? undefined : 'dot-editor-tab-model'} data-editor-tab="model" hidden={editorTab !== 'model'}>
        <Field label="Modelo disponível"><select required value={model} disabled={Boolean(pending)} onChange={e => { setModel(e.target.value); setEffort(''); }} autoFocus={kind === 'model'}>
          <option value="">Selecione um modelo</option>{choices.map(item => <option key={item.id} value={item.id} disabled={item.available === false}>{item.name}</option>)}</select></Field>
          {!choices.length && <p className="shell-notice">O runtime ainda não anunciou modelos disponíveis. Configure a conta em Ambientes e modelos.</p>}
          <Field label="Esforço"><select value={effort} disabled={Boolean(pending)} onChange={e => setEffort(e.target.value)}><option value="">Padrão autorizado</option>
            {(selected?.efforts || selected?.reasoning_efforts || ['low', 'medium', 'high', 'xhigh', 'max', 'ultra']).map(value => <option key={typeof value === 'string' ? value : value.id} value={typeof value === 'string' ? value : value.id}>{typeof value === 'string' ? value : value.label || value.id}</option>)}</select></Field>
        </section>
      </>}
      {error && <p className="shell-error" role="alert">{error}</p>}
      {pending && <p className="shell-notice">Resposta não confirmada. A consulta mantém a mesma chave e os mesmos campos.</p>}
      <footer><button type="button" disabled={busy || Boolean(pending)} onClick={onClose}>Cancelar</button>
        <button className="shell-primary" disabled={busy || (!editing && kind !== 'space' && !model)}>{busy ? 'Consultando…' : pending ? 'Consultar criação' : editing ? 'Salvar alterações' : 'Criar'}</button></footer>
    </form>
  </Modal>;
}

export function ShellCoordinateDialog({ space, conversation, dots, teams = [], bridge, onClose, onChanged, initialKind = 'create_team' }) {
  const [kind, setKind] = useState(initialKind), [name, setName] = useState('');
  const [coordinator, setCoordinator] = useState(''), [workers, setWorkers] = useState([]);
  const [dotId, setDotId] = useState(conversation?.dot_id || ''), [target, setTarget] = useState('');
  const [teamId, setTeamId] = useState(''), [objective, setObjective] = useState(''), [workItem, setWorkItem] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [result, setResult] = useState(null), [pending, setPending] = useState(null);
  const key = useRef(crypto.randomUUID());
  function dotSelect(value, setValue, label) {
    return <Field label={label}><select value={value} required onChange={e => setValue(e.target.value)} disabled={Boolean(pending)}><option value="">Selecione</option>
      {dots.map(dot => <option key={dot.dot_id} value={dot.dot_id}>{dot.name}</option>)}</select></Field>;
  }
  async function submit(e) {
    e.preventDefault(); if (busy) return;
    let intent;
        if (kind === 'create_team') intent = { kind, name, coordinator_dot_id: coordinator, worker_dot_ids: workers.filter(id => id !== coordinator) };
    else if (kind === 'delegate') intent = { kind, team_id: teamId, dot_id: dotId, objective };
    else if (kind === 'connect') intent = { kind, source_dot_id: dotId, target_dot_id: target };
    else if (kind === 'handoff') intent = { kind, source_dot_id: dotId, target_dot_id: target, content: objective };
    else if (kind === 'reassign') intent = { kind, work_item_id: workItem, dot_id: dotId };
    else intent = { kind };
    const payload = pending || { action: 'coordinate', project_id: space.project_id, space_id: space.space_id,
      ...(conversation ? { conversation_id: conversation.conversation_id } : {}), intent, request_key: key.current };
    setBusy(true); setError('');
    try { const value = await bridge(payload); setResult(value); setPending(null); key.current = crypto.randomUUID(); await onChanged(); }
    catch (e) { setError(e.message); if (e.uncertain) setPending(payload); else key.current = crypto.randomUUID(); }
    finally { setBusy(false); }
  }
  return <Modal open onOpenChange={value => { if (!value) onClose(); }} busy={busy || Boolean(pending)} className="shell-modal"
    title="Coordenar o trabalho" description="Selecione uma intenção e seus alvos. Aprovações necessárias permanecem pendentes no Control Plane.">
    <form className="shell-form" onSubmit={submit}><Field label="Ação"><select value={kind} disabled={Boolean(pending)} onChange={e => { setKind(e.target.value); setResult(null); }}>
      <option value="create_team">Criar equipe</option><option value="delegate">Delegar objetivo</option><option value="connect">Relacionar Dots</option>
      <option value="handoff">Encaminhar contexto entre Dots</option>
      <option value="pause">Pausar projeto</option><option value="resume">Retomar projeto</option><option value="cancel">Cancelar trabalho do projeto</option><option value="reassign">Reatribuir WorkItem</option></select></Field>
      {kind === 'create_team' ? <><Field label="Nome da equipe"><input required maxLength={120} value={name} disabled={Boolean(pending)} onChange={e => setName(e.target.value)} /></Field>
        {dotSelect(coordinator, setCoordinator, 'Coordenador')}<fieldset disabled={Boolean(pending)}><legend>Trabalhadores</legend>
          {dots.filter(dot => dot.dot_id !== coordinator).map(dot => <label className="shell-check" key={dot.dot_id}><input type="checkbox" checked={workers.includes(dot.dot_id)} onChange={e => setWorkers(old => e.target.checked ? [...old, dot.dot_id] : old.filter(id => id !== dot.dot_id))} />{dot.name}</label>)}</fieldset></>
        : <>{!['pause', 'resume', 'cancel'].includes(kind) && dotSelect(dotId, setDotId, kind === 'connect' ? 'Dot de origem' : 'Dot responsável')}
          {['connect', 'handoff'].includes(kind) && dotSelect(target, setTarget, 'Dot de destino')}
          {kind === 'handoff' && <Field label="Contexto a encaminhar"><textarea required value={objective} maxLength={100000} disabled={Boolean(pending)} onChange={e => setObjective(e.target.value)} /></Field>}
          {kind === 'delegate' && <><Field label="Equipe"><select required value={teamId} disabled={Boolean(pending)} onChange={e => setTeamId(e.target.value)}><option value="">Selecione</option>{teams.map(team => <option key={team.team_id || team.id} value={team.team_id || team.id}>{team.name}</option>)}</select></Field>
            <Field label="Objetivo"><textarea required value={objective} maxLength={100000} disabled={Boolean(pending)} onChange={e => setObjective(e.target.value)} /></Field></>}
          {kind === 'reassign' && <Field label="WorkItem"><input required value={workItem} disabled={Boolean(pending)} onChange={e => setWorkItem(e.target.value)} /></Field>}</>}
      {error && <p role="alert" className="shell-error">{error}</p>}{result && <OperationReceipt value={result} />}
      {pending && <p className="shell-notice">Resultado incerto; consultar mantém a chave original.</p>}
      <footer><button type="button" disabled={busy || Boolean(pending)} onClick={onClose}>Fechar</button><button className="shell-primary" disabled={busy || (kind === 'create_team' && !workers.filter(id => id !== coordinator).length)}>{busy ? 'Consultando…' : pending ? 'Consultar operação' : 'Submeter intenção'}</button></footer>
    </form>
  </Modal>;
}
