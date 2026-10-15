import React, { useEffect, useState } from 'react';
import { ReactFlow, ReactFlowProvider, Background, BackgroundVariant, Controls, Handle, Position, Panel, NodeResizer, useReactFlow, applyNodeChanges, applyEdgeChanges } from '@xyflow/react';
import { MessageCircle, Monitor, Plus, Workflow, MousePointer2, Hand, Cable, Grid2X2, Scan, TerminalSquare, Maximize2, Minimize2 } from 'lucide-react';
import { DotMascot } from './shell-mascot';
import { PtySlot } from './nodes';
import { canvasPhase, phaseCopy, summarizePhases, taskPresentation } from './shell-canvas-state';
import { FailureNotice } from './shell-failure.jsx';
import { Status } from './shell-receipts';
import { CanvasCable, CanvasConnection } from './shell-canvas-cable';

const providers = [
  { id: 'dot', title: 'Conversa do Dot' },
  { id: 'sentra-cli', title: 'SENTRA CLI · GPT-6 High' },
  { id: 'opencode', title: 'OpenCode · Muse Spark High' },
  { id: 'codex', title: 'Codex CLI' },
  { id: 'grok', title: 'Grok · 4.7' },
];

function AgentTerminal({ id, data, selected: nodeSelected }) {
  const flow = useReactFlow();
  const { member, agent, defaultTerminal, sessions, tools, tasks, teams, deliveries, incoming,
    start, close, converse, send, submit, cancel, project, busy } = data;
  const [toolChoice, setChosen] = useState(null), [expanded, setExpanded] = useState(false);
  const chosen = toolChoice || (defaultTerminal?.status === 'running' ? 'dot' : sessions.find(session => session.terminal?.status === 'running')?.tool || 'dot');
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
  function resizeWindow() {
    const next = !expanded;
    setExpanded(next);
    flow.setNodes(nodes => nodes.map(node => node.id === id ? { ...node, width: next ? 960 : 620, height: next ? 620 : 440, style: { ...node.style, width: next ? 960 : 620, height: next ? 620 : 440 } } : node));
  }
  return <article className={'shell-agent-terminal' + (selected ? ' has-terminal' : '')}>
    <NodeResizer isVisible={nodeSelected} minWidth={400} minHeight={280} maxWidth={1400} maxHeight={1000} color="var(--polish-accent)" />
    <Handle type="target" position={Position.Left} />
    <header className="shell-agent-titlebar"><TerminalSquare size={13} /><DotMascot mascot={member.mascot} identity={member.agent_id} name={member.name} status={member.status} execution={member.execution} size="nav" decorative /><div className="shell-agent-identity"><strong>{member.name}</strong><small title={agent?.model}>{agent?.model?.split('/').pop() || 'Seu Dot'}</small></div><button className="nodrag shell-icon" title="Abrir conversa" aria-label={'Conversar com ' + member.name} onClick={converse}><MessageCircle size={14} /></button><button className="nodrag shell-icon" aria-label={expanded ? 'Restaurar janela do terminal' : 'Ampliar janela do terminal'} onClick={resizeWindow}>{expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}</button></header>
    <nav className="nodrag nowheel shell-agent-tools" aria-label={'Ferramentas de ' + member.name}>
      <label>Ferramenta<select aria-label={'Ferramenta de ' + member.name} value={chosen} disabled={busy} onChange={event => setChosen(event.target.value)}>{providers.map(item => <option key={item.id} value={item.id} disabled={item.id !== 'dot' && !tools.some(t => t.id === item.id && t.installed)}>{item.title}</option>)}</select></label>
    </nav>
    <div className="nodrag nowheel shell-agent-session" style={{display:'flex',gap:8,alignItems:'center'}}>
      {selected?.status ? <Status value={selected.status} /> : <span>{installed ? 'Não iniciado' : 'Não instalado'}</span>}
      {chosen !== 'dot' && !selected?.status?.includes('running') &&
        <button disabled={busy || !installed} onClick={() => start(chosen)}>Abrir sessão</button>}
      {chosen !== 'dot' && selected?.status === 'running' &&
        <button disabled={busy} onClick={() => close(chosen)}>Encerrar sessão</button>}
    </div>
    <div className="shell-agent-stage">
      {selected ? <PtySlot ws={project} resource={selected} priority={20} /> :
        <div className="shell-terminal-empty"><TerminalSquare size={28} /><strong>{chosen === 'dot' ? 'Conversa de ' + member.name : providers.find(item => item.id === chosen)?.title}</strong><p>{chosen === 'dot' ? 'Escolha uma ferramenta acima para usar o terminal aqui.' : 'O terminal aparecerá aqui quando a sessão for aberta.'}</p>{chosen === 'dot' && <button className="nodrag" onClick={converse}><MessageCircle size={14} />Abrir conversa</button>}</div>}
    </div>
    <div className="shell-agent-details nodrag nowheel">
    {chosen !== 'dot' && <details className="shell-agent-fold"><summary>Enviar instrução</summary><div>
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
    </div></details>}
    <details className="shell-agent-fold"><summary>Tarefas e atividade <span>{recent.length + toolReceipts.length || ''}</span></summary><div>
      <label>Nova tarefa</label>
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
      {recent.map(task => {
        const view = taskPresentation(task, { owner: member?.name || agent?.id });
        return <div key={task.id} className="shell-phase-row" data-phase={view.phase}>
          <code title={view.receipt || task.id}>{task.id.slice(0,8)}</code>
          <span className="shell-phase" data-phase={view.phase}>{view.label}</span>
          <span>{view.owner} · {view.progress}{task.cancel_requested ? ' · cancelamento solicitado' : ''}</span>
          <small>{view.safeNext}{view.dependency ? ' Dependência: ' + view.dependency + '.' : ''}</small>
          {['queued','running'].includes(task.status) &&
            <button disabled={busy} onClick={() => cancel(task.id)}>Solicitar cancelamento</button>}
        </div>;
      })}
      {toolReceipts.map(receipt => {
        const phase = canvasPhase({ workItemState: receipt.work_item_state, operationState: receipt.operation_state });
        return <div key={receipt.handoff_id} title={receipt.operation_id} className="shell-phase-row" data-phase={phase}
        style={{display:'grid',gap:2,borderTop:'1px solid #444',paddingTop:5}}>
        <strong><span className="shell-phase" data-phase={phase}>{phaseCopy(phase).label}</span> Recibo {receipt.tool} ({receipt.mode === 'dispatch' ? 'Não-interativo' : 'ConPTY'})</strong>
        <small>WorkItem: {receipt.work_item_id} · Operation: {receipt.operation_id}</small>
        {receipt.receipt?.effective_model && <small>Modelo reportado: {receipt.receipt.effective_model} · Exit code: {receipt.receipt.exit_code}</small>}
        <small>Saída stdout: {receipt.transcript_evidence?.post_send_chars ?? receipt.receipt?.output_chars ?? 0} chars · SHA-256: {(receipt.transcript_evidence?.post_send_sha256 || receipt.receipt?.stdout_sha256 || 'indisponível').slice(0, 16)}…</small>
        {receipt.receipt?.echo_only_detected && <small style={{color:'#ff7b72'}}>Eco de entrada detectado no terminal (rejeitado: não comprova inferência)</small>}
        {receipt.model_result_verified && <small style={{color:'#7ee787'}}>Inferência comprovada via transformação de nonce (REVERSE/SHA256)</small>}
        {!receipt.model_result_verified && !receipt.receipt?.echo_only_detected &&
          <small>{receipt.operation_state === 'UNCERTAIN' ? 'Estado incerto: sem repetição automática' : 'Resultado do modelo NÃO comprovado; não concluir nem reenviar automaticamente'}</small>}
      </div>;
      })}
      <small>Conclusão só após consolidação do coordenador. Antigravity: aplicativo externo, sem API de agente validada.</small>
    </div></details></div>
    <Handle type="source" position={Position.Right} />
  </article>;
}
const types = { agentTerminal: AgentTerminal };
const edgeTypes = { cable: CanvasCable };

