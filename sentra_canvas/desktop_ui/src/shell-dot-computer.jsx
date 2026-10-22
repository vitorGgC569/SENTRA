import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronLeft, FileText, Folder, Globe, Monitor, RefreshCw, Terminal, X, Maximize2, Minimize2 } from 'lucide-react';
import { ShellMachines } from './shell-machines';
import { PtySlot } from './nodes';
import { DotMascot } from './shell-mascot';
import { ShellDotVm } from './shell-dot-vm';
import { DotFamilyControls } from './shell-dot-family.jsx';
import { ComputerStatusStrip } from './shell-computer-status.jsx';
import { ComputerResizeHandle } from './shell-computer-resize.jsx';

function ComputerFiles({ inventory, conversation, bridge, onConfigure }) {
  const [path, setPath] = useState('.'), [result, setResult] = useState(null), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [pending, setPending] = useState(null);
  const intent = useRef(null), alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const work = inventory.work_items.find(item => item.capabilities.includes('computer:file.read') &&
    (!item.conversation_id || item.conversation_id === conversation?.conversation_id));
  async function read(target, action = 'list') {
    if (busy || (!work && !intent.current)) return;
    const request = intent.current || { action: 'machine_execute', machine_id: work.machine_id,
      work_item_id: work.work_item_id, capability_id: 'computer:file.read', request_key: crypto.randomUUID(),
      arguments: { action, path: target } };
    intent.current = request; setBusy(true); setError('');
    try {
      const value = await bridge(request);
      if (!alive.current) return;
      if (value.state === 'UNCERTAIN' || value.status === 'uncertain') { setPending(request); setError('A leitura ainda não foi confirmada.'); return; }
      intent.current = null; setPending(null);
      if (value.state !== 'SUCCEEDED') throw Error(value.error || 'A leitura não foi autorizada ou não foi concluída.');
      const evidence = value.evidence?.payload || value.evidence;
      setResult(evidence); setPath(evidence.path || target);
    } catch (e) {
      if (!alive.current) return;
      setError(e.message); if (e.uncertain) setPending(request); else { intent.current = null; setPending(null); }
    } finally { if (alive.current) setBusy(false); }
  }
  return <section className="dot-computer-files" aria-label="Arquivos autorizados do Dot">
    {!work ? <div className="dot-computer-empty"><Folder size={38} /><strong>Leitura de arquivos indisponível</strong><p>Selecione um perfil de acesso nesta conversa para consultar arquivos pelo Dot.</p><button onClick={onConfigure}>Ver configurações</button></div> : <>
      <form onSubmit={e => { e.preventDefault(); void read(path); }}><input aria-label="Pasta autorizada" value={path} onChange={e => setPath(e.target.value)} disabled={busy || Boolean(pending)} /><button disabled={busy || Boolean(pending) || !path.trim()}><RefreshCw size={14} />Listar</button></form>
      {pending && <p className="shell-notice">Leitura pendente. <button disabled={busy} onClick={() => read(path)}>Consultar mesma leitura</button></p>}
      {error && <p className="shell-error" role="alert">{error}</p>}
      {result?.items && <div className="dot-computer-file-list">{result.items.map(item => <button key={item.name} disabled={busy || Boolean(pending)} onClick={() => read(result.path + '/' + item.name, item.directory ? 'list' : 'read')}>{item.directory ? <Folder size={16} /> : <FileText size={16} />}<span>{item.name}</span></button>)}{!result.items.length && <p>Pasta vazia.</p>}</div>}
      {typeof result?.content === 'string' && <><button disabled={busy || Boolean(pending)} onClick={() => read(result.path.replace(/[\\/][^\\/]+$/, '') || '.') }><ChevronLeft size={14} />Pasta</button><pre className="dot-computer-file-preview">{result.content.slice(0, 65536)}</pre>{result.content.length > 65536 && <small>Prévia limitada a 64 mil caracteres.</small>}</>}
      {result?.base64 && <p>Arquivo binário · prévia de texto indisponível.</p>}
    </>}
  </section>;
}

