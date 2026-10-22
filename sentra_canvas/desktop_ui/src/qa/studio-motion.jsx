// Isolated visual fixture. No API, PTY, provider or real project is connected.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { ShellDotCanvas } from '../shell-dot-canvas';
import '@xyflow/react/dist/style.css';
import '../desktop.css';
import '../shell-polish.css';
import '../shell-coucou-macos.css';

const dots = [
  { dot_id: 'fixture-a', agent_id: 'agent-a', name: 'Agente A · teste visual', mascot: 'blue', project_id: 'fixture', space_id: 'fixture' },
  { dot_id: 'fixture-b', agent_id: 'agent-b', name: 'Agente B · teste visual', mascot: 'mint', project_id: 'fixture', space_id: 'fixture' },
];
const graph = {
  dots, agents: dots.map(dot => ({ id: dot.agent_id })), terminals: [], tools: [], tool_sessions: [], teams: [], tasks: [], deliveries: [],
  nodes: [{ id: 'a', resource_id: 'agent-a', x: 0, y: 80 }, { id: 'b', resource_id: 'agent-b', x: 870, y: 240 }],
  links: [{ id: 'test-cable', source: 'a', target: 'b' }],
};
async function bridge(payload) {
  if (payload.action === 'dot_canvas_get') return structuredClone(graph);
  if (payload.action === 'dot_canvas_move') Object.assign(graph.nodes.find(node => node.id === payload.id), { x: payload.x, y: payload.y });
  return { status: 'ok' };
}
const noop = () => {};
createRoot(document.getElementById('desktop-root')).render(<div className="opendots-shell" style={{flexDirection:'column'}}><div style={{padding:'6px 16px',fontSize:11}}>Teste visual isolado · sem sessões reais</div><ShellDotCanvas dot={dots[0]} roots={[dots[0]]} bridge={bridge} onSelect={noop} onCreate={noop} onConversation={noop} onComputer={noop} /></div>);
