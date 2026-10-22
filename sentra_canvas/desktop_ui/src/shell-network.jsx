import React, { useState } from 'react';
import { Monitor, Network, SlidersHorizontal } from 'lucide-react';
import { networkPayload, presentNetwork, presentNetworkResult } from './shell-network.js';

function linkWord(peer) {
  if (peer.paired && !peer.disconnected) return 'Conectado';
  if (peer.invite && !peer.paired) return 'Convite pendente';
  return 'Desconectado';
}

export function NetworkSurface({ document, bridge, spaceId, dots = [] }) {
  const [live, setLive] = useState(null);
  const view = presentNetwork(live || document);
  const [dotId, setDotId] = useState(dots[0]?.dot_id || '');
  const [address, setAddress] = useState('');
  const [port, setPort] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [nodeId, setNodeId] = useState('');
  const [text, setText] = useState('');
  const [task, setTask] = useState('');
  const [intentId, setIntentId] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState('');
  const scoped = Boolean(spaceId && dotId);
  async function send(action, extra = {}) {
    if (busy || !bridge) return;
    setBusy(true); setError('');
    try {
      const payload = networkPayload(action, { space_id: spaceId, dot_id: dotId, ...extra });
      const value = await bridge(payload);
      if (action === 'network_home' || action === 'network_status') {
        const next = presentNetwork(value);
        if (next.readFailure) {
          setError('A consulta da rede não chegou. A Home continua como estava.');
          return;
        }
        setLive(value);
        setNotice(null);
        return;
      }
      const shown = presentNetworkResult(value);
      if (shown.readFailure) {
        setNotice(null);
        setError('A consulta da rede não chegou. A Home continua como estava.');
        return;
      }
      if (shown.effectUncertain || !shown.ok) {
        setNotice(null);
        setError('O resultado ainda não está confirmado. Consulte o estado. Não repita o envio.');
        return;
      }
      setNotice(shown);
    } catch (failure) {
      setNotice(null);
      setError(failure.uncertain ? 'O resultado ainda não está confirmado. Consulte o estado. Não repita o envio.' : (failure.message || 'A ação de rede não foi concluída.'));
    } finally { setBusy(false); }
  }
  return <section className="shell-network" aria-label="Rede de Dots" data-renderer="lumen" data-physical-proof="false">
    <header>
      <span className="shell-eyebrow">SEUS COMPUTADORES, CONECTADOS</span>
      <h1>Trabalhe de qualquer lugar.</h1>
      <p>{view.readFailure ? 'A consulta da rede não chegou.' : view.enabled ? (view.listening ? 'Este projeto está na rede.' : 'A rede está ligada e sem escuta.') : 'A rede deste projeto está desligada.'} {view.disconnected ? 'Os computadores conhecidos estão desconectados.' : 'Há computador alcançável.'}</p>
    </header>
    <div className="shell-network-overview"><span className="shell-network-symbol"><Network size={24} /></span><div>
      <h2>{view.enabled ? 'Sua rede de trabalho' : 'Conecte outra máquina'}</h2>
      <p>Acompanhe seus Dots e compartilhe trabalho entre computadores autorizados.</p>
    </div><span className="shell-network-state"><i data-connected={view.enabled && view.listening ? 'true' : 'false'} />{view.enabled && view.listening ? 'Rede disponível' : 'Rede desligada ou sem escuta'}</span></div>
    <div className="shell-network-actions">
      <button type="button" disabled={busy || !bridge} onClick={() => void send('network_home')}>Consultar rede</button>
      <label>Dot deste projeto
        <select value={dotId} onChange={event => setDotId(event.target.value)} disabled={busy}>
          {!dots.length && <option value="">Nenhum Dot neste Space</option>}
          {dots.map(dot => <option key={dot.dot_id} value={dot.dot_id}>{dot.name}</option>)}
        </select>
      </label>
      <button type="button" disabled={busy || !scoped} onClick={() => void send('network_status')}>Consultar estado</button>
      <button type="button" disabled={busy || !scoped} onClick={() => void send('network_enable')}>Ligar rede</button>
      <button type="button" disabled={busy || !scoped} onClick={() => void send('network_disable')}>Desligar rede</button>
    </div>
    <details className="shell-network-connect"><summary><Monitor size={16} />Conectar um computador pelo endereço</summary>
    <form className="shell-network-invite" onSubmit={event => { event.preventDefault(); void send('network_invite', { address, port, ...(confirmation ? { confirmation } : {}) }); }}>
      <label>Endereço do outro computador<input value={address} autoComplete="off" disabled={busy} onChange={event => setAddress(event.target.value)} /></label>
      <label>Porta do outro computador<input value={port} inputMode="numeric" disabled={busy} onChange={event => setPort(event.target.value)} /></label>
      <label>Confirmação, se já houver<input value={confirmation} autoComplete="off" disabled={busy} onChange={event => setConfirmation(event.target.value)} /></label>
      <button type="submit" disabled={busy || !scoped || !address.trim() || !port.trim()}>Convidar</button>
    </form>
    </details>
    {view.peers.length ? <ul className="shell-network-dots">{view.peers.map((peer, index) => <li key={(peer.node_id || 'peer') + ':' + index}>
      <strong>{peer.node_id || 'Computador sem nome'}</strong>
      <span>{linkWord(peer)}</span>
      {peer.invite ? <span>Convite {peer.invite}</span> : null}
      <span>Sem execução neste computador</span>
      <button type="button" disabled={busy || !scoped || !peer.node_id} onClick={() => void send('network_revoke', { node_id: peer.node_id })}>Desparear</button>
    </li>)}</ul> : <p>Nenhum computador conhecido nesta consulta.</p>}
    <details className="shell-network-advanced"><summary><SlidersHorizontal size={16} />Coordenação avançada</summary>
    <form onSubmit={event => { event.preventDefault(); void send('network_converse', { node_id: nodeId, text }); }}>
      <label>Computador<input value={nodeId} disabled={busy} onChange={event => setNodeId(event.target.value)} /></label>
      <label>Mensagem<input value={text} disabled={busy} onChange={event => setText(event.target.value)} /></label>
      <button type="submit" disabled={busy || !scoped || !nodeId.trim() || !text.trim()}>Conversar</button>
    </form>
    <form onSubmit={event => { event.preventDefault(); void send('network_delegate', { node_id: nodeId, task }); }}>
      <label>Tarefa<input value={task} disabled={busy} onChange={event => setTask(event.target.value)} /></label>
      <button type="submit" disabled={busy || !scoped || !nodeId.trim() || !task.trim()}>Delegar</button>
    </form>
    <form onSubmit={event => { event.preventDefault(); void send('network_review', { node_id: nodeId, intent_id: intentId }); }}>
      <label>Intenção<input value={intentId} disabled={busy} onChange={event => setIntentId(event.target.value)} /></label>
      <button type="submit" disabled={busy || !scoped || !nodeId.trim() || !intentId.trim()}>Revisar</button>
    </form>
    </details>
    {notice?.inReview && notice.artifact && <article role="status"><h2>Em revisão</h2><p>{notice.artifact}</p></article>}
    {notice?.ok && !notice.inReview && <p role="status">{notice.disconnected ? 'Rede desconectada.' : notice.listening ? 'Rede ouvindo.' : 'Pedido registrado.'}</p>}
    {error && <p className="shell-error" role="alert">{error}</p>}
  </section>;
}
