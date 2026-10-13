import React, { useEffect, useRef, useState } from 'react';
import { Download, FileText, RefreshCw } from 'lucide-react';
import { apiBinary, route } from './api';

function GeneratedAsset({ asset, message, scope }) {
  const [url, setUrl] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const current = useRef(null), alive = useRef(true), loading = useRef(false);
  const image = ['image/png', 'image/jpeg'].includes(asset.mime_type);
  async function load() {
    if (loading.current || current.current) return current.current;
    loading.current = true; setBusy(true); setError('');
    try {
      const blob = await apiBinary(route('/api/shell/generated-media', { ...scope,
        message_id: message.message_id, asset_id: asset.asset_id }), { maxBytes: asset.byte_length });
      const bytes = await blob.arrayBuffer();
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), n => n.toString(16).padStart(2, '0')).join('');
      if (blob.size !== asset.byte_length || blob.type !== asset.mime_type || hash !== asset.sha256) throw Error('A integridade do arquivo não foi confirmada.');
      if (!alive.current) return null;
      const value = URL.createObjectURL(blob); current.current = value; setUrl(value); return value;
    } catch (e) { if (alive.current) setError(e.message); return null; }
    finally { loading.current = false; if (alive.current) setBusy(false); }
  }
  useEffect(() => {
    alive.current = true;
    if (image) void load();
    return () => { alive.current = false; if (current.current) URL.revokeObjectURL(current.current); current.current = null; };
  }, [asset.asset_id, asset.sha256]);
  async function download() {
    const value = current.current || await load();
    if (!value) return;
    const link = document.createElement('a'); link.href = value; link.download = asset.filename;
    link.click();
  }
  return <figure className="shell-generated-asset">
    {image && url ? <img src={url} alt={asset.filename} loading="lazy" /> : !image && <FileText size={24} />}
    <figcaption><span>{asset.filename}<small>{(asset.byte_length / 1024).toFixed(0)} KiB · recebido</small></span>
      <button type="button" disabled={busy} onClick={() => void download()} aria-label={'Baixar ' + asset.filename}><Download size={15} />Baixar</button></figcaption>
    {busy && <small>Recebendo arquivo…</small>}
    {error && <p className="shell-error" role="alert">{error}<button type="button" onClick={() => void load()}><RefreshCw size={13} />Consultar arquivo</button></p>}
  </figure>;
}

export function ShellGeneratedAssets({ message, scope }) {
  if (!message.generated_assets?.length) return null;
  return <div className="shell-generated-assets" aria-label="Arquivos recebidos do ChatGPT">{message.generated_assets.map(asset =>
    <GeneratedAsset key={asset.asset_id + ':' + asset.sha256} asset={asset} message={message} scope={scope} />)}</div>;
}
