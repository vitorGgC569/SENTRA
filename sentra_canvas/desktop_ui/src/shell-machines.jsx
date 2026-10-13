import React, { useEffect, useRef, useState } from 'react';
import { Monitor, RefreshCw, Shield, Settings2, X } from 'lucide-react';
import { liveViewer, offlineRecording } from '../../../sentra_executors/remote_guacamole_viewer.js';
import { OperationReceipt, Status } from './shell-receipts';

export function ShellMachines({ bridge, scope, onConfigure, visible = true, compact = false }) {
  const intentKey = 'sentra_shell_machine_intent:' + scope.project_id + ':' + scope.space_id + ':' + (scope.dot_id || 'project');
  const initial = useRef(null);
  if (!initial.current) {
    try { initial.current = { request: JSON.parse(sessionStorage.getItem(intentKey)) }; } catch { initial.current = { request: null }; }
  }
  const [inventory, setInventory] = useState({ machines: [], work_items: [] }), [machineId, setMachineId] = useState(initial.current.request?.machine_id || '');
  const [workItemId, setWorkItemId] = useState(initial.current.request?.work_item_id || ''), [capabilityId, setCapabilityId] = useState(initial.current.request?.capability_id || ''), [sessionId, setSessionId] = useState(initial.current.request?.session_id || '');
  const [input, setInput] = useState(null), [viewer, setViewer] = useState(null), [mode, setMode] = useState('view');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [receipt, setReceipt] = useState(null), [ttl, setTTL] = useState(60);
  const [pending, setPending] = useState(initial.current.request), [connection, setConnection] = useState('idle'), [operation, setOperation] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [settings, setSettings] = useState(false);
  const [agentArguments, setAgentArguments] = useState('');
  const [recording, setRecording] = useState(null), [position, setPosition] = useState(0);
  const container = useRef(null), live = useRef(null), keyboard = useRef(null), mouse = useRef(null), deadline = useRef(null);
  const viewerRef = useRef(null), inputRef = useRef(null), inputDeadline = useRef(0), alive = useRef(true), locked = useRef(false);
  const pendingRef = useRef(initial.current.request), closeIntent = useRef(initial.current.request?.action === 'remote_viewer_close' ? initial.current.request : null), mouseTimer = useRef(null), bridgeRef = useRef(bridge);
  const selectionRef = useRef(null), visibleRef = useRef(visible); visibleRef.current = visible;
  const recordingContainer = useRef(null), playback = useRef(null);
  bridgeRef.current = bridge;
  const machine = inventory.machines.find(item => item.machine_id === machineId);
  const workItems = inventory.work_items.filter(item => item.machine_id === machineId);
  const work = workItems.find(item => item.work_item_id === workItemId);
  const capabilities = (machine?.capabilities || []).filter(id => !work?.capabilities?.length || work.capabilities.includes(id));
  const selected = { ...scope, machine_id: machineId, ...(workItemId ? { work_item_id: workItemId } : {}), ...(capabilityId ? { capability_id: capabilityId } : {}) };
  useEffect(() => {
    if (!compact || viewer || pending || busy) return;
    const remote = inventory.machines.filter(item => item.kind === 'guacamole');
    if (!machineId && remote.length === 1) setMachineId(remote[0].machine_id);
    if (machineId && !workItemId && workItems.length === 1) setWorkItemId(workItems[0].work_item_id);
    if (workItemId && !capabilityId && capabilities.length === 1) setCapabilityId(capabilities[0]);
  }, [compact, inventory, machineId, workItemId, capabilityId, viewer, pending, busy]);
  selectionRef.current = selected;
  function rememberIntent(request) {
    pendingRef.current = request;
    if (alive.current) setPending(request);
    try { if (request) sessionStorage.setItem(intentKey, JSON.stringify(request)); else sessionStorage.removeItem(intentKey); } catch { /* Memory retains the current intent; never store a viewer URL. */ }
  }
  function canInput(channel) {
    const ticket = viewerRef.current, status = inputRef.current;
    return visibleRef.current && ticket?.control_mode === 'human' && ticket.input_channels?.includes(channel) &&
      status?.holder === 'human' && status.live === true && status.grant_status === 'granted' &&
      status.epoch === ticket.input_epoch && Date.now() < inputDeadline.current;
  }
  function detach() {
    clearTimeout(deadline.current); clearTimeout(mouseTimer.current);
    if (keyboard.current) { keyboard.current.onkeydown = null; keyboard.current.onkeyup = null; keyboard.current.reset(); }
    if (mouse.current) { mouse.current.onmousedown = null; mouse.current.onmouseup = null; mouse.current.onmousemove = null; }
    keyboard.current = null; mouse.current = null;
    live.current?.close(); live.current = null;
    if (container.current) container.current.replaceChildren();
  }
  async function closeViewer() {
    const value = viewerRef.current;
    detach(); if (alive.current) setConnection('closed');
    if (!value) return true;
    const request = closeIntent.current || { action: 'remote_viewer_close', ...scope, viewer_id: value.viewer_id, request_key: crypto.randomUUID() };
    closeIntent.current = request;
    try {
      const result = await bridgeRef.current(request);
      if (result.closed !== true) throw Error('O encerramento do viewer ainda não foi confirmado.');
      viewerRef.current = null; closeIntent.current = null;
      if (!pendingRef.current || pendingRef.current.request_key === request.request_key) rememberIntent(null);
      if (alive.current) { setViewer(null); setReceipt(result); }
      return true;
    } catch (e) { rememberIntent(request); if (alive.current) setError(e.message); return false; }
  }
  async function loadMachines() {
    try {
      const value = await bridgeRef.current({ action: 'machine_list', ...scope });
      if (alive.current) { setInventory({ machines: value.machines || [], work_items: value.work_items || [] }); setError(''); }
    } catch (e) { if (alive.current) setError(e.message); }
  }
  async function readInput() {
    if (!machineId) return;
    try {
      const value = await bridgeRef.current({ action: 'input_status', ...selected });
      if (!alive.current || (value.machine_id && value.machine_id !== selectionRef.current.machine_id) || machineId !== selectionRef.current.machine_id || workItemId !== (selectionRef.current.work_item_id || '') || capabilityId !== (selectionRef.current.capability_id || '')) return;
      inputRef.current = value; setInput(value);
      const remaining = Number(value.ttl_remaining_seconds || 0);
      inputDeadline.current = Date.now() + Math.max(0, remaining) * 1000;
      if (viewerRef.current?.control_mode === 'human' && (!value.live || value.holder !== 'human' || value.grant_status !== 'granted' || value.epoch !== viewerRef.current.input_epoch)) {
        await closeViewer();
      }
    } catch (e) {
      inputRef.current = null; inputDeadline.current = 0;
      if (alive.current) setError(e.message);
      if (viewerRef.current?.control_mode === 'human') await closeViewer();
    }
  }
  useEffect(() => {
    alive.current = true; void loadMachines();
    return () => { alive.current = false; playback.current?.pause(); void closeViewer(); };
  }, [scope.project_id, scope.space_id, scope.dot_id]);
  useEffect(() => { if (!visible && viewerRef.current) void closeViewer(); }, [visible]);
  useEffect(() => {
    inputRef.current = null; setInput(null); inputDeadline.current = 0;
    if (!machineId) return;
    let fetching = false;
    const observe = async () => { if (fetching || document.hidden) return; fetching = true; try { await readInput(); } finally { fetching = false; } };
    void observe(); const timer = setInterval(observe, 2000);
    return () => clearInterval(timer);
  }, [machineId, workItemId, capabilityId]);
  async function handoff(holder) {
    if (locked.current || !inputRef.current) return;
    locked.current = true; setBusy(true); setError('');
    try {
      let argumentsValue;
      if (holder === 'agent') {
        argumentsValue = JSON.parse(agentArguments);
        if (!argumentsValue || Array.isArray(argumentsValue) || typeof argumentsValue !== 'object' || !(machine.actions?.[capabilityId] || []).includes(argumentsValue.action)) throw Error('Informe uma intenção JSON com uma ação anunciada pela capacidade escolhida.');
      }
      const request = { action: 'input_handoff', ...selected, holder, expected_epoch: inputRef.current.epoch,
        ttl_seconds: Number(ttl), request_key: crypto.randomUUID(), ...(argumentsValue ? { arguments: argumentsValue } : {}) };
      rememberIntent(request);
      if (keyboard.current) keyboard.current.reset();
      const result = await bridgeRef.current(request); setReceipt(result);
      rememberIntent(null); await readInput(); return true;
    } catch (e) { setError(e.message); if (!e.uncertain) rememberIntent(null); return false; }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function mountViewer(result) {
    if (!result.viewer_id || !result.ws_url || result.grant_status !== 'granted') throw Error('O servidor não concedeu um ticket de visualização.');
    const url = new URL(result.ws_url);
    if (!['ws:', 'wss:'].includes(url.protocol) || ![location.hostname, '127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) throw Error('O viewer retornou um transporte fora do host autorizado.');
    const module = await import('guacamole-common-js');
    const Guacamole = module.default?.Client ? module.default : module.default?.default || module.Guacamole || module;
    if (!Guacamole.Client || !Guacamole.WebSocketTunnel) throw Error('Biblioteca Guacamole pinada indisponível nesta superfície.');
    const { ws_url: ticketURL, ...publicValue } = result;
    viewerRef.current = publicValue; closeIntent.current = null;
    if (!alive.current) { await closeViewer(); return; }
    setViewer(publicValue); setConnection('connecting');
    const mounted = liveViewer(Guacamole, ticketURL, container.current); live.current = mounted;
    mounted.tunnel.onerror = () => { if (alive.current) { setError('A conexão do viewer foi interrompida. Consulte a autorização antes de abrir outra conexão.'); setConnection('interrupted'); } };
    mounted.client.onerror = () => { if (alive.current) { setError('O desktop remoto retornou erro ou perdeu autorização.'); setConnection('interrupted'); } };
    mounted.client.onstatechange = state => { if (alive.current) setConnection(state === 3 ? 'connected' : state === 5 ? 'closed' : 'connecting'); };
    if (result.control_mode === 'human') {
      const element = mounted.client.getDisplay().getElement(); element.tabIndex = 0;
      const keys = new Guacamole.Keyboard(element); keyboard.current = keys;
      keys.onkeydown = keysym => { if (!canInput('key')) return true; mounted.client.sendKeyEvent(1, keysym); return false; };
      keys.onkeyup = keysym => { if (canInput('key')) mounted.client.sendKeyEvent(0, keysym); };
      const pointer = new Guacamole.Mouse(mounted.client.getDisplay().getElement()); mouse.current = pointer;
      const sendPointer = state => { if (canInput('mouse')) mounted.client.sendMouseState(state, true); };
      pointer.onmousedown = state => { element.focus({ preventScroll: true }); sendPointer(state); };
      pointer.onmouseup = sendPointer;
      pointer.onmousemove = state => { clearTimeout(mouseTimer.current); mouseTimer.current = setTimeout(() => sendPointer(state), 40); };
      if (result.input_channels.includes('touch') && Guacamole.Touch && mounted.client.sendTouchState) {
        const touch = new Guacamole.Touch(element);
        touch.onEach(['touchstart', 'touchmove', 'touchend'], event => {
          if (!canInput('touch')) return;
          mounted.client.sendTouchState(event.state, true); event.preventDefault();
        });
      }
    }
    const seconds = Math.min(300, Number(result.max_connection_seconds || 300));
    deadline.current = setTimeout(() => { void closeViewer(); }, seconds * 1000);
  }
  async function openViewer(requestedMode) {
    if (locked.current || viewerRef.current || pendingRef.current) return;
    locked.current = true; setBusy(true); setError('');
    const viewerMode = ['view', 'human'].includes(requestedMode) ? requestedMode : mode;
    const request = { action: 'remote_viewer_open', ...selected, session_id: sessionId, control_mode: viewerMode,
      ...(viewerMode === 'human' ? { expected_epoch: inputRef.current?.epoch } : {}), request_key: crypto.randomUUID() };
    rememberIntent(request);
    try {
      const result = await bridgeRef.current(request); setReceipt(result);
      if (result.status === 'uncertain') { setError(result.reason || 'A sessão ainda não foi confirmada. Consulte a mesma intenção.'); setOperation(result.operation_id || null); return; }
      await mountViewer(result);
      rememberIntent(null);
    } catch (e) { setError(e.message); if (!e.uncertain) { rememberIntent(null); if (viewerRef.current) await closeViewer(); } }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function reconcile() {
    if (!pendingRef.current || locked.current) return;
    locked.current = true; setBusy(true); setError('');
    const request = pendingRef.current;
    try {
      const result = await bridgeRef.current(request); setReceipt(result);
      if (result.status === 'uncertain' || result.state === 'UNCERTAIN') { setError('O resultado permanece incerto. Observe a operação antes de repetir.'); setOperation(result.operation_id || null); return; }
      if (request.action === 'remote_viewer_open') await mountViewer(result);
      else if (request.action === 'input_handoff') await readInput();
      else if (request.action === 'remote_viewer_close') { viewerRef.current = null; closeIntent.current = null; setViewer(null); }
      else if (request.action === 'machine_execute') acceptMachineResult(result);
      rememberIntent(null);
    } catch (e) { setError(e.message); }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function observeOperation() {
    if (!operation) return;
    try { const result = await bridgeRef.current({ action: 'machine_observe', ...scope, target_operation_id: operation }); setReceipt(result); }
    catch (e) { setError(e.message); }
  }
  function acceptMachineResult(result) {
    if (result.state !== 'SUCCEEDED') return;
    const value = result.evidence?.payload || result.evidence || {};
    if (Array.isArray(value.sessions)) setSessions(value.sessions);
    if (value.session_id) { setSessionId(value.session_id); setSessions(old => old.some(item => (item.id || item.session_id) === value.session_id) ? old : [...old, { id: value.session_id, state: value.state || 'Consulta necessária' }]); }
  }
  async function sessionAction(action) {
    if (locked.current || pendingRef.current) return;
    locked.current = true; setBusy(true); setError('');
    const request = { action: 'machine_execute', ...selected, request_key: crypto.randomUUID(), arguments: { action,
      ...(['status', 'recording.read'].includes(action) ? { session_id: sessionId } : {}) } };
    rememberIntent(request);
    try {
      const result = await bridgeRef.current(request); setReceipt(result); setOperation(result.operation_id || null);
      if (result.state === 'UNCERTAIN' || result.status === 'uncertain') { setError('Operação ainda incerta. Consulte a mesma intenção; nenhuma sessão será aberta novamente.'); return; }
      acceptMachineResult(result); rememberIntent(null);
    } catch (e) { setError(e.message); if (!e.uncertain) rememberIntent(null); }
    finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function loadRecording(file) {
    if (!file) return;
    try {
      if (file.size > 4 * 1024 * 1024) throw Error('A gravação deve ter até 4 MiB neste viewer.');
      const document = JSON.parse(await file.text());
      if (!Array.isArray(document.events) || document.events.length > 20000) throw Error('A gravação excede o limite de eventos.');
      const module = await import('guacamole-common-js');
      const Guacamole = module.default?.Client ? module.default : module.default?.default || module.Guacamole || module;
      playback.current?.pause();
      playback.current = offlineRecording(Guacamole, document, recordingContainer.current);
      setRecording({ name: file.name, completeness_asserted: document.completeness_asserted === true }); setPosition(0);
    } catch (e) { setError(e.message); }
  }
  if (compact) {
    const desktops = inventory.machines.filter(item => item.kind === 'guacamole');
    const otherRemote = inventory.machines.filter(item => ['daytona', 'rustdesk'].includes(item.kind));
    const actions = machine?.actions?.[capabilityId] || [];
    const ready = Boolean(machine?.kind === 'guacamole' && workItemId && capabilityId && sessionId);
    return <section className="dot-computer-remote" aria-label="Computador do canvas do Dot">
      <header><span><Monitor size={15} />{machine?.name || 'Desktop'}</span><small role="status">{connection === 'connected' ? (viewer?.control_mode === 'human' ? 'Você controla' : 'Conectado · observando') : viewer ? 'Conectando…' : 'Desconectado'}</small>
        <button className="shell-icon" title="Atualizar máquinas" onClick={loadMachines}><RefreshCw size={14} /></button><button className="shell-icon" aria-label="Configurar conexão do desktop" aria-expanded={settings} onClick={() => setSettings(value => !value)}><Settings2 size={14} /></button></header>
      {error && <p role="alert" className="shell-error">{error}</p>}
      {pending && <div className="shell-notice">Conexão aguardando confirmação. <button disabled={busy} onClick={reconcile}>Consultar mesma intenção</button></div>}
      {settings && <div className="dot-computer-settings">
        <label>Computador<select value={machineId} disabled={busy || Boolean(viewer) || Boolean(pending)} onChange={e => { setMachineId(e.target.value); setWorkItemId(''); setCapabilityId(''); setSessionId(''); setSessions([]); }}><option value="">Selecione</option>{desktops.map(item => <option key={item.machine_id} value={item.machine_id}>{item.name || item.machine_id}</option>)}</select></label>
        <label>Autorização<select value={workItemId} disabled={busy || Boolean(viewer) || Boolean(pending)} onChange={e => { setWorkItemId(e.target.value); setCapabilityId(''); }}><option value="">Selecione</option>{workItems.map(item => <option key={item.work_item_id} value={item.work_item_id}>{item.objective || item.work_item_id}</option>)}</select></label>
        {capabilities.length !== 1 && <label>Capacidade<select value={capabilityId} disabled={busy || Boolean(viewer) || Boolean(pending)} onChange={e => setCapabilityId(e.target.value)}><option value="">Selecione</option>{capabilities.map(id => <option key={id} value={id}>{id}</option>)}</select></label>}
        <label>Sessão<input value={sessionId} list={'dot-computer-sessions-' + scope.dot_id} disabled={busy || Boolean(viewer) || Boolean(pending)} onChange={e => setSessionId(e.target.value)} placeholder="Sessão autorizada" /><datalist id={'dot-computer-sessions-' + scope.dot_id}>{sessions.map(item => <option key={item.id || item.session_id} value={item.id || item.session_id}>{item.state}</option>)}</datalist></label>
        <div>{actions.includes('session.list') && <button disabled={busy || Boolean(pending) || !workItemId} onClick={() => sessionAction('session.list')}>Consultar sessões</button>}{actions.includes('open') && <button disabled={busy || Boolean(pending) || Boolean(viewer) || !workItemId} onClick={() => sessionAction('open')}>Abrir sessão</button>}</div>
        <button onClick={onConfigure}>Gerenciar máquinas e autorizações</button>
      </div>}
      <div className="dot-computer-screen">
        <div ref={container} className="shell-guacamole-display" aria-label={viewer?.control_mode === 'human' ? 'Desktop remoto com controle autorizado' : 'Visualização do desktop remoto'} onBlur={() => keyboard.current?.reset()} />
        {!viewer && <div className="dot-computer-empty"><Monitor size={40} /><strong>{desktops.length ? 'Conecte o computador deste Dot' : otherRemote.length ? 'Visualização deste provedor ainda indisponível' : 'Nenhum desktop remoto vinculado a este canvas'}</strong><p>{desktops.length ? 'Selecione uma sessão e uma autorização para acompanhar o desktop.' : otherRemote.length ? 'A máquina está cadastrada, mas esta superfície de desktop usa sessões Guacamole. Consulte a configuração do provedor.' : 'Cadastre uma máquina e sua sessão para visualizar o sistema aqui. O acesso aos arquivos do computador local continua independente.'}</p><button onClick={() => desktops.length ? setSettings(true) : onConfigure()}>{desktops.length ? 'Configurar conexão' : 'Configurar computador'}</button></div>}
      </div>
      <footer><span>{input?.live ? (input.holder === 'human' ? 'Entrada com você' : input.holder === 'agent' ? 'Entrada com o Dot' : 'Entrada ocupada') : 'Sem posse ativa'}</span>
        {!viewer ? <button disabled={busy || Boolean(pending) || !ready} onClick={() => { setMode('view'); void openViewer('view'); }}>Conectar</button> : <button disabled={busy} onClick={() => closeViewer()}>Desconectar</button>}
        {viewer?.control_mode !== 'human' ? <button disabled={busy || Boolean(pending) || !input || input.holder === 'busy' || !ready} onClick={async () => { if (await closeViewer() && await handoff('human')) { setMode('human'); await openViewer('human'); } }}>Assumir controle</button> : <button disabled={busy || Boolean(pending) || !input} onClick={async () => { if (await closeViewer() && await handoff('none')) { setMode('view'); await openViewer('view'); } }}>Liberar controle</button>}
        {mode === 'human' && !viewer && <button disabled={busy || Boolean(pending) || !ready || !input?.live || input.holder !== 'human' || input.grant_status !== 'granted'} onClick={openViewer}>Conectar com controle</button>}
      </footer>
      {receipt && <details className="dot-computer-receipt"><summary>Detalhes da conexão</summary><OperationReceipt value={receipt} /></details>}
    </section>;
  }
  return <section className="shell-machines" aria-label="Máquinas e posse de entrada"><header><h3><Monitor size={15} />Desktop e entrada</h3><button className="shell-icon" aria-label="Atualizar máquinas" onClick={loadMachines}><RefreshCw size={14} /></button></header>
    {error && <p role="alert" className="shell-error">{error}</p>}
    {!inventory.machines.length && <p>Nenhuma máquina configurada neste projeto.</p>}
    <label>Máquina<select value={machineId} disabled={busy || Boolean(viewer) || Boolean(pending)} onChange={e => { setMachineId(e.target.value); setWorkItemId(''); setCapabilityId(''); setSessionId(''); setSessions([]); }}><option value="">Selecione</option>{inventory.machines.map(item => <option key={item.machine_id} value={item.machine_id}>{item.name || item.machine_id} · {item.kind}</option>)}</select></label>
    {machine && <><p className="shell-machine-readiness">{machine.registered ? 'Recurso cadastrado' : 'Cadastro não confirmado'} · {machine.provider_verified ? 'Provedor verificado' : 'Provedor ainda não verificado'} · transporte {machine.transport_ready || 'não informado'}</p>
      <label>Trabalho autorizado<select value={workItemId} disabled={busy || Boolean(viewer) || Boolean(pending)} onChange={e => { setWorkItemId(e.target.value); setCapabilityId(''); }}><option value="">Selecione um WorkItem</option>{workItems.map(item => <option key={item.work_item_id} value={item.work_item_id}>{item.objective || item.work_item_id}</option>)}</select></label>
      <label>Capacidade<select value={capabilityId} disabled={busy || Boolean(viewer) || Boolean(pending)} onChange={e => setCapabilityId(e.target.value)}><option value="">Selecione uma capacidade</option>{capabilities.map(id => <option key={id} value={id}>{id}</option>)}</select></label>
      {input && <div className="shell-input-status" role="status"><Shield size={14} /><span>{input.holder === 'human' ? 'Entrada com você' : input.holder === 'agent' ? 'Entrada com agente' : input.holder === 'busy' ? 'Entrada ocupada' : 'Entrada livre'} · epoch {input.epoch}</span><small>{input.live ? 'Posse ativa · ' + input.ttl_remaining_seconds + ' s' : 'Sem posse ativa'} · autorização {input.grant_status || 'unknown'}</small></div>}
      <label>Duração da posse<select value={ttl} disabled={busy || Boolean(pending)} onChange={e => setTTL(Number(e.target.value))}><option value={30}>30 segundos</option><option value={60}>1 minuto</option><option value={120}>2 minutos</option><option value={300}>5 minutos</option></select></label>
      <details><summary>Intenção autorizada para devolver ao agente</summary><label>Argumentos da ação (JSON)<textarea value={agentArguments} disabled={busy || Boolean(pending)} maxLength={16000} onChange={e => setAgentArguments(e.target.value)} /></label><small>O handoff vincula a posse ao WorkItem e ao grant existentes. A ação descrita não é executada pelo handoff.</small></details>
      <div className="shell-machine-actions"><button disabled={busy || Boolean(pending) || !input || input.holder === 'busy'} onClick={() => handoff('human')}>Assumir entrada</button><button disabled={busy || Boolean(pending) || !input || !workItemId || !capabilityId || !agentArguments.trim()} onClick={() => handoff('agent')}>Devolver ao agente</button><button disabled={busy || Boolean(pending) || !input} onClick={() => handoff('none')}>Liberar entrada</button></div>
      <p className="shell-machine-note">Assumir entrada interrompe os próximos inputs do agente. Posse e permissão são verificadas separadamente pelo servidor.</p>
      {machine.kind === 'guacamole' && <><div className="shell-machine-actions">
        {(machine.actions?.[capabilityId] || []).includes('session.list') && <button disabled={busy || Boolean(pending) || !workItemId} onClick={() => sessionAction('session.list')}>Consultar sessões</button>}
        {(machine.actions?.[capabilityId] || []).includes('open') && <button disabled={busy || Boolean(pending) || Boolean(viewer) || !workItemId} onClick={() => sessionAction('open')}>Abrir sessão autorizada</button>}
      </div><label>Sessão Guacamole<input list="shell-guacamole-sessions" value={sessionId} disabled={busy || Boolean(viewer) || Boolean(pending)} onChange={e => setSessionId(e.target.value)} placeholder="ID da sessão já aberta" /><datalist id="shell-guacamole-sessions">{sessions.map(item => <option key={item.id || item.session_id} value={item.id || item.session_id}>{item.state}</option>)}</datalist></label>
        {(machine.actions?.[capabilityId] || []).includes('status') && <button disabled={busy || Boolean(pending) || !workItemId || !sessionId} onClick={() => sessionAction('status')}>Consultar vínculo da sessão</button>}
        <label>Modo do viewer<select value={mode} disabled={busy || Boolean(viewer) || Boolean(pending)} onChange={e => setMode(e.target.value)}><option value="view">Somente visualizar</option><option value="human">Teclado e mouse com posse humana</option></select></label>
        <div className="shell-machine-actions"><button disabled={busy || Boolean(viewer) || Boolean(pending) || !workItemId || !capabilityId || !sessionId || (mode === 'human' && (!input?.live || input.holder !== 'human' || input.grant_status !== 'granted'))} onClick={openViewer}>Abrir viewer</button>
          <button disabled={busy || !viewer} onClick={() => closeViewer()}><X size={13} />Fechar viewer</button></div></>}
    </>}
    {pending && <div className="shell-notice">Resposta pendente; nenhuma intenção nova será enviada.<button disabled={busy} onClick={reconcile}>Consultar mesma intenção</button></div>}
    <div ref={container} className="shell-guacamole-display" aria-label={mode === 'human' ? 'Desktop remoto com controle autorizado' : 'Visualização do desktop remoto'} onBlur={() => keyboard.current?.reset()} />
    {viewer && <div className="shell-viewer-status"><Status value={connection} /><span>{viewer.control_mode === 'view' ? 'Somente leitura' : 'Controle condicionado ao epoch ' + viewer.input_epoch}</span><small>Canais autorizados: {viewer.input_channels?.join(', ') || 'nenhum input'}.</small><small>Fechar desconecta o viewer; a sessão do sistema remoto permanece.</small></div>}
    {receipt && <OperationReceipt value={receipt} />}
    <details className="shell-remote-playback"><summary>Gravação do desktop</summary><p>Reprodução local de gravações exportadas. Nenhum input é enviado ao desktop.</p>
      <label>Abrir gravação JSON<input type="file" accept="application/json,.json" onChange={e => { const file = e.target.files[0]; e.target.value = ''; void loadRecording(file); }} /></label>
      <div ref={recordingContainer} className="shell-guacamole-display" aria-label="Reprodução local sem entrada remota" />
      {recording && <><p>{recording.name} · {recording.completeness_asserted ? 'Completude declarada no artefato' : 'Completude não declarada'}</p><div className="shell-machine-actions"><button onClick={() => playback.current?.play()}>Reproduzir</button><button onClick={() => playback.current?.pause()}>Pausar</button></div>
        <label>Posição em milissegundos<input type="number" min={0} value={position} onChange={e => setPosition(Math.max(0, Number(e.target.value)))} /></label><button onClick={() => playback.current?.seek(position)}>Ir à posição</button></>}
      <small>Gravação desativada no provedor permanece indisponível para exportação; a ausência de arquivo não é suprida por replay de inputs.</small>
    </details>
    <details><summary>Consultar operação</summary><label>ID da operação existente<input value={operation || ''} onChange={e => setOperation(e.target.value)} /></label><button disabled={!operation} onClick={observeOperation}>Observar estado</button></details>
    <button onClick={onConfigure}>Configurar máquinas e sessões</button>
  </section>;
}
