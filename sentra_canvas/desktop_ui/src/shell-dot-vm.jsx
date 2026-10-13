import React, { useEffect, useRef, useState } from 'react';
import { Cpu, Monitor, Pause, Play, Power, RefreshCw, Settings2 } from 'lucide-react';

// Physical PC scancodes; the installed guest's layout determines characters.
const keys = { Escape:1, Digit1:2, Digit2:3, Digit3:4, Digit4:5, Digit5:6, Digit6:7, Digit7:8, Digit8:9, Digit9:10, Digit0:11, Minus:12, Equal:13, Backspace:14, Tab:15,
  KeyQ:16, KeyW:17, KeyE:18, KeyR:19, KeyT:20, KeyY:21, KeyU:22, KeyI:23, KeyO:24, KeyP:25, BracketLeft:26, BracketRight:27, Enter:28, ControlLeft:29,
  KeyA:30, KeyS:31, KeyD:32, KeyF:33, KeyG:34, KeyH:35, KeyJ:36, KeyK:37, KeyL:38, Semicolon:39, Quote:40, Backquote:41, ShiftLeft:42, Backslash:43,
  KeyZ:44, KeyX:45, KeyC:46, KeyV:47, KeyB:48, KeyN:49, KeyM:50, Comma:51, Period:52, Slash:53, ShiftRight:54, AltLeft:56, Space:57, CapsLock:58,
  F1:59, F2:60, F3:61, F4:62, F5:63, F6:64, F7:65, F8:66, F9:67, F10:68, NumLock:69, ScrollLock:70, F11:87, F12:88, IntlBackslash:86,
  ArrowUp:[224,72], ArrowLeft:[224,75], ArrowRight:[224,77], ArrowDown:[224,80], Insert:[224,82], Delete:[224,83], Home:[224,71], End:[224,79], PageUp:[224,73], PageDown:[224,81],
  ControlRight:[224,29], AltRight:[224,56], MetaLeft:[224,91], MetaRight:[224,92], ContextMenu:[224,93], NumpadEnter:[224,28], NumpadDivide:[224,53] };
function scancodes(code, down) {
  const scan = keys[code]; if (!scan) return null;
  const list = Array.isArray(scan) ? [...scan] : [scan]; if (!down) list[list.length - 1] |= 128;
  return list;
}

