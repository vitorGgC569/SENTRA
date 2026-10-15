import React, { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { feedMotion, homeFrame, HOME_LOADING, SurfaceMotion, useReducedMotion } from './index.js';
import { moveRoving, tabIndexFor } from './keyboard.js';
import './cadence.css';

const ROWS = ['Sentra Aqrt', 'testegpt6', 'Testando Advanced', 'SubAgenteGPT6', 'Teste', 'dasdas'];

function Preview() {
  const reduced = useReducedMotion();
  const [forced, setForced] = useState(null);
  const calm = forced == null ? reduced : forced;
  const [mode, setMode] = useState('loading');
  const [view, setView] = useState('home');
  const [from, setFrom] = useState('home');
  const [index, setIndex] = useState(0);
  const rows = useRef([]);
  const [shown, setShown] = useState('');
  const [beat, setBeat] = useState(() => feedMotion({ status: 'generating', activity: 'Coordenando', content: '' }));
  const frame = homeFrame({
    loading: mode === 'loading',
    settled: mode === 'ready' || mode === 'empty',
    readError: mode === 'error' ? 'não confirmado' : '',
    empty: mode === 'empty',
  });
  const motion = SurfaceMotion({ reduced: calm, from, to: view });
  const tabs = tabIndexFor(ROWS.length, index);
  function go(next) {
    setFrom(view);
    setView(next);
  }
  function onKeys(event) {
    const move = moveRoving({ index, count: ROWS.length, key: event.key, orientation: 'vertical' });
    if (!move) return;
    event.preventDefault();
    setIndex(move.index);
    rows.current[move.index]?.focus();
  }
  function grow(content, activity) {
    setBeat(current => feedMotion({ status: 'generating', activity, content }, current));
    setShown(content);
  }
  return <main className="cadence-root cadence-surface" data-reduced={calm ? 'true' : 'false'} data-motion={calm ? 'off' : 'on'} data-dir={motion.dir}
    style={{ minHeight: '100vh', padding: 28, background: '#16171b', color: '#f4f1ea', fontFamily: '"Segoe UI", system-ui, sans-serif' }}>
    <p style={{ letterSpacing: '0.08em', fontSize: 12, color: '#b7b3a8' }}>PREVIEW DE MOVIMENTO · NÃO É O SHELL 50282</p>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '12px 0 20px' }}>
      <button type="button" onClick={() => setMode('loading')}>Consulta</button>
      <button type="button" onClick={() => setMode('ready')}>Home assentada</button>
      <button type="button" onClick={() => setMode('error')}>Leitura falhou</button>
      <button type="button" onClick={() => setMode('empty')}>Projeto vazio</button>
      <button type="button" onClick={() => go(view === 'home' ? 'conversations' : 'home')}>Trocar superfície</button>
      <button type="button" onClick={() => setForced(value => !value)}>Reduced {calm ? 'ligado' : 'desligado'}</button>
    </div>
    {frame.show === 'loading' && <p className="cadence-loading" role="status" aria-busy="true">{HOME_LOADING}</p>}
    {frame.show === 'read-error' && <div className="cadence-read-error" role="alert" data-mutation="false" data-resend="false">
      <strong>{frame.headline}</strong><p>{frame.happened}</p><p>{frame.safeNext}</p>
      <button type="button" onClick={() => setMode('loading')}>Consultar de novo</button>
    </div>}
    {frame.showBoard && <section aria-label="Dots recentes">
      <h1 style={{ fontSize: 28, margin: '8px 0' }}>O que vamos fazer hoje?</h1>
      {frame.showEmpty ? <p>Ainda não há Dots neste projeto.</p> : <div className="shell-home-list" role="listbox" aria-label="Dots recentes" onKeyDown={onKeys} style={{ display: 'grid', gap: 8, maxWidth: 640 }}>
        {ROWS.map((name, item) => <button type="button" key={name} role="option" ref={element => { rows.current[item] = element; }} aria-selected={item === index} tabIndex={tabs[item]}
          onClick={() => setIndex(item)} onKeyDown={onKeys} style={{ height: 'max-content', maxHeight: 56, display: 'flex', justifyContent: 'space-between', padding: '8px 12px', borderRadius: 12, border: '1px solid #9a9a9a', background: '#202020', color: '#f4f1ea' }}>
          <strong>{name}</strong><small>Trabalhando</small>
        </button>)}
      </div>}
    </section>}
    <section aria-label="Feed" style={{ marginTop: 28, maxWidth: 640 }}>
      <h2 style={{ fontSize: 16 }}>Feed parcial</h2>
      <p data-phase={beat.phase} data-resend="false">{beat.activity || 'idle'} · {beat.phase}</p>
      <p>{shown}</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" onClick={() => grow('', 'Coordenando')}>Coordenando</button>
        <button type="button" onClick={() => grow('ha', 'Recebendo resposta')}>ha</button>
        <button type="button" onClick={() => grow('haha', 'Recebendo resposta')}>haha</button>
        <button type="button" onClick={() => setBeat(current => feedMotion({ status: 'generating', activity: 'Entrega incerta. Não reenvie.', content: shown }, current))}>Entrega incerta</button>
      </div>
    </section>
  </main>;
}

createRoot(document.getElementById('root')).render(<Preview />);
