import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import './desktop.css';
import { DOT_MASCOTS, DotMascot } from './shell-mascot';

if (location.search.includes('reduced')) {
  const query = { matches: true, media: '(prefers-reduced-motion: reduce)', addEventListener() {}, removeEventListener() {} };
  window.matchMedia = () => query;
}

const states = ['idle', 'working', 'needs_input', 'paused', 'completed'];

function Board() {
  const [live, setLive] = useState('idle');
  const [color, setColor] = useState('blue');
  return <div className="opendots-shell" style={{ display: 'block', height: 'auto', overflow: 'auto' }}>
    <div className="shell-mascot-picker" data-preview="picker"><div>{DOT_MASCOTS.map(item => <button type="button" key={item.id} onClick={() => setColor(item.id)}><img src={item.image} alt="" width="60" height="60" /><span>{item.label}</span></button>)}</div></div>
    {states.map(status => <section key={status} style={{ display: 'flex', gap: 16, alignItems: 'end', padding: 10 }}>
      <strong style={{ width: 110 }}>{status}</strong>
      {DOT_MASCOTS.map(item => <div key={item.id} style={{ display: 'flex', gap: 8, alignItems: 'end' }}>
        <div data-shot={item.id + '-' + status + '-nav'}><DotMascot mascot={item.id} name={item.label} status={status} execution={status === 'working' ? { validated: true, workItemState: 'RUNNING', operationState: 'RUNNING' } : undefined} size="nav" /></div>
        <div data-shot={item.id + '-' + status + '-small'}><DotMascot mascot={item.id} name={item.label} status={status} execution={status === 'working' ? { validated: true, workItemState: 'RUNNING', operationState: 'RUNNING' } : undefined} size="small" /></div>
      </div>)}
    </section>)}
    <section style={{ display: 'flex', gap: 16, padding: 10 }}>
      {DOT_MASCOTS.map(item => <DotMascot key={item.id} mascot={item.id} name={item.label} status="idle" size="hero" />)}
    </section>
    <div data-live="1">
      <DotMascot mascot={color} name="Ao vivo" status={live} execution={live === 'working' ? { validated: true, workItemState: 'RUNNING', operationState: 'RUNNING' } : undefined} size="hero" />
      {states.map(status => <button type="button" key={status} data-set={status} onClick={() => setLive(status)}>{status}</button>)}
    </div>
  </div>;
}

createRoot(document.getElementById('root')).render(<Board />);
