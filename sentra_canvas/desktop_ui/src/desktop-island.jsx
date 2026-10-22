import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { DotMascot } from './shell-mascot.jsx';
import { Tracked } from './vendor/coucou/core/anim.ts';
import { islandSize, botPosition, botGlowColor, botGlowOpacity } from './vendor/coucou/core/layout.ts';
import { IslandStateMachine } from './vendor/coucou/island/fsm.ts';
import { ICONS } from './vendor/coucou/views/icons.ts';
import { Ticker } from './vendor/coucou/views/ticker.ts';
import './vendor/coucou/style.css';
import './desktop-island.css';

const EMPTY = { schema: 1, sessions: [], events: [], decisions: 0, connected: false, observedAt: 0 };
const STATES = { work: 'Trabalhando', wait: 'Precisa de você', error: 'Precisa de atenção', done: 'Concluído e verificado', review: 'Resultado registrado', idle: 'Disponível' };
const COLORS = ['#22C55E', '#EAB308', '#60A5FA', '#E879F9'];
const colorFor = (id = '') => COLORS[Math.abs([...id].reduce((v, c) => (v * 31 + c.charCodeAt(0)) | 0, 0)) % COLORS.length];
function Icon({ name, size = 14, stroke = 0 }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"><path d={ICONS[name] || ICONS.bubble}
    fill={stroke ? 'none' : 'currentColor'} stroke={stroke ? 'currentColor' : undefined} strokeWidth={stroke || undefined} strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
function mood(row, fresh) {
  if (!fresh) return { status: 'idle' };
  if (row?.tone === 'work' && row.workingValidated) return { status: 'running', execution: { validated: true, workItemState: 'RUNNING', operationState: 'RUNNING' } };
  if (row?.tone === 'done') return { status: 'completed', execution: { verified: true } };
  return { status: row?.tone === 'wait' ? 'needs_input' : row?.tone === 'error' ? 'failed' : 'idle' };
}
function Dot({ row, fresh, diameter }) {
  return <span className="sentra-coucou-dot" style={{ width: diameter, height: diameter }}>
    <DotMascot mascot={row?.mascot || 'oxta'} identity={row?.dotId || 'oxta'} name={row?.name || 'Dot'} {...mood(row, fresh)} decorative />
  </span>;
}
function LiveTicker({ row, events, fresh, onOpen }) {
  const host = useRef(null), ticker = useRef(null), open = useRef(onOpen); open.current = onOpen;
  const sequence = useRef({ key: null, index: 0 });
  useLayoutEffect(() => {
    const instance = new Ticker(() => open.current?.()); ticker.current = instance;
    sequence.current = { key: null, index: 0 };
    host.current.append(instance.el);
    return () => { instance.el.remove(); ticker.current = null; };
  }, [row?.dotId]);
  useLayoutEffect(() => {
    const instance = ticker.current; if (!instance) return;
    const relevant = events.filter(e => !e.dotId || e.dotId === row?.dotId).slice(0, 12).reverse();
    const steps = relevant.map(e => e.label);
    if (!steps.length) steps.push(row?.detail || STATES[row?.tone] || 'Disponível');
    const key = relevant.at(-1)?.id || row?.detail || row?.tone;
    if (sequence.current.key !== key) {
      const previous = relevant.findIndex(e => e.id === sequence.current.key);
      sequence.current.index += previous < 0 ? 1 : relevant.length - previous - 1;
      sequence.current.key = key;
    }
    instance.sync({ steps, stepSeq: sequence.current.index, stepIndex: steps.length - 1,
      finalLine: fresh && row?.tone === 'done' ? steps.at(-1) : undefined });
    let frame = 0;
    function animate(now) { instance.tick(now); if (instance.animating) frame = requestAnimationFrame(animate); }
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [row, events, fresh]);
  // Idle/uncertain observations do not claim that an unobserved process is working.
  const active = fresh && (row?.workingValidated || row?.tone === 'done');
  return <><div ref={host} className="sentra-coucou-ticker" style={{ display: active ? 'contents' : 'none' }}/>{!active && <div className="ticker sentra-coucou-static">
    <div className="ticker-row" style={{ transform: 'translateY(22px)' }}><span className="tick-icon"><Icon name={row?.tone === 'error' ? 'xmark' : 'chevronRight'} size={9} stroke={2.4}/></span>
      <span className="tick-text">{!fresh ? 'Aguardando atualização' : row?.detail || STATES[row?.tone] || 'Disponível'}</span></div>
  </div>}</>;
}
export function DesktopIsland({ fixture }) {
  const [snapshot, setSnapshot] = useState(fixture || EMPTY), [mode, setMode] = useState('compact');
  const [view, setView] = useState('overview'), [selectedId, setSelectedId] = useState('');
  const [clock, setClock] = useState(Date.now()), [sound, setSound] = useState(true), [volume, setVolume] = useState(.12), [autoClose, setAutoClose] = useState(15);
  const [showClock, setShowClock] = useState(false);
  const fsm = useRef(null), shape = useRef(null), content = useRef(null), figure = useRef(null), grid = useRef(null), glowNode = useRef(null), countdown = useRef(null), audio = useRef(null);
  const modeRef = useRef(mode), viewRef = useRef(view), snapshotRef = useRef(snapshot); snapshotRef.current = snapshot;
  const rows = snapshot.sessions || [], simulated = !!(snapshot.preview || fixture);
  const fresh = snapshot.connected && snapshot.observedAt > 0 && clock - snapshot.observedAt < 16000;
  const row = rows.find(r => r.dotId === selectedId) || rows.find(r => r.tone === 'work' && r.workingValidated) || rows[0];
  const expanded = mode === 'expanded', selectedIndex = Math.max(0, rows.findIndex(r => r.dotId === row?.dotId));
  const visibleRows = rows.slice(Math.floor(selectedIndex / 4) * 4, Math.floor(selectedIndex / 4) * 4 + 4);
  const mainState = !fresh ? 'idle' : row?.tone === 'work' && row.workingValidated ? 'working' : row?.tone === 'wait' ? 'approval' : row?.tone === 'error' ? 'error' : row?.tone === 'done' ? 'finished' : 'idle';
  const glow = botGlowColor(mainState);
  useEffect(() => fixture ? undefined : window.sentraIsland?.subscribe(setSnapshot), [fixture]);
  useEffect(() => { const t = setInterval(() => setClock(Date.now()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => {
    const machine = new IslandStateMachine(); fsm.current = machine;
    machine.onTransition = (_from, next) => {
      const value = next === 'home' || next === 'coucou' ? 'expanded' : next === 'hidden' ? 'hidden' : 'compact';
      modeRef.current = value; setMode(value); window.sentraIsland?.expand(value === 'expanded');
    };
    machine.forcePetit(); machine.mouseLeft();
    return () => { machine.onTransition = null; machine.forceHidden(); fsm.current = null; };
  }, []);
  useEffect(() => { if (fsm.current) fsm.current.homeToPetitDelay = autoClose; }, [autoClose]);
  useEffect(() => { if (fsm.current) fsm.current.pinned = fresh && (snapshot.decisions > 0 || rows.some(r => r.tone === 'wait')); }, [snapshot.decisions, rows, fresh]);
  useEffect(() => {
    if (!fsm.current || typeof snapshot.expanded !== 'boolean') return;
    if (snapshot.expanded && modeRef.current !== 'expanded') fsm.current.forceHome();
    if (!snapshot.expanded && modeRef.current === 'expanded') fsm.current.forcePetit();
  }, [snapshot.expanded]);
  useEffect(() => {
    if (modeRef.current === 'hidden' && fresh && rows.some(r => ['work', 'wait', 'error'].includes(r.tone))) fsm.current?.reveal();
  }, [snapshot.observedAt, fresh]);
  const geometry = useRef({ width: new Tracked(288), height: new Tracked(32), radius: new Tracked(14) });
  useLayoutEffect(() => {
    modeRef.current = mode; viewRef.current = view;
    const g = geometry.current, target = islandSize(mode, view === 'settings' ? 'settings' : 'overview');
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    for (const [key, value] of Object.entries({ width: target.w, height: target.h, radius: expanded ? 22 : 14 })) {
      if (!g[key].animating && Math.abs(g[key].value - value) < .01) { g[key].jump(value); continue; }
      if (reduced) g[key].jump(value);
      else if (value > g[key].value) g[key].springTo(value);
      else g[key].curveTowards(value);
    }
    let frame = 0, previous = performance.now();
    function animate(now) {
      const dt = Math.min(.05, (now - previous) / 1000); previous = now;
      for (const tracked of Object.values(g)) tracked.step(dt, now);
      const w = g.width.value, h = Math.max(0, g.height.value), scale = Math.min(1, window.innerWidth / 720);
      if (shape.current) Object.assign(shape.current.style, { width: w + 'px', height: h + 'px', borderRadius: `0 0 ${g.radius.value}px ${g.radius.value}px`, transform: `translateX(-50%) scale(${scale})` });
      const bot = botPosition(modeRef.current, viewRef.current === 'settings' ? 'settings' : 'overview', h);
      if (figure.current) Object.assign(figure.current.style, { left: bot.cx + 'px', top: bot.cy + 'px', width: bot.diameter + 'px', height: bot.diameter + 'px', opacity: String(bot.opacity) });
      if (glowNode.current) Object.assign(glowNode.current.style, { left: (bot.cx - bot.diameter * 1.1) + 'px', top: (bot.cy - bot.diameter * 1.1) + 'px', width: bot.diameter * 2.2 + 'px', height: bot.diameter * 2.2 + 'px' });
      if (grid.current) Object.assign(grid.current.style, { left: (w - 40 - 14.5) + 'px', top: (h / 2 - 14.5) + 'px' });
      const due = fsm.current?.homeCollapseDueAt, remaining = due == null ? 0 : (due - now) / 1000, range = Math.min(10, autoClose * .6);
      if (countdown.current) countdown.current.style.width = expanded && due && remaining < range ? Math.max(0, remaining / range * 160) + 'px' : '0px';
      window.sentraIsland?.geometry?.({ width: Math.min(720, w * scale), height: Math.min(320, h * scale) });
      if (Object.values(g).some(t => t.animating) || expanded && due != null) frame = requestAnimationFrame(animate);
    }
    frame = requestAnimationFrame(animate); return () => cancelAnimationFrame(frame);
  }, [mode, view, autoClose, clock]);
  function blip() {
    if (!sound) return;
    try { const a = audio.current || (audio.current = new AudioContext()), o = a.createOscillator(), gain = a.createGain();
      void a.resume(); o.frequency.value = 720; gain.gain.setValueAtTime(volume, a.currentTime); gain.gain.exponentialRampToValueAtTime(.0001, a.currentTime + .06); o.connect(gain); gain.connect(a.destination); o.start(); o.stop(a.currentTime + .07);
    } catch { /* Display sounds are optional. */ }
  }
  function activate(action, target = row) { if (!fixture) window.sentraIsland?.activate(action, target?.dotId); }
  function go(next) { blip(); fsm.current?.userInteracted(); setView(next); fsm.current?.forceHome(); }
  function keydown(event) {
    if (event.key === 'Escape') { event.preventDefault(); fsm.current?.forcePetit(); }
    if (event.ctrlKey && ['ArrowRight', 'ArrowLeft'].includes(event.key) && rows.length) {
      event.preventDefault(); setSelectedId(rows[(selectedIndex + (event.key === 'ArrowRight' ? 1 : rows.length - 1)) % rows.length].dotId);
    }
    if (event.ctrlKey && event.key.toLowerCase() === 'o') { event.preventDefault(); activate('canvas'); }
  }
  return <div id="root" onKeyDown={keydown}>
    <div id="wake-strip" onMouseEnter={() => fsm.current?.mouseEntered()} />
    <div ref={shape} id="island" className="desktop-island" data-live={fresh ? 'true' : 'false'} data-mode={mode} aria-label={simulated ? 'Prévia visual do SENTRA' : 'Atividade dos Dots'}
      onMouseEnter={() => fsm.current?.mouseEntered()} onMouseLeave={() => fsm.current?.mouseLeft()} onPointerDown={() => fsm.current?.userInteracted()}
      style={{ width: 288, height: 32, transform: 'translateX(-50%)', transformOrigin: 'top center' }}>
      <div id="island-clip"><div ref={content} id="content" style={{ opacity: expanded ? 1 : 0, pointerEvents: expanded ? 'auto' : 'none' }} aria-hidden={!expanded}>
        <div id="header"><div className="tabs">
          <button className={'tab' + (view === 'overview' ? ' on' : '')} title="Visão geral" aria-label="Visão geral" onClick={() => go('overview')}><Icon name="house" size={13}/></button>
          <button className="tab" title="Abrir conversa" aria-label="Abrir conversa" disabled={simulated || !row?.conversationId} onClick={() => activate('conversation')}><Icon name="bubble" size={13}/></button>
          <button className="tab" title="Anexar na conversa" aria-label="Anexar na conversa" disabled={simulated || !row?.conversationId} onClick={() => activate('conversation')}><Icon name="plus" size={13}/></button>
        </div><div className="header-actions">
          <button className={view === 'settings' ? 'on' : ''} title="Configurações" aria-label="Configurações" onClick={() => go('settings')}><Icon name={view === 'settings' ? 'gearFill' : 'gear'} size={14}/></button>
          <button title={sound ? 'Silenciar' : 'Ativar som'} aria-label={sound ? 'Silenciar' : 'Ativar som'} onClick={() => setSound(v => !v)}><Icon name={sound ? 'speakerOn' : 'speakerOff'} size={14}/></button>
        </div></div>
        <div id="views">
          {view === 'overview' && <div className="view overview on"><div className="left"><div className="card"><div className="left-body"><div className="card-body">
            <div className="who"><i className="dot" style={{ width: 7, height: 7, background: colorFor(row?.dotId) }}/><span className="name">{row?.name || 'SENTRA'}</span><span className="tool">{simulated ? 'Prévia' : 'Dot'}</span></div>
            <LiveTicker row={row} events={snapshot.events || []} fresh={fresh} onOpen={() => activate('canvas')}/>
          </div></div><button className="icon-btn jump" title="Abrir Canvas" aria-label="Abrir Canvas" disabled={simulated || !row} onClick={() => activate('canvas')}><Icon name="arrowUpRight" size={8}/></button></div></div>
          <div className="right"><div className="card"><div className="pills">{visibleRows.map(item => <button key={item.dotId} className="pill" title={`${item.name} · ${fresh ? STATES[item.tone] : 'Última leitura'}`} aria-pressed={row?.dotId === item.dotId}
            style={{ borderColor: colorFor(item.dotId) + '24', '--pill-color': colorFor(item.dotId) }}
            onClick={() => { blip(); setSelectedId(item.dotId); }}>
            <span className="mini" style={{ width: 24, height: 24 }}><Dot row={item} fresh={fresh} diameter={24}/></span><span className="lbl">{item.name}</span>
            {['wait', 'done', 'error'].includes(item.tone) && <span className="pill-badge"><i style={{ background: item.tone === 'wait' ? '#F5A524' : item.tone === 'done' ? '#22C55E' : '#F4505E' }}><Icon name={item.tone === 'wait' ? 'bang' : item.tone === 'done' ? 'check' : 'xmark'} size={6}/></i></span>}
          </button>)}</div></div></div></div>}
          {view === 'settings' && <div className="view on"><div className="card"><div className="stack" style={{ padding: '14px 16px 14px 84px' }}><div className="settings-rows">
            <div className="settings-row"><button className={'switch' + (sound ? ' on' : '')} aria-label="Som" aria-pressed={sound} onClick={() => setSound(v => !v)}/><span>Som</span><input aria-label="Volume" type="range" min="0" max="0.2" step="0.005" value={volume} style={{ opacity: sound ? 1 : .4 }} onChange={e => setVolume(Number(e.target.value))}/></div>
            <div className="settings-row"><Icon name="timer" size={12}/><span>Fechar automaticamente · {autoClose}s</span><div className="seg">{[10, 15, 30].map(n => <button key={n} className={autoClose === n ? 'on' : ''} onClick={() => setAutoClose(n)}>{n}s</button>)}</div></div>
            <div className="settings-row" style={{ gap: 14 }}><span className="status-badge"><i className="dot" style={{ width: 6, height: 6, background: fresh ? '#22C55E' : '#F4505E' }}/><span>Dots</span></span>
              <span className="status-badge"><i className="dot" style={{ width: 6, height: 6, background: snapshot.decisions ? '#F5A524' : '#22C55E' }}/><button className="link-btn" onClick={() => activate('decisions')} disabled={simulated}>Aprovações</button></span>
              <div className="grow"/><button className="link-btn" style={{ color: '#8e939c', fontSize: 11.5 }} onClick={() => activate('hub')} disabled={simulated}>Configurações…</button>
            </div>
          </div></div></div></div>}
        </div>
      </div></div>
      <div ref={glowNode} id="bot-glow" style={{ background: glow, opacity: botGlowOpacity(mainState) }}/>
      <div ref={figure} id="sentra-bot" role="button" tabIndex={0} aria-label={row ? `Abrir conversa de ${row.name}` : 'Abrir SENTRA'} onClick={() => expanded ? activate(row?.conversationId ? 'conversation' : 'show') : fsm.current?.click()} onKeyDown={e => { if (e.key === 'Enter') expanded ? activate('conversation') : fsm.current?.click(); }}>
        <Dot row={row} fresh={fresh} diameter="100%"/>
      </div>
      <div ref={grid} id="mini-grid" style={{ opacity: expanded ? 0 : 1 }} aria-hidden="true">{rows.slice(0, 4).map(item => <Dot key={item.dotId} row={item} fresh={fresh} diameter={13}/>)}</div>
      <div id="island-clock" style={{ opacity: !expanded && showClock ? 1 : 0, height: 32 }}>{new Date(clock).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })}  {new Date(clock).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
      {!expanded && <button className="coucou-compact di-capsule" aria-label="Expandir atividade dos Dots" onClick={() => fsm.current?.click()} onContextMenu={e => { e.preventDefault(); fsm.current?.forceHome(); setView('settings'); }}/>}
      <div ref={countdown} id="countdown"/>
    </div>
  </div>;
}
