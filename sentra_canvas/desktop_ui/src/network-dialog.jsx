import React, { useEffect, useRef, useState } from 'react';
import { api, route } from './api';
import { Modal, Field } from './primitives';
import { useDesktop } from './context';

function ipv4(text) {
  const parts = text.split('.');
  return parts.length === 4 && parts.every(p => /^(0|[1-9]\d{0,2})$/.test(p) && Number(p) <= 255) &&
    text !== '0.0.0.0' && Number(parts[0]) < 224;
}
export function NetworkDialog({ close }) {
  const { ws, notify } = useDesktop();
  const [loaded, setLoaded] = useState(null), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [enabled, setEnabled] = useState(false), [adapter, setAdapter] = useState('hamachi');
  const [local, setLocal] = useState(''), [ips, setIPs] = useState(''), [port, setPort] = useState('37037');
  const [label, setLabel] = useState(''), [meshKey, setMeshKey] = useState('');
  const [pairing, setPairing] = useState(null), [pairingBusy, setPairingBusy] = useState(false);
  const current = useRef(true), pairField = useRef(null);
  function accept(result, updateForm = true) {
    const configuration = result.configuration;
    if (!configuration || !Number.isInteger(configuration.revision)) throw Error('A API não retornou a revisão da configuração.');
    setLoaded(previous => !updateForm && previous ? { ...result, configuration: previous.configuration } : result);
    if (!updateForm && loaded && configuration.revision !== loaded.configuration.revision) {
      setError('A configuração foi alterada em outra sessão. Recarregue a configuração antes de salvar.');
    }
    if (updateForm) {
      setEnabled(configuration.enabled === true); setAdapter(configuration.adapter_kind);
      setLocal(configuration.interface_address || ''); setIPs((configuration.allowed_ips || []).join('\n'));
      setPort(String(configuration.port)); setLabel(configuration.label || '');
      setMeshKey(''); setPairing(null);
    }
  }
  async function load(updateForm = true) {
    if (!ws) { setError('Selecione um workspace.'); setLoading(false); return; }
    setLoading(true); setError('');
    try { const result = await api(route('/api/center/network', { ws })); if (current.current) accept(result, updateForm); }
    catch (e) { if (current.current) setError(e.message); }
    finally { if (current.current) setLoading(false); }
  }
  useEffect(() => { current.current = true; load(); return () => { current.current = false; }; }, [ws]);
  async function save(e) {
    e.preventDefault(); if (!loaded || busy) return;
    setBusy(true); setError(''); setPairing(null);
    try {
      const allowed = [...new Set(ips.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean))];
      if (allowed.length > 128 || allowed.some(ip => !ipv4(ip))) throw Error('Informe até 128 endereços IPv4 válidos, um por linha.');
      if (local.trim() && !ipv4(local.trim())) throw Error('Informe um IPv4 válido para a interface local.');
      if (enabled && (!local.trim() || !allowed.length)) throw Error('Para ligar, preencha a interface local e ao menos um IP permitido.');
      const numericPort = Number(port);
      if (!Number.isInteger(numericPort) || numericPort < 1 || numericPort > 65535) throw Error('A porta deve estar entre 1 e 65535.');
      if (!label.trim() || label.trim().length > 80) throw Error('Informe um nome de até 80 caracteres.');
      const configuration = { enabled, adapter_kind: adapter, interface_address: local.trim(),
        allowed_ips: allowed, port: numericPort, label: label.trim(), expected_revision: loaded.configuration.revision };
      if (meshKey) {
        const bytes = new TextEncoder().encode(meshKey).length;
        if (bytes < 32 || bytes > 256) throw Error('A chave de pareamento aceita de 32 a 256 bytes.');
        configuration.mesh_key = meshKey;
      }
      const result = await api('/api/center/network', { ws, configuration });
      if (current.current) { accept(result); notify('Configuração de rede salva na revisão ' + result.configuration.revision + '.'); }
    } catch (e) { if (current.current) setError(e.message); }
    finally { if (current.current) setBusy(false); }
  }
  async function revealPairing() {
    setPairingBusy(true); setError('');
    try {
      const result = await api('/api/center/network/pairing', { ws });
      if (typeof result.mesh_key !== 'string' || !Number.isInteger(result.port)) throw Error('Pareamento indisponível.');
      if (current.current) setPairing({ key: result.mesh_key, port: result.port, purpose: result.purpose });
    } catch {
      if (current.current) setError('Não foi possível consultar o pareamento. Salve a configuração e confira a autorização do proprietário.');
    } finally { if (current.current) setPairingBusy(false); }
  }
  const presence = loaded?.presence;
  const peers = Array.isArray(presence?.peers) ? presence.peers : [];
  const interfaces = Array.isArray(loaded?.local_interfaces) ? loaded.local_interfaces : [];
  const detectedIndex = interfaces.findIndex(item => item.address === local && item.adapter_kind === adapter);
  return <Modal open busy={busy || pairingBusy} onOpenChange={v => { if (!v) close(); }} title="Rede"
    description="Configuração do workspace para Hamachi, Radmin ou interface manual." className="network-dialog">
    {loading && <p className="form-help">Consultando configuração…</p>}
    {loaded && <div className="network-config-summary">
      <span>Configuração · revisão {loaded.configuration.revision}</span>
      <code>{loaded.configuration.interface_address || 'Interface não configurada'}:{loaded.configuration.port}</code>
    </div>}
    <form onSubmit={save} autoComplete="off">
      <fieldset className="dialog-fields" disabled={busy || loading || pairingBusy || !loaded}>
        <label className="checkbox-field"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /> Ligar presença de rede</label>
        <Field label="Adaptador"><select value={adapter} onChange={e => setAdapter(e.target.value)}>
          <option value="hamachi">LogMeIn Hamachi</option><option value="radmin">Radmin VPN</option><option value="manual">Interface manual</option>
        </select></Field>
        <Field label="Interface detectada" hint={!loaded ? 'Carregue a configuração para editar a interface.' :
          interfaces.length ? 'Dados dos adaptadores locais. Não comprovam um par autenticado.' : 'A API não informou interfaces Hamachi/Radmin. A entrada manual continua disponível.'}>
          <select value={detectedIndex < 0 ? 'manual' : String(detectedIndex)} onChange={e => {
            if (e.target.value === 'manual') { setAdapter('manual'); return; }
            const selected = interfaces[Number(e.target.value)];
            if (!selected) return;
            setLocal(selected.address);
            if (['hamachi', 'radmin', 'manual'].includes(selected.adapter_kind)) setAdapter(selected.adapter_kind);
          }}>
            <option value="manual">Entrada manual</option>
            {interfaces.map((item, i) => <option key={item.address + ':' + i} value={String(i)}>
              {item.name || item.description || item.adapter_kind} · {item.address}
            </option>)}
          </select>
        </Field>
        <div className="network-field-row">
          <Field label="IPv4 da interface local"><input value={local} onChange={e => setLocal(e.target.value)} placeholder="IP atribuído à interface VPN" inputMode="decimal" /></Field>
          <Field label="Porta"><input type="number" min={1} max={65535} value={port} onChange={e => setPort(e.target.value)} required /></Field>
        </div>
        <Field label="IPs permitidos" hint="Um IPv4 por linha. Pode salvar a lista vazia com a presença desligada.">
          <textarea value={ips} onChange={e => setIPs(e.target.value)} rows={4} placeholder="IPs fornecidos pelos participantes" />
        </Field>
        <Field label="Nome deste ponto"><input value={label} onChange={e => setLabel(e.target.value)} maxLength={80} required /></Field>
        <details className="network-pairing"><summary>Pareamento do proprietário</summary>
          <Field label="Chave para ingressar em projeto pareado (opcional)" hint="Deixe vazio para manter a chave protegida já cadastrada. A consulta normal nunca retorna seu conteúdo.">
            <input type="password" autoComplete="new-password" value={meshKey} onChange={e => setMeshKey(e.target.value)} />
          </Field>
          <small>{loaded?.pairing_key_configured === true ? 'A API informa uma chave cadastrada.' :
            loaded?.pairing_key_configured === false ? 'A API informa que não há chave cadastrada.' : 'Estado da chave não informado.'}</small>
        </details>
      </fieldset>
      {error && <p className="form-error" role="alert">{error}</p>}
      <footer className="dialog-actions"><button type="button" disabled={busy || pairingBusy} onClick={() => load()}>Recarregar configuração</button>
        <button type="submit" className="primary" disabled={busy || loading || pairingBusy || !loaded}>{busy ? 'Salvando…' : 'Salvar'}</button></footer>
    </form>
    {loaded && <section className="network-pairing-reveal">
      <button type="button" disabled={busy || loading || pairingBusy || loaded.configuration.revision < 1}
        onClick={revealPairing}>{pairingBusy ? 'Consultando…' : 'Código de pareamento'}</button>
      {pairing && <div className="pairing-code">
        <label>Código protegido do proprietário<input ref={pairField} type="text" value={pairing.key || ''} readOnly autoComplete="off" spellCheck={false} /></label>
        <small>Porta informada: {pairing.port}. Compartilhe somente com o proprietário da outra máquina.</small>
        <div className="dialog-actions"><button type="button" onClick={async () => {
          try {
            if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(pairing.key);
            else { pairField.current.focus(); pairField.current.select(); return; }
            notify('Código copiado.');
          } catch { pairField.current.focus(); pairField.current.select(); }
        }}>Copiar código</button><button type="button" onClick={() => setPairing(null)}>Ocultar código</button></div>
      </div>}
    </section>}
    {loaded && <section className="network-presence" aria-label="Presença informada pelo runtime">
      <h3>Presença</h3>
      <p>{presence?.running === true ? 'Serviço de presença em execução.' : presence?.running === false ? 'Serviço de presença parado.' : 'Estado de presença não informado.'}</p>
      <p>{loaded.collaboration_transport_ready === false ? 'A colaboração ainda não está ligada a este transporte.' :
        loaded.collaboration_transport_ready === true ? 'A API informa transporte de colaboração ligado.' : 'Estado do transporte de colaboração não informado.'}</p>
      {loaded.error && <p className="form-error">{typeof loaded.error === 'string' ? loaded.error : loaded.error.status || loaded.error.type || 'A API retornou um erro de rede.'}</p>}
      {peers.length ? <ul className="network-peers">{peers.map((peer, i) =>
        <li key={peer.node_id || peer.id || i}><strong>{peer.label || peer.node_id || peer.id || 'Par informado'}</strong>
          <code>{peer.address || peer.ip || 'Endereço não informado'}{peer.port ? ':' + peer.port : ''}</code>
          {peer.state && <small>Estado registrado: {peer.state}</small>}
        </li>)}</ul> : <p>Nenhum par retornado nesta consulta.</p>}
      <button type="button" disabled={busy || loading || pairingBusy} onClick={() => load(false)}>Atualizar presença</button>
    </section>}
  </Modal>;
}