function CanvasTools({ tool, onTool, grid, onGrid, onCreate, onComputer, busy }) {
  const flow = useReactFlow();
  return <Panel position="top-center" className="shell-studio-tools" role="toolbar" aria-label="Ferramentas do canvas">
    <button aria-label="Selecionar" title="Selecionar" aria-pressed={tool === 'select'} onClick={() => onTool('select')}><MousePointer2 size={16} /></button>
    <button aria-label="Mover canvas" title="Mover canvas" aria-pressed={tool === 'pan'} onClick={() => onTool('pan')}><Hand size={16} /></button>
    <span className="shell-studio-divider" />
    <button aria-label="Adicionar terminal de agente" title="Adicionar terminal de agente" onClick={onCreate} disabled={busy}><TerminalSquare size={16} /></button>
    <button aria-label="Conectar agentes" title="Conectar agentes" aria-pressed={tool === 'connect'} onClick={() => onTool('connect')}><Cable size={16} /></button>
    <button aria-label="Computador do Dot" title="Computador do Dot" onClick={onComputer}><Monitor size={16} /></button>
    <span className="shell-studio-divider" />
    <button aria-label="Mostrar grade" title="Mostrar grade" aria-pressed={grid} onClick={onGrid}><Grid2X2 size={15} /></button>
    <button aria-label="Enquadrar terminais" title="Enquadrar terminais" onClick={() => flow.fitView({ padding: .2, maxZoom: 1 })}><Scan size={16} /></button>
  </Panel>;
}