export function ShellDotComputer({ dot, conversation, bridge, onClose, onConfigure, onCanvas, visible = true, initialTab = 'desktop', simple = false }) {
  const [tab, setTab] = useState(initialTab), [inventory, setInventory] = useState({ machines: [], work_items: [], agents: [], terminals: [], dots: [] });
  const [machine, setMachine] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const panelRef = useRef(null);
  const [error, setError] = useState(''), [agentId, setAgentId] = useState(dot.agent_id);
  const scopedBridge = useCallback(async payload => {
    const { action, request_key, project_id, space_id, dot_id, conversation_id, ...request } = payload;
    const scope = { project_id: dot.project_id, space_id: dot.space_id, dot_id: dot.dot_id,
      ...(conversation?.conversation_id ? { conversation_id: conversation.conversation_id } : {}) };
    if (action === 'machine_list') return bridge({ action: 'dot_computer_get', ...scope });
    return bridge({ action: ['input_status', 'machine_observe'].includes(action) ? 'dot_computer_read' : 'dot_computer_action',
      ...scope, request: { action, ...request }, ...(request_key ? { request_key } : {}) });
  }, [dot.project_id, dot.space_id, dot.dot_id, dot.canvas_root_dot_id, conversation?.conversation_id, bridge]);
  useEffect(() => {
    let alive = true, loading = false;
    async function refresh() {
      if (!alive || loading || document.hidden || !visible) return;
      loading = true;
      try { const value = await scopedBridge({ action: 'machine_list' }); if (alive) { setInventory(value); setError(''); } }
      catch (e) { if (alive) setError(e.message); } finally { loading = false; }
    }
    void refresh(); const timer = setInterval(refresh, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, [scopedBridge, visible]);
  const agent = inventory.agents.find(item => item.id === agentId);
  const terminal = inventory.terminals.find(item => item.id === agent?.terminal_id);
  return <aside ref={panelRef} className={'dot-computer-panel' + (expanded ? ' is-expanded' : '')} aria-label={'Computador de ' + dot.name}>
    <ComputerResizeHandle panelRef={panelRef} expanded={expanded} />
    <div className="dot-computer-window-actions"><button className="shell-icon" aria-label={expanded ? 'Recolher computador' : 'Ampliar computador'} aria-pressed={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button><button className="shell-icon" aria-label="Fechar computador" onClick={onClose}><X size={17} /></button></div>
    <header className="dot-computer-heading"><DotMascot mascot={dot.mascot} identity={dot.agent_id} name={dot.name} status={dot.status} execution={dot.execution} size="intro" decorative /><div className="dot-computer-identity"><strong>{dot.name}</strong><small>Seu computador</small></div></header>
    {error && <p className="shell-error" role="alert">{error}</p>}
    <div className="dot-computer-tabs" role="tablist" aria-label="Visões do computador">{[['desktop', 'Computador', Monitor], ...(!simple?[['terminal', 'Terminal', Terminal], ['files', 'Arquivos', Folder]]:[]), ...(tab === 'remote' ? [['remote', 'Remoto', Globe]] : [])].map(([id, label, Icon], index, tabs) => <button key={id} id={'dot-computer-tab-' + id} role="tab" tabIndex={tab === id ? 0 : -1} aria-selected={tab === id} aria-controls={'dot-computer-view-' + id} onClick={() => setTab(id)} onKeyDown={event => { const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null; if (next !== null) { event.preventDefault(); setTab(tabs[next][0]); event.currentTarget.parentElement.children[next].focus(); } }}><Icon size={14} />{label}</button>)}</div>
    <div className="dot-computer-view" id={'dot-computer-view-' + tab} role="tabpanel" aria-labelledby={'dot-computer-tab-' + tab}>
      {tab === 'desktop' && <ShellDotVm key={dot.dot_id + ':' + conversation?.conversation_id} dot={dot} conversation={conversation} bridge={bridge} visible={visible} simple={simple} onStatus={setMachine} onRemote={() => setTab('remote')} />}
      {tab === 'remote' && <ShellMachines key={dot.dot_id} compact bridge={scopedBridge} scope={{ project_id: dot.project_id, space_id: dot.space_id, dot_id: dot.dot_id }} visible={visible} onConfigure={onConfigure} />}
      {tab === 'terminal' && <section className="dot-computer-terminal"><select aria-label="Terminal deste canvas" value={agentId} onChange={e => setAgentId(e.target.value)}>{inventory.dots.map(item => <option key={item.agent_id} value={item.agent_id}>{item.name}</option>)}</select>{terminal?.status === 'running' ? <PtySlot ws={dot.project_id} resource={terminal} priority={30} /> : <div className="dot-computer-empty"><Terminal size={38} /><strong>Terminal encerrado</strong><p>Abra ou reabra o terminal deste agente no canvas.</p><button onClick={onCanvas}>Abrir canvas de agentes</button></div>}</section>}
      {tab === 'files' && <ComputerFiles key={dot.dot_id + ':' + (conversation?.conversation_id || 'canvas')} inventory={inventory} conversation={conversation} bridge={scopedBridge} onConfigure={onConfigure} />}
    </div>
    <details className="dot-computer-details"><summary>Detalhes do computador</summary><ComputerStatusStrip status={machine} /><p>{dot.model || 'Modelo não informado'}</p><button onClick={onConfigure}><Globe size={14} />Configurar navegador</button></details>
    <details className="shell-dot-family-fold">
      <summary>Família do Dot</summary>
      <DotFamilyControls dot={dot} bridge={bridge} projectId={dot.project_id} spaceId={dot.space_id} />
    </details>
  </aside>;
}
