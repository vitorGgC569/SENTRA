import { api, route } from './api';

const element = (tag, text, cls) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (cls) el.className = cls;
  return el;
};
export async function openInspector(kind, { bridge, actions, notify, generation, isCurrent, integrations, models }, target) {
  const state = bridge.current, ws = state.ws;
  const content = document.getElementById('inspector-content');
  const title = document.getElementById('inspector-title');
  const label = document.getElementById('inspector-label');
  document.getElementById('inspector-tabs').hidden = true;
  const alive = () => isCurrent(generation) && state.ws === ws && !document.getElementById('inspector').hidden;
  const scopedAPI = async (path, data) => {
    if (!alive()) throw Error('O painel mudou. Abra novamente para continuar.');
    const value = await api(path, data);
    if (!alive()) throw Error('O painel mudou durante a consulta.');
    return value;
  };
  const requireWS = () => {
    if (!ws || state.ws !== ws) throw Error('Selecione um workspace.');
    return ws;
  };
  const scopedToast = (message, tone) => { if (alive()) notify(message, tone); };
  const machine = () => {
    requireWS();
    if (!window.SentraMachinePanel) throw Error('O painel de máquinas não foi carregado pelo desktop.');
    return window.SentraMachinePanel.open({ api: scopedAPI, state, toast: scopedToast, requireWS });
  };
  content.replaceChildren();
  if (kind === 'machines') return machine();
  if (kind === 'center') {
    requireWS();
    if (!window.SentraCenterPanel) throw Error('A Central não foi carregada pelo desktop.');
    return window.SentraCenterPanel.open({ api: scopedAPI, state, toast: scopedToast, requireWS, machines: machine });
  }
  const row = (name, value) => {
    const block = element('div', undefined, 'inspect-field');
    block.append(element('label', name), element('div', String(value ?? 'Não informado')));
    content.append(block);
  };
  const button = (name, fn, dangerous = false) => {
    const b = element('button', name, dangerous ? 'danger-action' : '');
    b.type = 'button';
    b.addEventListener('click', async () => {
      if (!alive()) return;
      b.disabled = true;
      try { await fn(); } catch (e) { scopedToast(e.message, 'error'); } finally { b.disabled = false; }
    });
    return b;
  };
  if (kind === 'registry') {
    title.textContent = 'Ambientes e modelos'; label.textContent = 'REGISTRY LOCAL';
    for (const i of integrations) row(i.name || i.id, (i.installed ? 'Instalado' : 'Não instalado') +
      (i.native_model_authenticated === true ? ' · autenticação nativa verificada' : ' · acesso ao modelo não verificado'));
    const section = element('section', undefined, 'inspect-field');
    section.append(element('label', 'Catálogo de modelos'));
    section.append(element('p', 'A presença no catálogo não comprova acesso ou disponibilidade.', 'center-note'));
    for (const m of models) section.append(element('code', m, 'registry-model'));
    if (!models.length) section.append(element('p', 'Nenhum catálogo disponível nesta consulta.', 'center-empty'));
    content.append(section); return;
  }
  if (kind === 'activity') {
    requireWS(); title.textContent = 'Atividade'; label.textContent = 'EVENTOS E RECIBOS';
    content.append(element('p', 'Consultando eventos…', 'center-empty'));
    const [events, handoffs] = await Promise.all([
      scopedAPI(route('/api/events', { ws })), scopedAPI(route('/api/graph/handoffs', { ws })),
    ]);
    if (!alive()) return;
    content.replaceChildren();
    for (const receipt of handoffs.slice(0, 30)) row('Handoff · ' + receipt.status, receipt.message || receipt.content || receipt.id);
    if (!events.length && !handoffs.length) content.append(element('p', 'Nenhum evento registrado.', 'center-empty'));
    for (const event of events) {
      const block = element('div', undefined, 'inspect-block');
      block.append(element('small', new Date(event.created * 1000).toLocaleString('pt-BR')),
        element('strong', event.kind), element('p', event.detail || event.subject));
      content.append(block);
    }
    return;
  }
  const graph = state.nodes.find(n => n.id === target);
  if (!graph) { title.textContent = 'Workspace'; label.textContent = 'DETALHES'; row('Pasta', state.detail?.workspace?.path); return; }
  const resources = { terminal: 'terminals', agent: 'agents', team: 'teams' };
  const resource = state.detail?.[resources[graph.kind]]?.find(r => r.id === graph.resource_id);
  title.textContent = graph.title; label.textContent = graph.kind.toUpperCase();
  row('Identidade', graph.resource_id || graph.id);
  row('Namespace', resource?.namespace || 'workspace/' + ws + '/note/' + graph.id);
  if (resource?.status) row('Estado registrado', resource.status);
  if (resource?.model) { row('Modelo solicitado', resource.model); row('Acesso ao modelo', 'Não verificado por este painel.'); }
  if (resource?.role) row('Função', resource.role);
  if (resource?.shell) row('Shell', resource.shell);
  if (resource?.pid) row('PID', resource.pid);
  const actionsRow = element('div', undefined, 'inspect-actions');
  actionsRow.append(button('Enviar instrução', () => actions.open('handoff', graph.id)));
  if (graph.kind === 'terminal') actionsRow.append(
    button('Renomear', () => actions.open('rename', graph.id)),
    button('Duplicar', () => actions.open('duplicate', graph.id)),
    button('Encerrar terminal', () => actions.remove(graph.id), true));
  if (graph.kind === 'agent') {
    actionsRow.append(button('Abrir conversa', () => actions.restart(graph.resource_id)),
      button('Contexto e objetivo', async () => {
        const value = await scopedAPI('/api/agent/context', { ws, agent_id: graph.resource_id });
        if (!alive()) return;
        let editor = content.querySelector('.agent-context-editor');
        if (editor) editor.remove();
        editor = element('section', undefined, 'agent-context-editor inspect-field');
        const revision = element('small', 'Revisão ' + value.revision);
        const field = element('label', 'Objetivo', 'machine-field');
        const goal = element('textarea'); goal.rows = 4; goal.value = value.goal;
        field.append(goal); editor.append(revision, field);
        if (value.parent_agent_id) editor.append(element('p', 'Agente de origem: ' + value.parent_agent_id, 'center-note'));
        let currentRevision = value.revision;
        editor.append(button('Salvar objetivo', async () => {
          if (new TextEncoder().encode(goal.value).length > 16000) throw Error('O objetivo aceita até 16.000 bytes.');
          const result = await scopedAPI('/api/agent/context', { ws, agent_id: graph.resource_id,
            goal: goal.value, expected_revision: currentRevision });
          if (!alive()) return;
          currentRevision = result.revision; goal.value = result.goal;
          revision.textContent = 'Revisão ' + result.revision;
          scopedToast('Objetivo preservado na revisão ' + result.revision + '.');
        }));
        content.append(editor);
      }));
  }
  if (graph.kind === 'team') actionsRow.append(button('Delegar tarefa', () => actions.open('task', graph.id)),
    button('Consultar membros', async () => {
      const members = await scopedAPI(route('/api/team', { ws, id: graph.resource_id }));
      if (alive()) row('Membros', members.map(m => m.name + ' · ' + m.team_role).join('\n'));
    }));
  if (graph.kind === 'note') actionsRow.append(button('Excluir nota', () => actions.remove(graph.id), true));
  content.append(actionsRow);
  const links = state.links.filter(e => e.source === graph.id || e.target === graph.id);
  for (const link of links) {
    const outgoing = link.source === graph.id;
    const other = state.nodes.find(n => n.id === (outgoing ? link.target : link.source));
    row(outgoing ? 'Envia para' : 'Recebe de', other?.title || (outgoing ? link.target : link.source));
  }
}