export function ShellDotVm({ dot, conversation, bridge, visible = true, onRemote }) {
  const [status, setStatus] = useState(null), [frame, setFrame] = useState(null), [intervalMs, setIntervalMs] = useState(null);
  const [images, setImages] = useState([]);
  const [settings, setSettings] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState(''), [pending, setPending] = useState(null);
  const [form, setForm] = useState({ os_family:'linux', cpus:2, memory_mb:4096, disk_gb:64, iso_path:'' });
  const [watching, setWatching] = useState(true);
  const [importFolder, setImportFolder] = useState('.');
  const alive = useRef(true), initialized = useRef(false), lastFrame = useRef(null), lock = useRef(false), held = useRef(new Set()), pointer = useRef(null), pointerTimer = useRef(null);
  const state = useRef(null), pendingRef = useRef(null), inputQueue = useRef([]), sendingInput = useRef(false), screen = useRef(null), visibleRef = useRef(visible);
  state.current = status; visibleRef.current = visible;
  const scope = { project_id:dot.project_id, space_id:dot.space_id, dot_id:dot.dot_id, conversation_id:conversation?.conversation_id };
  const vm = status?.vm, running = vm?.vm_state === 'running', human = status?.input?.holder === 'human' && status.input.live === true;
  const debianSeed = vm?.os_family === 'linux' && /debian-live-13\./i.test(vm.iso_path || '');
  const installation = status?.installation;
  useEffect(() => {
    let active = true;
    bridge({ action:'dot_vm_images', ...scope }).then(value => {
      if (active) setImages(value.items || []);
    }).catch(() => { if (active) setImages([]); });
    return () => { active = false; };
  }, [dot.dot_id, conversation?.conversation_id]);
  async function refresh() {
    const value = await bridge({ action:'dot_vm_status', ...scope });
    if (!alive.current) return;
    setStatus(value);
    if (!initialized.current) {
      initialized.current = true;
      if (value.vm) { setForm(old => ({ ...old, ...Object.fromEntries(Object.keys(old).map(key => [key, value.vm[key] ?? old[key]])) })); setSettings(!value.vm.iso_path); }
    }
  }
  useEffect(() => {
    alive.current = true; let active = true, fetching = false;
    async function load() { if (!active || fetching || !visible || document.hidden) return; fetching = true; try { await refresh(); } catch (e) { if (active) setError(e.message); } finally { fetching = false; } }
    void load(); const timer = setInterval(load, 4000);
    return () => { active = false; alive.current = false; clearInterval(timer); clearTimeout(pointerTimer.current); };
  }, [dot.dot_id, conversation?.conversation_id, visible]);
  useEffect(() => {
    if (!running || !visible || !watching) { setFrame(null); lastFrame.current = null; return; }
    let active = true, timer;
    async function capture() {
      if (!active) return;
      const begin = performance.now();
      if (!document.hidden) {
        try {
          const value = await bridge({ action:'dot_vm_frame', ...scope });
          if (!active) return;
          if (value.status === 'live' && value.image_base64) {
            const previous = lastFrame.current; lastFrame.current = value.captured_at;
            setFrame(value); if (previous) setIntervalMs(Math.round((value.captured_at - previous) * 1000));
          } else { setFrame(null); setError('O framebuffer da VM ainda não está disponível.'); }
        } catch (e) { if (active) { setFrame(null); setError(e.message); } }
      }
      // At most one sequential capture per second; no background or overlap.
      if (active) timer = setTimeout(capture, Math.max(1000, performance.now() - begin));
    }
    void capture(); return () => { active = false; clearTimeout(timer); };
  }, [running, visible, watching, dot.dot_id, conversation?.conversation_id]);
  async function inspectPending() {
    const request = pendingRef.current;
    if (!request || busy) return;
    try {
      const verified = await bridge({ action:'dot_vm_status', ...scope });
      if (!alive.current) return;
      setStatus(verified);
      // A confirmed lease epoch/holder is authoritative for handoff. It does
      // not claim a possibly UNCERTAIN physical operation was completed.
      const leaseAdvanced = request.action === 'dot_vm_handoff'
        && verified.input?.live === true
        && verified.input.epoch > request.expected_epoch;
      const confirmedHandoff = leaseAdvanced && verified.input.holder === request.holder;
      // An epoch advanced by another handoff supersedes the old request:
      // its stale expected_epoch can no longer acquire the keyboard.
      const supersededHandoff = leaseAdvanced && !confirmedHandoff;
      // A VM observed as physically running need not stay UI-blocked by an
      // older provision request. That original request remains UNCERTAIN in
      // the host journal; we only release this view for independent actions.
      const physicalVmPresent = request.action === 'dot_vm_execute'
        && request.arguments?.action === 'provision'
        && verified.vm?.vm_state === 'running'
        && verified.vm?.conversation_authorized === true;
      if (confirmedHandoff || supersededHandoff || physicalVmPresent) {
        pendingRef.current = null; setPending(null);
        setError(confirmedHandoff ? 'Controle confirmado pelo estado atual da VM.' :
          supersededHandoff ? 'Posse do teclado atualizada por outra decisão. A solicitação anterior permanece sem recibo e não foi reenviada.' :
          'VM física confirmada. A solicitação anterior continua incerta no histórico; nenhuma criação foi reenviada.');
      } else {
        setError('A operação anterior continua sem confirmação. Nenhuma ação foi reenviada; consulte o diagnóstico original antes de tentar novamente.');
      }
    } catch (e) { setError(e.message); }
  }
  async function mutate(action, fields = {}) {
    if (lock.current) return false;
    // Never reuse a request key for a different operation or automatically
    // replay an uncertain physical effect. The owner can inspect read-only.
    if (pendingRef.current) {
      setError('Há uma operação não confirmada. Verifique o estado sem reenviar antes de outro comando.');
      return false;
    }
    lock.current = true; setBusy(true); setError('');
    const request = { action, ...scope, ...fields, request_key:crypto.randomUUID() };
    pendingRef.current = request;
    try {
      const value = await bridge(request);
      if (value.state === 'UNCERTAIN' || value.status === 'uncertain') { setPending(request); setError('A operação ainda não foi confirmada. Consulte a mesma intenção antes de continuar.'); return false; }
      pendingRef.current = null; setPending(null);
      if (value.state && value.state !== 'SUCCEEDED') throw Error(value.error || 'A operação da VM não foi autorizada.');
      if (['pending_image', 'unsupported_image', 'existing_vm'].includes(value.evidence?.status)) setError(value.evidence.status === 'pending_image' ? 'Informe uma ISO local para instalar o sistema.' : value.evidence.status === 'unsupported_image' ? 'Esta ISO não permite a instalação automática do sistema selecionado.' : 'Esta VM já existe; sua instalação não foi repetida.');
      await refresh(); return true;
    } catch (e) { setError(e.message); if (e.uncertain) setPending(request); else { pendingRef.current = null; setPending(null); } return false; }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function canInput() { return visibleRef.current && state.current?.input?.holder === 'human' && state.current.input.live && !pendingRef.current; }
  async function drainInput() {
    if (sendingInput.current) return;
    sendingInput.current = true;
    try {
      while (inputQueue.current.length && canInput()) {
        const argumentsValue = inputQueue.current.shift();
        const value = await bridge({ action:'dot_vm_input', ...scope, arguments:argumentsValue,
          expected_epoch:state.current.input.epoch, request_key:crypto.randomUUID() });
        if (value.state !== 'SUCCEEDED') throw Error('Entrada da VM não confirmada; atualize a posse de controle.');
      }
    } catch (e) { inputQueue.current = []; held.current.clear(); if (alive.current) setError(e.message); }
    finally { sendingInput.current = false; }
  }
  function sendInput(argumentsValue) { if (!canInput() || inputQueue.current.length >= 32) return; inputQueue.current.push(argumentsValue); void drainInput(); }
  function keyboard(e, down) {
    if (!canInput()) return;
    const scans = scancodes(e.code, down); if (!scans) return;
    e.preventDefault(); if (down && held.current.has(e.code)) return;
    if (down) held.current.add(e.code); else held.current.delete(e.code);
    sendInput({ action:'input.key', scancodes:scans });
  }
  function releaseKeys() {
    for (const code of held.current) { const scans = scancodes(code, false); if (scans) sendInput({ action:'input.key', scancodes:scans }); }
    held.current.clear();
    if (pointer.current) sendInput({ ...pointer.current, buttons:0 });
  }
  function mouse(e) {
    if (!canInput() || !frame) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const buttons = ((e.buttons & 1) ? 1 : 0) | ((e.buttons & 2) ? 2 : 0) | ((e.buttons & 4) ? 4 : 0);
    const args = { action:'input.mouse', x:Math.min(frame.source_width, Math.max(1, Math.round((e.clientX - rect.left) / rect.width * frame.source_width))),
      y:Math.min(frame.source_height, Math.max(1, Math.round((e.clientY - rect.top) / rect.height * frame.source_height))), buttons,
      ...(e.type === 'wheel' ? { wheel:-Math.sign(e.deltaY) } : {}) };
    pointer.current = args;
    if (e.type === 'pointermove') { clearTimeout(pointerTimer.current); pointerTimer.current = setTimeout(() => sendInput(args), 60); }
    else { clearTimeout(pointerTimer.current); if (e.type === 'pointerdown') e.currentTarget.setPointerCapture(e.pointerId); screen.current?.focus(); e.preventDefault(); sendInput(args); }
  }
  async function create() {
    if (await mutate('dot_vm_configure', form) && form.iso_path.trim()) { setSettings(false); await mutate('dot_vm_execute', { arguments:{ action:'provision' } }); }
  }
  async function preparePersistent() {
    if (await mutate('dot_vm_execute', { arguments:{ action:'installation.prepare' } })) {
      await mutate('dot_vm_execute', { arguments:{ action:'start' } });
    }
  }
  async function bootPersistent() {
    if (await mutate('dot_vm_execute', { arguments:{ action:'installation.boot_disk' } })) {
      await mutate('dot_vm_execute', { arguments:{ action:'start' } });
    }
  }
  return <section className="dot-vm-panel" data-view-active={String(visible)} aria-label="Máquina virtual exclusiva do Dot">
    <header><Monitor size={16} /><strong>{vm ? (vm.os_family === 'windows' ? 'Windows' : 'Linux') : 'Máquina virtual do Dot'}</strong><small role="status" aria-live="polite">{running && frame?.status === 'live' ? '● Ao vivo · VM do Dot' : running ? 'VM ligada · conectando vídeo…' : vm?.vm_state || (status?.hypervisor_available ? 'Aguardando configuração' : 'VirtualBox indisponível')}</small><button className="shell-icon" aria-label="Configuração da VM" onClick={() => setSettings(value => !value)}><Settings2 size={15} /></button></header>
    {status?.host && <div className="dot-vm-budget"><Cpu size={13} /><span>{status.host.reserved_cpus}/{status.host.max_cpus} vCPU · {(status.host.reserved_memory_mb / 1024).toFixed(1)}/{(status.host.max_memory_mb / 1024).toFixed(1)} GiB reservados</span><small>Todas as VMs dos Dots juntas: até 50% dos processadores lógicos e da RAM física configurados.</small></div>}
    {error && <p className="shell-error" role="alert">{error}</p>}
    {installation && <p className="shell-notice">{installation.installed_os_verified ? 'Instalação persistente verificada' : 'Instalação persistente ainda não verificada'}{installation.desktop_ready_verified ? ' · desktop XFCE confirmado' : ''}{installation.verified_at ? ' · última verificação: ' + new Date(installation.verified_at * 1000).toLocaleString() : ''}. {vm?.vm_state !== 'running' ? 'A VM está desligada ou pausada.' : 'Use Verificar instalação para atualizar a confirmação.'}</p>}
    {vm?.os_family === 'windows' && !installation?.installed_os_verified && <p className="shell-notice">A instalação do Windows depende da ISO local e da licença correspondente. O desktop instalado e o canal de comandos ainda não foram verificados.</p>}
    {vm?.provisioning_status === 'uncertain_requires_reconciliation' && <p role="alert" className="shell-error">O provisionamento anterior está INCERTO. A reserva permanece retida. Verifique a VM física e reconcilie a operação original antes de tentar criar novamente.</p>}
    {pending && <p className="shell-notice">Operacao anterior sem confirmacao. <button disabled={busy} onClick={() => void inspectPending()}>Verificar estado sem reenviar</button></p>}
    {settings && <form className="dot-vm-form" onSubmit={e => { e.preventDefault(); void create(); }}>
      <label>Sistema<select value={form.os_family} disabled={busy || Boolean(pending) || vm?.vm_state === 'running'} onChange={e => setForm(value => ({ ...value, os_family:e.target.value, cpus:Math.max(value.cpus, e.target.value === 'windows' ? 2 : 1), memory_mb:Math.max(value.memory_mb, e.target.value === 'windows' ? 4096 : 1024), disk_gb:Math.max(value.disk_gb, e.target.value === 'windows' ? 64 : 16) }))}><option value="linux">Linux com interface gráfica</option><option value="windows">Windows</option></select></label>
      <label>Processadores<input type="number" min={form.os_family === 'windows' ? 2 : 1} max={status?.host?.max_cpus || 1} value={form.cpus} disabled={busy || Boolean(pending)} onChange={e => setForm(value => ({ ...value, cpus:Number(e.target.value) }))} /></label>
      <label>RAM (MiB)<input type="number" min={form.os_family === 'windows' ? 4096 : 1024} step={256} max={status?.host?.max_memory_mb} value={form.memory_mb} disabled={busy || Boolean(pending)} onChange={e => setForm(value => ({ ...value, memory_mb:Number(e.target.value) }))} /></label>
      <label>Disco virtual (GiB)<input type="number" min={form.os_family === 'windows' ? 64 : 16} max={256} value={form.disk_gb} disabled={busy || Boolean(pending)} onChange={e => setForm(value => ({ ...value, disk_gb:Number(e.target.value) }))} /></label>
      {images.length > 0 && <label>ISOs encontradas no projeto<select value={images.some(image => image.path === form.iso_path) ? form.iso_path : ''} onChange={e => setForm(value => ({ ...value, iso_path:e.target.value }))} disabled={busy || Boolean(pending)}><option value="">Selecionar imagem local</option>{images.map(image => <option key={image.path} value={image.path}>{image.name}</option>)}</select></label>}
      <label className="dot-vm-image">ISO local de instalação<input value={form.iso_path} disabled={busy || Boolean(pending)} placeholder="C:\ISOs\sistema.iso" onChange={e => setForm(value => ({ ...value, iso_path:e.target.value }))} /><small>Use uma ISO de desktop Linux ou Windows que já exista neste computador. Nenhuma imagem será baixada automaticamente.</small></label>
      <p>A VM pertence exclusivamente ao canvas deste Dot. Com acesso completo, o Dot pode iniciar a instalação e executar comandos dentro dela.</p><button disabled={busy || Boolean(pending) || !status?.hypervisor_available || vm?.provisioning_status === 'uncertain_requires_reconciliation'}>{busy ? 'Configurando…' : form.iso_path.trim() ? 'Criar e instalar sistema' : 'Salvar · aguardando ISO'}</button>
    </form>}
    {debianSeed && !installation?.installed_os_verified && <div className="dot-vm-install">
      <p>A ISO Live é temporária. A instalação persistente usa exclusivamente o disco virtual vazio deste Dot.</p>
      {!['installation_seed_prepared','installation_launch_sent','disk_boot_configured'].includes(vm.provisioning_status) && <button disabled={busy || Boolean(pending) || human || !['poweroff','running'].includes(vm.vm_state)} onClick={preparePersistent}>Preparar instalação persistente</button>}
      {vm.provisioning_status === 'installation_seed_prepared' && <><p>Aguarde aparecer o desktop Live antes de iniciar. A instalação encerra a VM quando termina.</p><button disabled={busy || Boolean(pending) || human || !running || !frame} onClick={() => mutate('dot_vm_execute', { arguments:{ action:'installation.launch' } })}>Instalar no disco vazio do Dot</button></>}
      {vm.provisioning_status === 'installation_launch_sent' && (vm.vm_state === 'poweroff' ? <button disabled={busy || Boolean(pending) || human} onClick={bootPersistent}>Iniciar pelo disco instalado</button> : <p>Instalação enviada. Acompanhe o progresso na tela; nenhuma tentativa será repetida automaticamente.</p>)}
    </div>}
    <div className="dot-vm-frame" ref={screen} tabIndex={human ? 0 : -1} aria-label={human ? 'Desktop da VM com controle humano' : 'Desktop da VM observado'} onKeyDown={e => keyboard(e, true)} onKeyUp={e => keyboard(e, false)} onBlur={releaseKeys}>
      {frame ? <img src={'data:image/png;base64,' + frame.image_base64} alt="Framebuffer atual da máquina virtual deste Dot" draggable={false} onPointerDown={mouse} onPointerUp={mouse} onPointerMove={mouse} onWheel={mouse} onContextMenu={e => { if (human) e.preventDefault(); }} /> : <div className="dot-computer-empty"><Monitor size={38} /><strong>{vm?.iso_path ? 'A tela aparece quando a VM estiver em execução' : 'Escolha uma ISO para instalar o sistema'}</strong><p>{vm?.iso_path ? 'O início da instalação não confirma que o sistema já está pronto.' : 'Linux e Windows são suportados. A VM permanece sem criar ou iniciar até existir uma imagem de instalação.'}</p></div>}
    </div>
    <footer><span>{frame ? 'Quadro real' + (intervalMs ? ' · atualização em ' + (intervalMs / 1000).toFixed(1) + ' s' : '') + ' · captura ' + frame.capture_ms + ' ms' : 'Sem quadro atual'}</span><button onClick={() => setWatching(value => !value)} disabled={!running}>{watching ? 'Pausar visualização' : 'Ver tela'}</button>
      {running || vm?.vm_state === 'paused' ? <><button disabled={busy || Boolean(pending) || human} onClick={() => mutate('dot_vm_execute', { arguments:{ action:vm.vm_state === 'paused' ? 'resume' : 'pause' } })}><Pause size={13} />{vm.vm_state === 'paused' ? 'Retomar VM' : 'Pausar VM'}</button><button disabled={busy || Boolean(pending) || human} onClick={() => mutate('dot_vm_execute', { arguments:{ action:'shutdown' } })}><Power size={13} />Desligar</button></> : vm?.vm_state && vm.vm_state !== 'not_created' && <button disabled={busy || Boolean(pending)} onClick={() => mutate('dot_vm_execute', { arguments:{ action:'start' } })}><Play size={13} />Iniciar</button>}
      <button disabled={busy || Boolean(pending) || !running} onClick={async () => { releaseKeys(); await mutate('dot_vm_handoff', { holder:human ? 'agent' : 'human', expected_epoch:status?.input?.epoch || 0 }); }}>{human ? 'Devolver ao Dot' : 'Assumir controle'}</button><button className="shell-icon" aria-label="Atualizar estado da VM" onClick={() => refresh().catch(e => setError(e.message))}><RefreshCw size={14} /></button></footer>
    {running && <button disabled={busy || Boolean(pending) || human} onClick={() => mutate('dot_vm_execute', { arguments:{ action:'installation.verify' } })}>Verificar instalação</button>}
    {installation?.installed_os_verified && <details className="dot-vm-advanced"><summary>Copiar projeto para a VM</summary><p>Cria uma cópia independente do projeto ou da pasta selecionada. Credenciais, diretórios de ferramentas e arquivos vinculados são excluídos.</p><label>Pasta relativa ao projeto<input value={importFolder} onChange={e => setImportFolder(e.target.value)} placeholder=". para o projeto inteiro" /></label><button disabled={busy || Boolean(pending) || human || !running} onClick={() => mutate('dot_vm_execute', { arguments:{ action:'project.import', relative_path:importFolder } })}>Copiar para a VM deste Dot</button>{vm?.last_project_import?.guest_path && <p>Cópia disponível em <code>{vm.last_project_import.guest_path}</code>.</p>}</details>}
    {human && <small className="dot-vm-control-note">Clique na tela para usar teclado e mouse. A posse dura até 5 minutos; enquanto ativa, os comandos e entradas do Dot ficam bloqueados.</small>}
    <details className="dot-vm-advanced"><summary>Outros desktops e conexões existentes</summary><button onClick={onRemote}>Abrir desktop remoto configurado</button></details>
  </section>;
}
