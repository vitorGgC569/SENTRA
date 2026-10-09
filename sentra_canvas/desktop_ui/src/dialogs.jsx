import React, { useEffect, useRef, useState } from 'react';
import { Modal, Field } from './primitives';
import { useDesktop } from './context';
import { api, route } from './api';

const titles = { workspace: 'Novo workspace', attach: 'Adicionar pasta existente', terminal: 'Novo terminal',
  agent: 'Novo agente', team: 'Nova equipe', note: 'Nova nota', handoff: 'Enviar instrução',
  task: 'Delegar tarefa', rename: 'Renomear terminal', duplicate: 'Duplicar terminal' };
export function EntryDialog({ request, close }) {
  const { bridge, integrations, models, actions, notify } = useDesktop();
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [shell, setShell] = useState(integrations.find(i => i.id === 'sentra-cli' && i.installed)?.id || integrations.find(i => i.installed)?.id || '');
  const [members, setMembers] = useState([]);
  const [team, setTeam] = useState(bridge.current.detail?.teams?.[0]?.id || '');
  const sealed = useRef(null), [frozen, setFrozen] = useState(false), [unknown, setUnknown] = useState(false);
  const form = useRef(null);
  const kind = request.kind;
  const state = bridge.current, detail = state.detail || {};
  const agents = detail.agents || [], teams = detail.teams || [];
  const graph = state.nodes.find(n => n.id === request.target);
  const defaultModel = integrations.some(i => i.id === 'codex' && i.native_model_authenticated === true)
    ? 'sentra/codex/current' : 'sentra/chatgpt-web/auto';
  const destinations = state.links.filter(e => e.source === graph?.id)
    .map(e => state.nodes.find(n => n.id === e.target)).filter(n => {
      if (!n) return false;
      const resource = n.kind === 'terminal' ? detail.terminals?.find(t => t.id === n.resource_id) :
        detail.terminals?.find(t => t.id === agents.find(a => a.id === n.resource_id)?.terminal_id);
      return resource?.status === 'running' && ['sentra-cli', 'codex'].includes(resource.shell);
    });
  useEffect(() => {
    if (kind !== 'task' || !team) return;
    const controller = new AbortController();
    api(route('/api/team', { ws: state.ws, id: team }), undefined, { signal: controller.signal })
      .then(rows => setMembers(rows.filter(r => r.team_role === 'worker')))
      .catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [kind, team, state.ws]);
  async function submit(e) {
    e.preventDefault(); if (busy || unknown) return;
    setBusy(true); setError('');
    const data = new FormData(form.current), value = name => String(data.get(name) || '').trim();
    let path, payload;
    try {
      if (sealed.current) ({ path, payload } = sealed.current);
      else {
        const ws = state.ws;
        if (kind === 'workspace') { path = '/api/workspaces'; payload = { name: value('name') }; }
        else if (kind === 'attach') { path = '/api/workspace/attach'; payload = { name: value('name'), path: value('path') }; }
        else if (kind === 'terminal') {
          path = shell === 'antigravity-app' ? '/api/external/antigravity' : '/api/terminals';
          payload = shell === 'antigravity-app' ? { ws, approved: true } :
            { ws, name: value('name'), shell, ...(shell === 'sentra-cli' ? { model: value('model'), effort: value('effort') } : {}) };
        } else if (kind === 'agent') {
          const goal = String(data.get('goal') || '').trim();
          if (new TextEncoder().encode(goal).length > 16000) throw Error('O objetivo aceita até 16.000 bytes de texto.');
          path = '/api/agents'; payload = { ws, name: value('name'), model: value('model'), role: value('role'), goal, start: data.get('start') === 'on' };
        }
        else if (kind === 'team') {
          const coordinator = value('coordinator');
          const workers = data.getAll('workers').filter(x => x !== coordinator);
          if (!workers.length) throw Error('Selecione um trabalhador diferente do coordenador.');
          path = '/api/teams'; payload = { ws, name: value('name'), coordinator, workers };
        } else if (kind === 'note') { path = '/api/graph/note'; payload = { ws, title: value('title'), body: String(data.get('body') || ''), ...request.point }; }
        else if (kind === 'rename' || kind === 'duplicate') {
          path = '/api/terminal/' + kind; payload = { ws, id: graph.resource_id, name: value('name') };
        } else if (kind === 'handoff') {
          path = '/api/graph/handoff'; payload = { ws, source: graph.id, target: value('destination'),
            message: value('message').replace(/[\x00-\x1f\x7f]/g, ' ').trim(),
            approved: true, request_key: crypto.randomUUID() };
        } else if (kind === 'task') {
          path = '/api/tasks'; payload = { ws, team, agent: value('agent'), prompt: value('prompt'), provider: value('provider'),
            approved: value('provider') === 'sentra-cli', request_key: crypto.randomUUID(),
            checks: value('check_path') ? [{ path: value('check_path'), text: String(data.get('check_text') || '') }] : [] };
        }
        if (!path) throw Error('Ação não reconhecida.');
        if (kind === 'handoff' || kind === 'task') sealed.current = { path, payload };
      }
      const result = await api(path, payload);
      if (kind === 'workspace' || kind === 'attach') await actions.loadWorkspaces(result.id);
      else await actions.refresh();
      notify(kind === 'handoff' ? 'Transporte: ' + result.status + '. Consulte a resposta em Atividade.' :
        kind === 'agent' ? 'Agente registrado. Acesso ao modelo ainda não verificado.' : 'Operação registrada.', 'info');
      close();
    } catch (e) {
      setError(e.message);
      if (sealed.current) setFrozen(true);
      else if (e.status === 0) setUnknown(true);
    } finally { setBusy(false); }
  }
  return <Modal open onOpenChange={v => { if (!v) close(); }} busy={busy} title={titles[kind]}
    description={kind === 'handoff' ? 'Mensagem para um CLI com conexão dirigida existente.' :
      'Configuração no workspace local. O estado de execução vem do runtime.'}>
    <form ref={form} onSubmit={submit} onKeyDown={e => {
      if (e.target.tagName === 'TEXTAREA' && (e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); form.current.requestSubmit(); }
    }}>
      <fieldset disabled={busy || frozen || unknown} className="dialog-fields">
        {['workspace', 'attach', 'terminal', 'agent', 'team', 'rename', 'duplicate'].includes(kind) &&
          <Field label="Nome"><input name="name" required maxLength={48}
            pattern={['workspace', 'attach'].includes(kind) ? '[A-Za-z][A-Za-z0-9_-]*' : undefined}
            defaultValue={kind === 'rename' ? graph?.title : kind === 'duplicate' ? (graph?.title || '') + '_copia' : ''}
            placeholder={kind === 'workspace' ? 'meu_projeto' : 'Nome da sessão'} /></Field>}
        {kind === 'attach' && <Field label="Pasta existente"><input name="path" required placeholder="C:\\Projetos\\meu_projeto" /></Field>}
        {kind === 'terminal' && <Field label="Ambiente"><select name="shell" required value={shell} onChange={e => setShell(e.target.value)}>
          {!shell && <option value="">Selecione um ambiente instalado</option>}
          {integrations.map(i => <option key={i.id} value={i.id} disabled={!i.installed}>{i.name}{i.installed ? '' : ' · indisponível'}</option>)}
        </select></Field>}
        {(kind === 'agent' || kind === 'terminal' && shell === 'sentra-cli') && <>
          <Field label="Modelo" hint="O catálogo informa nomes; não comprova autenticação ou acesso.">
            <input name="model" list="desktop-models" required defaultValue={defaultModel} />
            <datalist id="desktop-models">{models.map(m => <option key={m} value={m} />)}</datalist>
          </Field>
          {kind === 'terminal' && <Field label="Esforço de raciocínio do Codex"><select name="effort" defaultValue="low">
            <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="xhigh">Extra High</option>
          </select></Field>}
        </>}
        {kind === 'agent' && <>
          <Field label="Função"><select name="role"><option value="worker">Trabalhador</option><option value="coordinator">Coordenador</option><option value="reviewer">Revisor</option></select></Field>
          <Field label="Objetivo" hint="Opcional. Preservado no contexto privado do agente."><textarea name="goal" rows={3} placeholder="O que este agente deve realizar…" /></Field>
          <label className="checkbox-field"><input name="start" type="checkbox" defaultChecked /> Iniciar sessão CLI real</label>
        </>}
        {kind === 'team' && <>
          <Field label="Coordenador"><select name="coordinator" required>{agents.map(a => <option key={a.id} value={a.id}>{a.name} · {a.role}</option>)}</select></Field>
          <Field label="Trabalhadores" hint="Ctrl + clique para selecionar vários."><select name="workers" multiple size={5} required>{agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
        </>}
        {kind === 'note' && <><Field label="Título"><input name="title" required defaultValue="Anotações" /></Field>
          <Field label="Conteúdo"><textarea name="body" rows={5} /></Field></>}
        {kind === 'handoff' && <>
          <Field label="Destino conectado"><select name="destination" required>
            {!destinations.length && <option value="">Nenhum CLI conectado ativo</option>}
            {destinations.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
          </select></Field>
          <Field label="Instrução" hint="Ctrl+Enter envia. ConPTY confirma transporte, não conclusão do modelo.">
            <textarea name="message" required maxLength={4000} rows={5} />
          </Field>
        </>}
        {kind === 'task' && <>
          <Field label="Equipe"><select name="team" required value={team} onChange={e => { setTeam(e.target.value); setMembers([]); }}>{teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
          <Field label="Trabalhador"><select name="agent" required><option value="">Selecione</option>{members.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
          <Field label="Provedor"><select name="provider" defaultValue="sentra-cli"><option value="sentra-cli">SENTRA CLI real</option><option value="test">Teste local · sem IA</option></select></Field>
          <Field label="Tarefa"><textarea name="prompt" required maxLength={4000} rows={5} /></Field>
          <Field label="Arquivo a verificar (opcional)"><input name="check_path" maxLength={1024} /></Field>
          <Field label="Conteúdo esperado"><textarea name="check_text" maxLength={4000} rows={3} /></Field>
        </>}
      </fieldset>
      {error && <p className="form-error" role="alert">{error}</p>}
      {unknown && <p className="form-help">A resposta se perdeu. Atualize o workspace e confira o registro antes de criar novamente.</p>}
      <footer className="dialog-actions"><button type="button" onClick={close} disabled={busy}>Cancelar</button>
        <button type="submit" className="primary" disabled={busy || unknown || kind === 'handoff' && !destinations.length}>
          {busy ? 'Enviando…' : frozen ? 'Repetir a mesma solicitação' : ['handoff', 'task'].includes(kind) ? 'Enviar' : 'Salvar'}
        </button></footer>
    </form>
  </Modal>;
}
export function ConfirmDialog({ request, close }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  return <Modal open onOpenChange={v => { if (!v) close(); }} busy={busy} title={request.title}
    description={request.description}>
    {error && <p className="form-error" role="alert">{error}</p>}
    <footer className="dialog-actions"><button onClick={close} disabled={busy}>Cancelar</button>
      <button className="danger-action" disabled={busy} onClick={async () => {
        setBusy(true); setError(''); try { await request.run(); close(); } catch (e) { setError(e.message); } finally { setBusy(false); }
      }}>{busy ? 'Aplicando…' : 'Confirmar'}</button></footer>
  </Modal>;
}
