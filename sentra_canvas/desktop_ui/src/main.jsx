import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ReactFlow, ReactFlowProvider, Background, BackgroundVariant, MiniMap, Panel,
  applyNodeChanges, applyEdgeChanges, useReactFlow, useViewport } from '@xyflow/react';
import * as Tooltip from '@radix-ui/react-tooltip';
import { MousePointer2, TerminalSquare, Bot, Users, StickyNote, Cable, Hand, Menu,
  Folder, Search, Plus, Minus, Layers, Map as MapIcon, Scan, Settings2, Activity,
  PanelRight, X, Copy, Monitor, Undo2, Redo2, RefreshCw, Workflow, ChevronDown, Globe } from 'lucide-react';
import { api, route } from './api';
import { TerminalPool } from './terminal-pool';
import { IconButton, ActionMenu, Modal } from './primitives';
import { DesktopContext } from './context';
import { nodeTypes, PtySlot } from './nodes';
import { EntryDialog, ConfirmDialog } from './dialogs';
import { openInspector } from './panels';
import { NetworkDialog } from './network-dialog';
import '@xyflow/react/dist/style.css';
import '@xterm/xterm/css/xterm.css';
import './desktop.css';

function WorkspaceDesktop() {
  const flow = useReactFlow(), viewport = useViewport();
  const [nodes, setNodes] = useState([]), [edges, setEdges] = useState([]);
  const [workspaces, setWorkspaces] = useState([]), [ws, setWS] = useState(null);
  const [filter, setFilter] = useState(''), [sidebar, setSidebar] = useState(true);
  const [tool, setTool] = useState('select'), [grid, setGrid] = useState(true), [map, setMap] = useState(false);
  const [phase, setPhase] = useState('loading'), [failure, setFailure] = useState('');
  const [integrations, setIntegrations] = useState([]), [models, setModels] = useState([]);
  const [inspector, setInspector] = useState(false), [entry, setEntry] = useState(null);
  const [confirmation, setConfirmation] = useState(null), [expanded, setExpanded] = useState(null);
  const [search, setSearch] = useState(false), [searchText, setSearchText] = useState('');
  const [network, setNetwork] = useState(false);
  const [toasts, setToasts] = useState([]), [, terminalChanged] = useState(0);
  const [nativeReady, setNativeReady] = useState(Boolean(window.pywebview?.api));
  const bridge = useRef({ ws: null, detail: null, nodes: [], links: [], x: 55, y: 55, scale: 1, move: null });
  const collaboration = useRef(null), actionsRef = useRef({}), requestSequence = useRef(0);
  const inspectorGeneration = useRef(0), noteTimers = useRef(new Map()), noteDrafts = useRef(new Map()), persisting = useRef(new Set());
  const activeNode = useRef(null), mounted = useRef(true), fetching = useRef(false);
  const entryRef = useRef(entry); entryRef.current = entry;
  const notify = useCallback((message, tone = 'info') => {
    if (!mounted.current) return;
    const id = crypto.randomUUID();
    setToasts(old => old.some(t => t.message === message) ? old : [{ id, message, tone }, ...old].slice(0, 4));
    setTimeout(() => { if (mounted.current) setToasts(old => old.filter(t => t.id !== id)); }, tone === 'error' ? 9000 : 4500);
  }, []);
  const poolRef = useRef(null);
  if (!poolRef.current) poolRef.current = new TerminalPool(notify, () => { if (mounted.current) terminalChanged(n => n + 1); });
  const pool = poolRef.current;
  function resourceData(graph) {
    const detail = bridge.current.detail || {};
    const lists = { terminal: 'terminals', agent: 'agents', team: 'teams' };
    const resource = detail[lists[graph.kind]]?.find(r => r.id === graph.resource_id);
    const terminal = graph.kind === 'terminal' ? resource :
      graph.kind === 'agent' ? detail.terminals?.find(t => t.id === resource?.terminal_id) : null;
    const owner = graph.kind === 'terminal' ? detail.agents?.find(a => a.terminal_id === graph.resource_id) : null;
    return { graph, resource, terminal, owner };
  }
  function projectGraph() {
    setNodes(previous => {
      const old = new Map(previous.map(n => [n.id, n]));
      return bridge.current.nodes.map(graph => ({
        ...old.get(graph.id), id: graph.id, type: 'session',
        position: { x: graph.x, y: graph.y }, style: { width: graph.width, height: graph.height },
        dragHandle: '.node-titlebar', data: resourceData(graph),
      }));
    });
    setEdges(previous => {
      const selected = new Set(previous.filter(e => e.selected).map(e => e.id));
      return bridge.current.links.map(link => ({ id: link.id, source: link.source, target: link.target,
        sourceHandle: 'output', targetHandle: 'input', type: 'default', selected: selected.has(link.id),
        className: 'desktop-cable', interactionWidth: 16, data: { link },
      }));
    });
  }
  function acceptGraph(info) {
    const previous = new Map(bridge.current.nodes.map(n => [n.id, n]));
    bridge.current.detail = info;
    bridge.current.nodes = info.nodes.map(n => {
      const local = previous.get(n.id);
      const draft = noteDrafts.current.get(bridge.current.ws + ':' + n.id);
      if (draft) n = { ...n, body: draft.body };
      if (local && (bridge.current.move || persisting.current.has(n.id))) {
        return { ...n, x: local.x, y: local.y, width: local.width, height: local.height };
      }
      return n;
    });
    bridge.current.links = info.links;
    pool.reconcile(bridge.current.ws, info.terminals || []);
    projectGraph();
  }
  async function refresh() {
    const currentWS = bridge.current.ws;
    if (!currentWS || fetching.current) return;
    fetching.current = true;
    try {
      const info = await api(route('/api/graph', { ws: currentWS }));
      if (bridge.current.ws === currentWS) { acceptGraph(info); setFailure(''); }
    } finally { fetching.current = false; }
  }
  async function chooseWorkspace(id) {
    if (id === bridge.current.ws && bridge.current.detail) return refresh();
    const sequence = ++requestSequence.current;
    try { await collaboration.current?.stop(); } catch (e) { notify(e.message, 'error'); }
    if (sequence !== requestSequence.current) return;
    await flushNotes();
    if (sequence !== requestSequence.current) return;
    bridge.current.ws = id; bridge.current.detail = null; bridge.current.nodes = []; bridge.current.links = [];
    pool.activeWorkspace = id; setWS(id); setNodes([]); setEdges([]); setExpanded(null);
    setInspector(false); inspectorGeneration.current++; setPhase('loading');
    activeNode.current = null;
    try {
      const [detail, graph] = await Promise.all([
        api(route('/api/workspace', { ws: id })), api(route('/api/graph', { ws: id })),
      ]);
      if (sequence !== requestSequence.current) return;
      acceptGraph({ ...detail, ...graph }); setPhase('ready'); setFailure('');
      const saved = sessionStorage.getItem('sentra_desktop_view:' + id);
      let camera;
      try { camera = JSON.parse(saved); } catch { /* optional local viewport preference */ }
      if (camera && ['x', 'y', 'zoom'].every(k => Number.isFinite(camera[k])) &&
        camera.zoom >= .2 && camera.zoom <= 2.5) flow.setViewport(camera);
      else if (graph.nodes.length) {
        requestAnimationFrame(() => flow.fitView({ padding: .28, minZoom: .4, maxZoom: .85 }));
      } else flow.setViewport({ x: 55, y: 55, zoom: 1 });
    } catch (e) {
      if (sequence === requestSequence.current) { setPhase('error'); setFailure(e.message); notify(e.message, 'error'); }
    }
  }
  async function loadWorkspaces(preferred) {
    try {
      const rows = await api('/api/workspaces');
      setWorkspaces(rows);
      const current = preferred || bridge.current.ws;
      if (rows.length) await chooseWorkspace(rows.some(w => w.id === current) ? current : rows[0].id);
      else { bridge.current.ws = null; setWS(null); setPhase('ready'); setFailure(''); }
    } catch (e) { setPhase('error'); setFailure(e.message); }
  }
  function requireWS() {
    if (!bridge.current.ws || !bridge.current.detail) throw Error('Selecione um workspace carregado.');
    return bridge.current.ws;
  }
  function guarded(fn) {
    return async (...args) => { try { return await fn(...args); } catch (e) { notify(e.message, 'error'); } };
  }
  function point() {
    const rect = document.getElementById('viewport').getBoundingClientRect();
    const p = flow.screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
    return { x: Math.round(p.x - 220), y: Math.round(p.y - 145) };
  }
  function open(kind, target = activeNode.current) {
    if (!['workspace', 'attach'].includes(kind)) requireWS();
    if (kind === 'team' && bridge.current.detail.agents.length < 2) throw Error('Crie um coordenador e pelo menos um trabalhador.');
    if (kind === 'task' && !bridge.current.detail.teams.length) throw Error('Crie uma equipe antes de delegar.');
    setEntry({ kind, target, point: point(), key: crypto.randomUUID() }); setTool('select');
  }
  async function showPanel(kind, target) {
    setInspector(true);
    document.getElementById('inspector').hidden = false;
    const generation = ++inspectorGeneration.current;
    const content = document.getElementById('inspector-content');
    content.replaceChildren();
    try { await openInspector(kind, { bridge, actions: actionsRef.current, notify, generation,
      isCurrent: value => value === inspectorGeneration.current, integrations, models }, target); }
    catch (e) {
      if (generation !== inspectorGeneration.current) return;
      const message = document.createElement('p'); message.className = 'center-empty'; message.textContent = e.message;
      content.replaceChildren(message); notify(e.message, 'error');
    }
  }
  function closeInspector() { inspectorGeneration.current++; setInspector(false); }
  function updateGeometry(id, values) {
    const n = bridge.current.nodes.find(n => n.id === id);
    if (n) Object.assign(n, values);
  }
  async function persistGeometry(id, size = false) {
    const currentWS = requireWS(), n = bridge.current.nodes.find(n => n.id === id);
    if (!n) return;
    persisting.current.add(id);
    try {
      if (!collaboration.current?.node(n)) {
        await api('/api/graph/move', { ws: currentWS, id, x: Math.round(n.x), y: Math.round(n.y) });
        if (size) await api('/api/graph/resize', { ws: currentWS, id, width: Math.round(n.width), height: Math.round(n.height) });
      }
    } catch (e) { notify(e.message, 'error'); }
    finally { persisting.current.delete(id); bridge.current.move = null; await guarded(refresh)(); }
  }
  function editing(id) { bridge.current.move = { n: bridge.current.nodes.find(n => n.id === id) }; }
  async function resized(id, params) {
    updateGeometry(id, { x: params.x, y: params.y, width: params.width, height: params.height });
    await persistGeometry(id, true);
  }
  function saveNote(id, body, immediate = false) {
    const currentWS = bridge.current.ws;
    const old = noteTimers.current.get(id); if (old) clearTimeout(old.timer);
    updateGeometry(id, { body });
    const send = async () => {
      noteTimers.current.delete(id);
      try {
        await api('/api/graph/note/update', { ws: currentWS, id, body });
        const key = currentWS + ':' + id;
        if (noteDrafts.current.get(key)?.body === body) noteDrafts.current.delete(key);
        return true;
      } catch (e) { notify(e.message, 'error'); return false; }
    };
    noteDrafts.current.set(currentWS + ':' + id, { body, send });
    noteTimers.current.set(id, { timer: setTimeout(send, immediate ? 0 : 450), send });
  }
  async function flushNotes() {
    const pending = [...noteTimers.current.values()];
    for (const item of pending) clearTimeout(item.timer);
    const results = await Promise.all([...noteDrafts.current.values()].map(item => item.send()));
    if (results.some(value => !value)) throw Error('Há notas com envio não confirmado. O rascunho permanece nesta janela; tente salvar antes de sair.');
  }
  function remove(id) {
    const currentWS = requireWS(), n = bridge.current.nodes.find(n => n.id === id);
    if (!n) return;
    if (!['terminal', 'note'].includes(n.kind)) { notify('Gerencie este recurso pela Central do workspace.'); return; }
    setConfirmation({ title: n.kind === 'terminal' ? 'Encerrar ' + n.title + '?' : 'Excluir nota?',
      description: n.kind === 'terminal' ? 'O processo do terminal será encerrado. O histórico preservado permanece consultável.' : 'A nota será removida do canvas.',
      run: async () => {
        await api(n.kind === 'terminal' ? '/api/terminal/close' : '/api/graph/note/delete',
          { ws: currentWS, id: n.kind === 'terminal' ? n.resource_id : n.id, confirm: true });
        await refresh();
      } });
  }
  function removeEdge(edge) {
    const currentWS = requireWS();
    setConfirmation({ title: 'Remover conexão?', description: 'Remove apenas o vínculo dirigido entre os nós.',
      run: async () => { await api('/api/graph/unlink', { ws: currentWS, id: edge.id }); await refresh(); } });
  }
  async function restart(id) {
    await api('/api/agent/restart', { ws: requireWS(), id }); await refresh();
  }
  function focusNode(id) {
    const n = bridge.current.nodes.find(n => n.id === id);
    if (!n) return;
    activeNode.current = id; setNodes(old => old.map(node => ({ ...node, selected: node.id === id })));
    flow.setCenter(n.x + n.width / 2, n.y + n.height / 2, { zoom: Math.max(viewport.zoom, .85), duration: 150 });
  }
  actionsRef.current = { open: guarded(open), refresh, loadWorkspaces, inspect: id => guarded(showPanel)('node', id),
    remove, editing, resized: guarded(resized), saveNote, expand: id => setExpanded(id),
    restart: guarded(restart), focusResource: id => {
      const n = bridge.current.nodes.find(n => n.resource_id === id); if (n) focusNode(n.id);
    } };
  useEffect(() => {
    mounted.current = true;
    loadWorkspaces();
    Promise.allSettled([api('/api/integrations'), api('/api/models')]).then(results => {
      if (!mounted.current) return;
      if (results[0].status === 'fulfilled') setIntegrations(results[0].value);
      if (results[1].status === 'fulfilled') setModels(results[1].value.models || []);
    });
    const timer = setInterval(() => {
      if (!document.hidden && !bridge.current.move && !entryRef.current && !persisting.current.size) guarded(refresh)();
    }, 2500);
    const native = () => setNativeReady(Boolean(window.pywebview?.api));
    window.addEventListener('pywebviewready', native);
    const shutdown = () => pool.destroy();
    window.addEventListener('beforeunload', shutdown);
    return () => { mounted.current = false; clearInterval(timer); window.removeEventListener('pywebviewready', native);
      window.removeEventListener('beforeunload', shutdown); pool.destroy(); };
  }, []);
  useEffect(() => {
    const controller = window.SentraCollaborationPanel;
    if (!controller) return;
    collaboration.current = controller.create({
      api, state: bridge.current, toast: notify,
      drawEdges: () => projectGraph(), refreshResources: refresh,
    });
    return () => { collaboration.current?.stop().catch(() => {}); };
  }, []);
  useEffect(() => {
    Object.assign(bridge.current, { x: viewport.x, y: viewport.y, scale: viewport.zoom });
  }, [viewport.x, viewport.y, viewport.zoom]);
  useEffect(() => {
    function keydown(e) {
      if (e.target.closest('input,textarea,select,[contenteditable],.xterm,[role=dialog]') || entry || confirmation || expanded || network) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setSearchText(''); setSearch(true); return; }
      if (search) return;
      const keys = { t: 'terminal', a: 'agent', e: 'team', n: 'note' };
      if (keys[e.key.toLowerCase()]) { e.preventDefault(); actionsRef.current.open(keys[e.key.toLowerCase()]); }
      if (e.key.toLowerCase() === 'v') setTool('select');
      if (e.key.toLowerCase() === 'l') setTool('link');
      if (e.key === 'Escape') { setTool('select'); closeInspector(); }
      if (e.key === 'Delete') {
        const edge = flow.getEdges().find(edge => edge.selected);
        if (edge) guarded(removeEdge)(edge); else if (activeNode.current) guarded(remove)(activeNode.current);
      }
    }
    document.addEventListener('keydown', keydown); return () => document.removeEventListener('keydown', keydown);
  }, [entry, confirmation, expanded, search, network]);
  const current = workspaces.find(w => w.id === ws);
  const expandedGraph = bridge.current.nodes.find(n => n.id === expanded);
  const expandedResource = expandedGraph && resourceData(expandedGraph).terminal;
  const context = { bridge, ws, pool, collaboration, actions: actionsRef.current, notify, integrations, models };
  const toolbar = [
    ['select', 'Selecionar (V)', MousePointer2, () => setTool('select')],
    ['terminal', 'Novo terminal (T)', TerminalSquare, () => actionsRef.current.open('terminal')],
    ['agent', 'Novo agente (A)', Bot, () => actionsRef.current.open('agent')],
    ['team', 'Nova equipe (E)', Users, () => actionsRef.current.open('team')],
    ['note', 'Nova nota (N)', StickyNote, () => actionsRef.current.open('note')],
    ['link', 'Conectar nós (L)', Cable, () => setTool('link')],
    ['pan', 'Mover canvas', Hand, () => setTool('pan')],
  ];
  return <DesktopContext.Provider value={context}><Tooltip.Provider delayDuration={380}>
    <div id="app" className={'desktop-shell ' + (!sidebar ? 'sidebar-closed' : '')}>
      <aside className="workspace-sidebar" hidden={!sidebar}>
        <div className="workspace-filter"><Search size={13} /><input value={filter} onChange={e => setFilter(e.target.value)}
          aria-label="Filtrar workspaces" placeholder="Filtrar" /><IconButton label="Novo workspace" onClick={() => actionsRef.current.open('workspace')}><Plus size={17} /></IconButton></div>
        <div className="sidebar-label">WORKSPACES</div>
        <nav className="workspace-list" aria-label="Workspaces">
          {workspaces.filter(w => w.name.toLowerCase().includes(filter.toLowerCase())).map(w =>
            <button key={w.id} className={'workspace-item ' + (w.id === ws ? 'selected' : '')}
              onClick={() => guarded(chooseWorkspace)(w.id)}><TerminalSquare size={13} className="workspace-symbol" />
              <span>{w.name}</span>{w.id === ws && <small><TerminalSquare size={12} />{bridge.current.detail?.terminals?.length ?? '…'}</small>}</button>)}
          {phase === 'loading' && !workspaces.length && <p className="sidebar-empty">Carregando…</p>}
          {phase === 'ready' && !workspaces.length && <p className="sidebar-empty">Crie ou adicione um workspace.</p>}
        </nav>
        <div className="sidebar-footer"><button onClick={() => actionsRef.current.open('attach')}><Folder size={12} /> Adicionar pasta</button>
          <IconButton label="Rede · Hamachi / Radmin" onClick={() => guarded(() => { requireWS(); setNetwork(true); })()}><Globe size={14} /></IconButton>
          <IconButton label="Central do workspace" onClick={() => guarded(showPanel)('center')}><Workflow size={13} /></IconButton>
          <IconButton label="Ambientes e modelos" onClick={() => guarded(showPanel)('registry')}><Settings2 size={13} /></IconButton></div>
      </aside>
      <main className="desktop-canvas" id="viewport" onPointerMove={e => {
        const rect = e.currentTarget.getBoundingClientRect();
        collaboration.current?.presence({ x: (e.clientX - rect.left - viewport.x) / viewport.zoom,
          y: (e.clientY - rect.top - viewport.y) / viewport.zoom });
      }}>
        <div className="window-drag pywebview-drag-region" aria-hidden="true" />
        <div className="window-controls">
          <button disabled={!nativeReady} aria-label="Minimizar" onClick={() => guarded(() => window.pywebview.api.minimize())()}><Minus size={12} /></button>
          <button disabled={!nativeReady} aria-label="Restaurar ou maximizar" onClick={() => guarded(() => window.pywebview.api.toggle_maximize())()}><Copy size={11} /></button>
          <button disabled={!nativeReady} className="window-close" aria-label="Fechar SENTRA" onClick={() => guarded(async () => { await flushNotes(); await window.pywebview.api.close(); })()}><X size={14} /></button>
        </div>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} colorMode="dark" onlyRenderVisibleElements={false}
          minZoom={.2} maxZoom={2.5} defaultViewport={{ x: 55, y: 55, zoom: 1 }}
          nodesDraggable={tool !== 'pan' && tool !== 'link'} panOnDrag connectOnClick deleteKeyCode={null}
          nodesConnectable={tool !== 'pan'} zoomOnDoubleClick={false}
          onNodesChange={changes => {
            setNodes(old => applyNodeChanges(changes, old));
            for (const c of changes) {
              if (c.type === 'position' && c.position) updateGeometry(c.id, { x: c.position.x, y: c.position.y });
              if (c.type === 'dimensions' && c.resizing && c.dimensions) updateGeometry(c.id, { width: c.dimensions.width, height: c.dimensions.height });
            }
          }}
          onEdgesChange={changes => setEdges(old => applyEdgeChanges(changes, old))}
          onNodeClick={(_, node) => { activeNode.current = node.id; }}
          onNodeDragStart={(_, node) => editing(node.id)}
          onNodeDragStop={(_, node, selection) => {
            const moved = selection?.length ? selection : [node];
            for (const n of moved) updateGeometry(n.id, { x: n.position.x, y: n.position.y });
            guarded(async () => { for (const n of moved) await persistGeometry(n.id); })();
          }}
          onNodeDoubleClick={(_, node) => { const d = resourceData(node.data.graph); if (d.terminal && !d.owner) setExpanded(node.id); }}
          onConnect={guarded(async connection => {
            if (connection.source === connection.target) throw Error('Escolha outro nó como destino.');
            await api('/api/graph/link', { ws: requireWS(), source: connection.source, target: connection.target });
            await refresh(); setTool('select');
          })}
          onEdgeDoubleClick={(_, edge) => guarded(removeEdge)(edge)}
          onMoveEnd={(_, camera) => { if (bridge.current.ws) sessionStorage.setItem('sentra_desktop_view:' + bridge.current.ws, JSON.stringify(camera)); }}
          onPaneClick={() => { activeNode.current = null; }}
          ariaLabelConfig={{ 'node.a11yDescription.default': 'Use as setas para mover. Enter seleciona. Detalhes disponíveis no menu do nó.',
            'controls.zoomIn.ariaLabel': 'Aumentar zoom', 'controls.zoomOut.ariaLabel': 'Diminuir zoom' }}>
          {grid && <><Background id="fine" variant={BackgroundVariant.Lines} gap={16} color="#303034" lineWidth={.5} />
            <Background id="major" variant={BackgroundVariant.Lines} gap={80} color="#37373b" lineWidth={.5} /></>}
          <Panel position="top-left" className="sidebar-toggle-panel">
            <IconButton label={sidebar ? 'Recolher sidebar' : 'Mostrar sidebar'} onClick={() => setSidebar(v => !v)}><Menu size={16} /></IconButton>
          </Panel>
          <Panel position="top-center" className="floating-tools">
            {toolbar.map(([id, label, Icon, fn]) => <IconButton key={id} label={label} aria-pressed={tool === id}
              className={tool === id ? 'active' : ''} onClick={fn}><Icon size={16} strokeWidth={1.65} /></IconButton>)}
            <span className="tool-divider" />
            <ActionMenu label="Mais ferramentas" trigger={<button className="icon-button" aria-label="Mais ferramentas"><ChevronDown size={15} /></button>}
              items={[
                { label: 'Máquinas, documentos e sessões remotas', icon: <Monitor size={14} />, action: () => guarded(showPanel)('machines') },
                { label: 'Central do workspace', icon: <Workflow size={14} />, action: () => guarded(showPanel)('center') },
                { label: 'Rede · Hamachi / Radmin', icon: <Globe size={14} />, action: () => guarded(() => { requireWS(); setNetwork(true); })() },
                { label: 'Atividade', icon: <Activity size={14} />, action: () => guarded(showPanel)('activity') },
                { label: 'Buscar nós e comandos', icon: <Search size={14} />, action: () => { setSearchText(''); setSearch(true); } },
                { label: 'Atualizar workspace', icon: <RefreshCw size={14} />, action: () => guarded(refresh)() },
              ]} />
          </Panel>
          <Panel position="top-right" className="utility-tools">
            <IconButton label="Atividade" onClick={() => guarded(showPanel)('activity')}><Activity size={14} /></IconButton>
            <IconButton label="Máquinas e documentos" onClick={() => guarded(showPanel)('machines')}><Monitor size={14} /></IconButton>
          </Panel>
          {map && <MiniMap position="bottom-right" pannable zoomable nodeColor="#626269" maskColor="#1c1c1c99" className="desktop-minimap" />}
          <Panel position="bottom-right" className="viewport-controls">
            <ActionMenu label="Camadas e colaboração" trigger={<button className="round-control" aria-label="Camadas e colaboração"><Layers size={15} /></button>}
              items={[
                { label: grid ? 'Ocultar grid' : 'Mostrar grid', action: () => setGrid(v => !v) },
                { label: map ? 'Ocultar minimapa' : 'Mostrar minimapa', action: () => setMap(v => !v) },
                { label: 'Detalhes do nó selecionado', icon: <PanelRight size={14} />, action: () => guarded(showPanel)('node', activeNode.current) },
                { separator: true },
                { label: 'Ativar / desativar colaboração', action: () => guarded(async () => { await flushNotes(); if (!collaboration.current) throw Error('Runtime de colaboração indisponível.'); await collaboration.current.toggle(); })() },
                { label: 'Desfazer edição colaborativa', icon: <Undo2 size={14} />, action: () => guarded(() => collaboration.current?.undo())() },
                { label: 'Refazer edição colaborativa', icon: <Redo2 size={14} />, action: () => guarded(() => collaboration.current?.redo())() },
              ]} />
            <IconButton label="Enquadrar nós" className="round-control" onClick={() => flow.fitView({ padding: .25, maxZoom: 1 })}><Scan size={15} /></IconButton>
            <IconButton label="Mostrar / ocultar minimapa" className="round-control" aria-pressed={map} onClick={() => setMap(v => !v)}><MapIcon size={15} /></IconButton>
            <div className="zoom-capsule"><IconButton label="Diminuir zoom" onClick={() => flow.zoomOut()}><Minus size={14} /></IconButton>
              <button className="zoom-value" title="Zoom de 100%" onClick={() => flow.zoomTo(1)}>{Math.round(viewport.zoom * 100)}%</button>
              <IconButton label="Aumentar zoom" onClick={() => flow.zoomIn()}><Plus size={14} /></IconButton></div>
          </Panel>
        </ReactFlow>
        {phase === 'ready' && !nodes.length && <div className="canvas-empty">
          <TerminalSquare size={23} strokeWidth={1.2} /><p>{ws ? 'Abra um terminal para começar.' : 'Crie ou adicione um workspace.'}</p>
          <button onClick={() => actionsRef.current.open(ws ? 'terminal' : 'workspace')}>{ws ? 'Novo terminal' : 'Novo workspace'}</button>
        </div>}
        {(failure || phase === 'loading') && <div className={'connection-banner ' + (failure ? 'error' : '')} role="status">
          <span>{failure || 'Consultando workspace…'}</span>{failure && <button onClick={() => loadWorkspaces()}>Consultar novamente</button>}
        </div>}
        <div className="workspace-caption">{current?.name || 'SENTRA'}{ws && <span> · {nodes.length} nós</span>}</div>
        <button id="show-collaboration" hidden aria-pressed="false" type="button" />
      </main>
      <aside id="inspector" className="desktop-inspector" hidden={!inspector}>
        <header className="inspector-heading"><div><small id="inspector-label">WORKSPACE</small><h2 id="inspector-title">Detalhes</h2></div>
          <IconButton label="Fechar inspector" onClick={closeInspector}><X size={17} /></IconButton></header>
        <div id="inspector-tabs" hidden /><div id="inspector-content" />
      </aside>
    </div>
    {entry && <EntryDialog key={entry.key} request={entry} close={() => setEntry(null)} />}
    {network && <NetworkDialog close={() => setNetwork(false)} />}
    {confirmation && <ConfirmDialog request={confirmation} close={() => setConfirmation(null)} />}
    {expandedResource && <Modal open onOpenChange={v => { if (!v) setExpanded(null); }} title={expandedGraph.title}
      description={expandedResource.shell + ' · mesma sessão PTY'} className="expanded-terminal"
      onOpenAutoFocus={e => { e.preventDefault(); requestAnimationFrame(() => pool.focus(ws, expandedResource.id)); }}>
      <PtySlot ws={ws} resource={expandedResource} priority={100} />
    </Modal>}
    <Modal open={search} onOpenChange={setSearch} title="Buscar" description="Nós e comandos do workspace." className="command-dialog">
      <input className="command-input" aria-label="Buscar nós e comandos" value={searchText} onChange={e => setSearchText(e.target.value)} placeholder="Nome da sessão ou ação…" />
      <div className="command-results">
        {bridge.current.nodes.filter(n => n.title.toLowerCase().includes(searchText.toLowerCase())).map(n =>
          <button key={n.id} onClick={() => { setSearch(false); focusNode(n.id); }}>{n.title}<small>{n.kind}</small></button>)}
        {toolbar.filter(([id, label]) => !['select', 'pan', 'link'].includes(id) && label.toLowerCase().includes(searchText.toLowerCase())).map(([id, label, Icon, fn]) =>
          <button key={id} onClick={() => { setSearch(false); fn(); }}><Icon size={15} />{label}</button>)}
      </div>
    </Modal>
    <div className="desktop-toasts" aria-live="polite">{toasts.map(t => <div key={t.id} className={'desktop-toast ' + t.tone}>
      <span>{t.message}</span><button aria-label="Dispensar aviso" onClick={() => setToasts(old => old.filter(x => x.id !== t.id))}><X size={14} /></button>
    </div>)}</div>
  </Tooltip.Provider></DesktopContext.Provider>;
}

class DesktopBoundary extends React.Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) return <section className="desktop-load-error"><strong>O desktop não pôde ser renderizado</strong>
      <p>{String(this.state.error.message || 'Erro nos componentes locais.').replace(/(?:Bearer\s+|token=)[^\s&#]+/gi, '[credencial omitida]').slice(0, 400)}</p>
      <button onClick={() => location.reload()}>Recarregar a superfície</button></section>;
    return this.props.children;
  }
}
function start() {
  createRoot(document.getElementById('desktop-root')).render(<DesktopBoundary><ReactFlowProvider><WorkspaceDesktop /></ReactFlowProvider></DesktopBoundary>);
}
// Classic compatibility panel scripts are defer scripts; mount after all are ready.
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
else start();
