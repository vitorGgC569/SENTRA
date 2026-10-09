import React, { memo, useLayoutEffect, useRef } from 'react';
import { Handle, Position, NodeResizer } from '@xyflow/react';
import { TerminalSquare, Bot, Users, StickyNote, Maximize2, Send, Copy, Pencil, PanelRight, X } from 'lucide-react';
import { IconButton, ActionMenu } from './primitives';
import { useDesktop } from './context';

const icons = { terminal: TerminalSquare, agent: Bot, team: Users, note: StickyNote };
export function PtySlot({ ws, resource, priority = 1 }) {
  const { pool } = useDesktop(); const ref = useRef(null);
  useLayoutEffect(() => pool.attach(ws, resource, ref.current, priority), [pool, ws, resource.id, priority]);
  return <div ref={ref} className="pty-slot nodrag nowheel nopan" aria-label={'Terminal ' + resource.name} />;
}
export const SessionNode = memo(function SessionNode({ id, data, selected }) {
  const { actions, pool, ws, collaboration } = useDesktop();
  const { graph, resource, terminal, owner } = data;
  const Icon = icons[graph.kind] || StickyNote;
  const actual = terminal && (pool.state(ws, terminal.id) || terminal);
  const status = actual?.transportUnavailable ? 'Conexão indisponível' :
    actual?.recoverable === false ? 'Histórico recuperado' : actual?.status;
  const noteRef = useRef(null);
  const currentBody = useRef(graph.body || '');
  useLayoutEffect(() => {
    if (graph.kind === 'note' && noteRef.current && document.activeElement !== noteRef.current) {
      noteRef.current.value = graph.body || ''; currentBody.current = graph.body || '';
    }
  }, [graph.body, graph.kind]);
  const items = [
    { label: 'Detalhes', icon: <PanelRight size={14} />, action: () => actions.inspect(id) },
    { label: 'Enviar instrução', icon: <Send size={14} />, action: () => actions.open('handoff', id) },
  ];
  if (graph.kind === 'terminal') {
    items.push({ label: 'Renomear', icon: <Pencil size={14} />, action: () => actions.open('rename', id) },
      { label: 'Duplicar terminal', icon: <Copy size={14} />, action: () => actions.open('duplicate', id) },
      { separator: true },
      { label: 'Encerrar terminal', danger: true, icon: <X size={14} />, action: () => actions.remove(id) });
  }
  if (graph.kind === 'note') items.push({ separator: true },
    { label: 'Excluir nota', danger: true, icon: <X size={14} />, action: () => actions.remove(id) });
  return <article className={'session-node ' + graph.kind + (selected ? ' selected' : '')} data-desktop-node={id}>
    <NodeResizer isVisible={selected} minWidth={250} minHeight={150} maxWidth={1100} maxHeight={850}
      color="#7c8795" onResizeStart={() => actions.editing(id)}
      onResizeEnd={(_, params) => actions.resized(id, params)} />
    <Handle type="target" position={Position.Left} id="input" className="session-handle" />
    <header className="node-titlebar" onDoubleClick={() => terminal && !owner && actions.expand(id)}>
      <Icon size={13} className={'kind-icon ' + graph.kind} />
      <span className="node-name" title={graph.title}>{graph.title}</span>
      <span className="node-kind">{terminal?.shell || graph.kind}</span>
      {terminal && !owner && <IconButton label="Ampliar terminal" className="nodrag" onClick={() => actions.expand(id)}><Maximize2 size={13} /></IconButton>}
      <ActionMenu items={items} />
    </header>
    {terminal && !owner ? <>
      {graph.kind === 'agent' && <div className="agent-session-line" title={resource?.model}>{resource?.model} · {resource?.role}</div>}
      <PtySlot ws={ws} resource={terminal} />
      <footer className="node-footer"><span className={'session-dot ' + (status === 'running' ? 'running' : '')} />
        <span>{status === 'running' ? 'Em execução' : status || 'Estado não informado'}</span>
        <span className="footer-spacer" />
        {terminal.shell === 'sentra-cli' ? <span className="cli-controls">
          <button className="nodrag" title="Consultar modelo no CLI" onClick={() => pool.command(ws, terminal.id, '/model')}>/model</button>
          <button className="nodrag" title="Consultar esforço no CLI" onClick={() => pool.command(ws, terminal.id, '/effort')}>/effort</button>
        </span> : <span>{actual?.persisted === false ? 'Histórico não salvo' : terminal.shell}</span>}
        <span>{terminal.pid ? 'PID ' + terminal.pid : ''}</span>
      </footer>
    </> : owner ? <div className="reference-node"><strong>{owner.name}</strong>
      <p>Esta sessão está no nó do agente.</p>
      <button className="nodrag" onClick={() => actions.focusResource(owner.id)}>Abrir sessão</button>
    </div> : graph.kind === 'note' ?
      <textarea ref={noteRef} className="note-editor nodrag nowheel nopan" data-note={id}
        aria-label={'Conteúdo de ' + graph.title} defaultValue={graph.body || ''} placeholder="Anotações…"
        onChange={e => { currentBody.current = e.target.value; if (!collaboration.current?.active()) actions.saveNote(id, e.target.value); }}
        onBlur={() => { if (!collaboration.current?.active()) actions.saveNote(id, currentBody.current, true); }} /> :
      graph.kind === 'agent' ? <div className="resource-node"><code>{resource?.model || 'Modelo não informado'}</code>
        <p>{resource?.role} · {resource?.status || 'Estado não informado'}</p><p>Sessão CLI não iniciada.</p>
        <button className="nodrag" onClick={() => actions.restart(graph.resource_id)}>Abrir conversa</button>
      </div> : <div className="resource-node"><p>Equipe do workspace</p>
        <strong>{resource?.name || graph.title}</strong>
        <button className="nodrag" onClick={() => actions.open('task', id)}>Delegar tarefa</button>
      </div>}
    <Handle type="source" position={Position.Right} id="output" className="session-handle" />
  </article>;
});
export const nodeTypes = { session: SessionNode };
