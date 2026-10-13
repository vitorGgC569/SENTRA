import React, { useEffect, useState } from 'react';
import { ReactFlow, ReactFlowProvider, Background, Controls, Handle, Position, applyNodeChanges, applyEdgeChanges } from '@xyflow/react';
import { DotMascot } from './shell-mascot';
import { PtySlot } from './nodes';

const providers = [
  { id: 'dot', title: 'Conversa do Dot' },
  { id: 'sentra-cli', title: 'SENTRA CLI · GPT-6 High' },
  { id: 'opencode', title: 'OpenCode · Muse Spark High' },
  { id: 'codex', title: 'Codex CLI' },
];

function AgentTerminal({ data }) {
  const { member, agent, defaultTerminal, sessions, tools, tasks, teams, deliveries, incoming,
    start, close, converse, send, submit, cancel, project, busy } = data;
  const [chosen, setChosen] = useState('dot');
  const [message, setMessage] = useState('');
  const [prompt, setPrompt] = useState('');
  const [sender, setSender] = useState('');
  const [team, setTeam] = useState('');
  const selected = chosen === 'dot' ? defaultTerminal : sessions.find(s => s.tool === chosen)?.terminal;
  const installed = chosen === 'dot' || tools.find(t => t.id === chosen)?.installed;
  const suitableTeams = teams.filter(t => t.worker_ids.includes(agent?.id));
  const from = incoming.find(item => item.dot_id === sender) || incoming[0];
  const taskTeam = suitableTeams.find(item => item.id === team) || suitableTeams[0];
  const recent = tasks.filter(t => t.agent_id === agent?.id).slice(-4).reverse();
  const toolReceipts = deliveries.filter(d => d.member_dot_id === member.dot_id).slice(0, 5);
  return <article className="shell-agent-terminal">
    <Handle type="target" position={Position.Left} />
    <header><strong>{member.name}</strong><button className="nodrag" onClick={converse}>Conversa</button>
      <small>{agent?.model || 'Modelo do Dot não informado'}</small></header>
    <nav className="nodrag nowheel" aria-label={'Ferramentas de ' + member.name}>
      {providers.map(item => <button key={item.id} type="button" disabled={busy || (item.id !== 'dot' && !tools.some(t => t.id === item.id && t.installed))}
        aria-pressed={chosen === item.id} onClick={() => setChosen(item.id)}>{item.title}</button>)}
    </nav>
    <div className="nodrag nowheel" style={{display:'flex',gap:8,alignItems:'center'}}>
      <span>{selected?.status || (installed ? 'Não iniciado' : 'Não instalado')}</span>
      {chosen !== 'dot' && !selected?.status?.includes('running') &&
        <button disabled={busy || !installed} onClick={() => start(chosen)}>Abrir sessão</button>}
      {chosen !== 'dot' && selected?.status === 'running' &&
        <button disabled={busy} onClick={() => close(chosen)}>Encerrar sessão</button>}
      {chosen === 'dot' && !selected && <span>Conversa principal: abrir na conversa do Dot.</span>}
    </div>
    <div style={{height:175,overflow:'hidden'}}>
      {selected ? <PtySlot ws={project} resource={selected} priority={20} /> :
        <div className="shell-terminal-empty">Nenhum terminal ativo nesta ferramenta.</div>}
    </div>
    {chosen !== 'dot' && <div className="nodrag nowheel" style={{display:'grid',gap:5}}>
      <label>Coordenar por ligação dirigida (envio não comprova execução)</label>
      <select aria-label="Dot remetente" value={from?.dot_id || ''} onChange={e => setSender(e.target.value)}>
        {incoming.length === 0 && <option value="">Conecte outro Dot a este nó</option>}
        {incoming.map(item => <option key={item.dot_id} value={item.dot_id}>{item.name}</option>)}
      </select>
      <div style={{display:'flex',gap:5}}>
        <input aria-label="Mensagem ao terminal" maxLength={4000} value={message}
          placeholder="Instrução sem quebras de linha" onChange={e => setMessage(e.target.value)} />
        <button disabled={busy || !from || selected?.status !== 'running' || !message.trim()}
          onClick={() => {
            if (!window.confirm('Enviar a instrução ao CLI? O envio não confirma aceite ou conclusão.')) return;
            send(from.dot_id, chosen, message); setMessage('');
          }}>Enviar</button>
      </div>
    </div>}
    <div className="nodrag nowheel" style={{display:'grid',gap:5}}>
      <label>Tarefa SENTRA (aceitar ≠ concluir)</label>
      <div style={{display:'flex',gap:5}}>
        <select aria-label="Equipe autorizada" value={taskTeam?.id || ''} onChange={e => setTeam(e.target.value)}>
          {suitableTeams.length === 0 && <option value="">Dot não é trabalhador de uma equipe</option>}
          {suitableTeams.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <input aria-label="Objetivo da tarefa" maxLength={4000} value={prompt}
          placeholder="Trabalho para este Dot" onChange={e => setPrompt(e.target.value)} />
        <button disabled={busy || !taskTeam || !prompt.trim()} onClick={() => {
          if (!window.confirm('Autorizar o SENTRA CLI a executar esta tarefa real?')) return;
          submit(taskTeam.id, prompt); setPrompt('');
        }}>Aceitar tarefa</button>
      </div>
      {recent.map(task => <div key={task.id} style={{display:'flex',gap:6,alignItems:'center'}}>
        <code title={task.work_item_id || task.id}>{task.id.slice(0,8)}</code>
        <span>{task.status}{task.cancel_requested ? ' · cancelamento solicitado' : ''}</span>
        {['queued','running'].includes(task.status) &&
          <button disabled={busy} onClick={() => cancel(task.id)}>Solicitar cancelamento</button>}
      </div>)}
      {toolReceipts.map(receipt => <div key={receipt.handoff_id} title={receipt.operation_id}
        style={{display:'grid',gap:2,borderTop:'1px solid #444',paddingTop:5}}>
        <strong>Recibo {receipt.tool} ({receipt.mode === 'dispatch' ? 'Não-interativo' : 'ConPTY'}) · {receipt.work_item_state === 'IN_REVIEW' ? 'EM REVISÃO' : receipt.work_item_state} / {receipt.operation_state}</strong>
        <small>WorkItem: {receipt.work_item_id} · Operation: {receipt.operation_id}</small>
        {receipt.receipt?.effective_model && <small>Modelo reportado: {receipt.receipt.effective_model} · Exit code: {receipt.receipt.exit_code}</small>}
        <small>Saída stdout: {receipt.transcript_evidence?.post_send_chars ?? receipt.receipt?.output_chars ?? 0} chars · SHA-256: {(receipt.transcript_evidence?.post_send_sha256 || receipt.receipt?.stdout_sha256 || 'indisponível').slice(0, 16)}…</small>
        {receipt.receipt?.echo_only_detected && <small style={{color:'#ff7b72'}}>Eco de entrada detectado no terminal (rejeitado: não comprova inferência)</small>}
        {receipt.model_result_verified && <small style={{color:'#7ee787'}}>Inferência comprovada via transformação de nonce (REVERSE/SHA256)</small>}
        {!receipt.model_result_verified && !receipt.receipt?.echo_only_detected &&
          <small>{receipt.operation_state === 'UNCERTAIN' ? 'Estado incerto: sem repetição automática' : 'Resultado do modelo NÃO comprovado; não concluir nem reenviar automaticamente'}</small>}
      </div>)}
      <small>Conclusão só após consolidação do coordenador. Antigravity: aplicativo externo, sem API de agente validada.</small>
    </div>
    <Handle type="source" position={Position.Right} />
  </article>;
}
const types = { agentTerminal: AgentTerminal };

export function ShellDotCanvas({ dot, roots, bridge, onSelect, onCreate, onConversation, onComputer }) {
  const [nodes, setNodes] = useState([]), [edges, setEdges] = useState([]), [error, setError] = useState('');
  const [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const scope = { project_id: dot.project_id, space_id: dot.space_id, dot_id: dot.dot_id };
  async function refresh() {
    const value = await bridge({ action: 'dot_canvas_get', ...scope });
    setNodes(previous => value.nodes.map(node => {
      const member = value.dots.find(item => item.agent_id === node.resource_id);
      const agent = value.agents.find(item => item.id === node.resource_id);
      const terminal = value.terminals.find(item => item.id === agent?.terminal_id);
      const local = previous.find(item => item.id === node.id);
      const incoming = value.links.filter(link => link.target === node.id).map(link => {
        const fromNode = value.nodes.find(item => item.id === link.source);
        return value.dots.find(item => item.agent_id === fromNode?.resource_id);
      }).filter(Boolean);
      return { id: node.id, position: local?.dragging ? local.position : { x: node.x, y: node.y },
        dragging: local?.dragging, selected: local?.selected, type: 'agentTerminal',
        style: { width: 760, height: 615 },
        data: { member, agent, defaultTerminal: terminal,
          sessions: value.tool_sessions.filter(s => s.member_dot_id === member?.dot_id),
          tools: value.tools, tasks: value.tasks, teams: value.teams, deliveries: value.deliveries || [], incoming, project: scope.project_id, busy,
          converse: () => onConversation(member),
          start: tool => void mutate('dot_canvas_terminal', { member_dot_id: member.dot_id, tool }),
          close: tool => void mutate('dot_canvas_terminal_close', { member_dot_id: member.dot_id, tool }),
          send: (source_dot_id, tool, message) => void mutate('dot_canvas_handoff',
            { source_dot_id, member_dot_id: member.dot_id, tool, message, approved: true }),
          submit: (team_id, prompt) => void mutate('dot_canvas_task_submit',
            { team_id, member_dot_id: member.dot_id, prompt, approved: true }),
          cancel: task_id => void mutate('dot_canvas_task_cancel', { task_id }) } };
    }));
    setEdges(value.links.map(link => ({ id: link.id, source: link.source, target: link.target })));
    setError(''); setLoading(false);
  }
  useEffect(() => {
    let active = true, loading = false;
    const load = async () => { if (!active || loading || document.hidden) return; loading = true;
      try { await refresh(); } catch (e) { if (active) { setError(e.message); setLoading(false); } } finally { loading = false; } };
    void load(); const timer = setInterval(load, 4000);
    return () => { active = false; clearInterval(timer); };
  }, [dot.dot_id, dot.project_id, dot.space_id]);
  async function mutate(action, fields) {
    setBusy(true); setNotice('');
    try {
      const result = await bridge({ action, ...scope, ...fields, request_key: crypto.randomUUID() });
      if (result.status === 'uncertain') throw Error('Efeito incerto; consulte o diário, nunca reenvie automaticamente.');
      if (result.status === 'sent') setNotice('Enviado ao ConPTY. Aceite e resultado do modelo ainda não comprovados.');
      else if (result.status === 'accepted') setNotice('Tarefa aceita: ' + result.task_id + '. Execução/conclusão pendentes.');
      else if (result.status === 'cancel_requested') setNotice('Cancelamento solicitado; aguarde confirmação do executor.');
      else setNotice('Estado: ' + result.status);
      await refresh();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <section className="shell-dot-canvas" aria-label={'Canvas de ' + dot.name}>
    <header className="shell-dot-canvas-heading"><DotMascot mascot={dot.mascot} identity={dot.agent_id} name={dot.name} size="small" decorative /><strong>{dot.name}</strong>
      <select aria-label="Canvas do Dot" value={dot.dot_id} onChange={e => onSelect(e.target.value)}>
        {roots.map(item => <option key={item.dot_id} value={item.dot_id}>{item.name}</option>)}</select>
      <button onClick={() => onComputer(dot)}>Computador</button><button onClick={() => onCreate(dot)} disabled={busy}>Novo terminal de agente</button></header>
    {error && <p className="shell-error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {loading && <p className="shell-empty" role="status">Carregando terminais do Canvas…</p>}
    <div className="shell-dot-flow"><ReactFlowProvider><ReactFlow nodes={nodes} edges={edges} nodeTypes={types} colorMode="dark" fitView
      nodesDraggable={!busy} nodesConnectable={!busy} deleteKeyCode={null}
      onNodesChange={changes => setNodes(old => applyNodeChanges(changes, old))}
      onEdgesChange={changes => setEdges(old => applyEdgeChanges(changes, old))}
      onNodeDragStop={(_, node) => void mutate('dot_canvas_move', { id: node.id, x: Math.round(node.position.x), y: Math.round(node.position.y) })}
      onConnect={value => void mutate('dot_canvas_link', { source: value.source, target: value.target })}
      onEdgeDoubleClick={(_, edge) => void mutate('dot_canvas_unlink', { id: edge.id })}>
      <Background color="#343434" /><Controls showInteractive={false} /></ReactFlow></ReactFlowProvider></div>
  </section>;
}