export function ShellDotCanvas({ dot, roots, bridge, onSelect, onCreate, onConversation, onComputer }) {
  const [nodes, setNodes] = useState([]), [edges, setEdges] = useState([]), [error, setError] = useState('');
  const [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [tool, setTool] = useState('select'), [grid, setGrid] = useState(true);
  const [phases, setPhases] = useState(() => summarizePhases());
  const [phaseId, setPhaseId] = useState(null);
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
        dragging: local?.dragging, selected: local?.selected, resizing: local?.resizing, width: local?.width, height: local?.height, type: 'agentTerminal', dragHandle: '.shell-agent-titlebar',
        style: local?.style || { width: 620, height: 440 },
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
    setEdges(value.links.map(link => ({ id: link.id, source: link.source, target: link.target, type: 'cable' })));
    setPhases(summarizePhases(value.tasks || [], value.deliveries || []));
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
      else if (!['dot_canvas_move', 'dot_canvas_link', 'dot_canvas_unlink'].includes(action)) setNotice('Estado: ' + result.status);
      await refresh();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const chosenPhase = phaseId ? phases.find(item => item.id === phaseId) : null;
  return <section className="shell-dot-canvas shell-studio" aria-label={'Canvas de ' + dot.name}>
    {error && <FailureNotice message={error} onConsult={() => { void refresh().catch(e => setError(e.message)); }} onDismiss={() => setError('')} />}
    {notice && <p role="status">{notice}</p>}
    {loading && <p className="shell-empty" role="status">Carregando terminais do Canvas…</p>}
    <div className="shell-dot-flow"><ReactFlowProvider><ReactFlow nodes={nodes} edges={edges} nodeTypes={types} edgeTypes={edgeTypes} connectionLineComponent={CanvasConnection} colorMode="dark" fitView fitViewOptions={{ padding: 0.3, minZoom: 0.4, maxZoom: 1 }} minZoom={0.15} maxZoom={1.75} defaultEdgeOptions={{ type: 'cable' }}
      nodesDraggable={!busy && tool !== 'pan'} nodesConnectable={!busy} deleteKeyCode={null} panOnDrag={tool === 'pan' ? true : [1, 2]} selectionOnDrag={tool === 'select'} selectionKeyCode="Shift"
      onNodesChange={changes => setNodes(old => applyNodeChanges(changes, old))}
      onEdgesChange={changes => setEdges(old => applyEdgeChanges(changes, old))}
      onNodeDragStop={(_, node) => void mutate('dot_canvas_move', { id: node.id, x: Math.round(node.position.x), y: Math.round(node.position.y) })}
      onConnect={value => void mutate('dot_canvas_link', { source: value.source, target: value.target })}
      onEdgeDoubleClick={(_, edge) => void mutate('dot_canvas_unlink', { id: edge.id })}>
      {grid && <><Background id="fine" variant={BackgroundVariant.Lines} color="#ffffff06" gap={8} lineWidth={.5} /><Background id="major" variant={BackgroundVariant.Lines} color="#ffffff0b" gap={40} lineWidth={.6} /></>}
      <Panel position="top-left" className="shell-studio-location"><Workflow size={14} /><select aria-label="Canvas do Dot" value={dot.dot_id} onChange={e => onSelect(e.target.value)}>{roots.map(item => <option key={item.dot_id} value={item.dot_id}>{item.name}</option>)}</select></Panel>
      <CanvasTools tool={tool} onTool={setTool} grid={grid} onGrid={() => setGrid(value => !value)} onCreate={() => onCreate(dot)} onComputer={() => onComputer(dot)} busy={busy} />
      <Controls showInteractive={false} orientation="horizontal" position="bottom-right" /><Panel position="bottom-left" className="shell-canvas-hint"><MousePointer2 size={13} /><span>{tool === 'connect' ? 'Arraste de um conector ao outro' : tool === 'pan' ? 'Arraste o fundo para explorar' : 'Arraste as janelas · role para ampliar'}</span></Panel>{!loading && !nodes.length && <Panel position="top-center" className="shell-canvas-empty"><TerminalSquare size={28} /><strong>Seu espaço de trabalho.</strong><p>Adicione um agente para abrir seu primeiro terminal.</p><button onClick={() => onCreate(dot)} disabled={busy}><Plus size={15} />Adicionar agente</button></Panel>}</ReactFlow></ReactFlowProvider></div>
  </section>;
}
