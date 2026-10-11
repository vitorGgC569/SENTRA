import React, { useEffect, useState } from 'react';
import { api, route } from './api';
import { Modal } from './primitives';

/** Owner actions only. MCPB entries are metadata, never executable grants. */
export function PluginBundlesDialog({ ws, close }) {
  const [packages, setPackages] = useState([]);
  const [source, setSource] = useState(''), [sha, setSha] = useState('');
  const [approve, setApprove] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [message, setMessage] = useState('');
  const [inspection, setInspection] = useState(null);
  async function refresh() {
    const value = await api(route('/api/center/plugin-bundles', { ws }));
    setPackages(value.packages || []);
  }
  useEffect(() => { refresh().catch(e => setError(e.message)); }, [ws]);
  async function perform(action, extra = {}) {
    setBusy(true); setError(''); setMessage('');
    try {
      const value = await api('/api/center/plugin-bundles', {
        ws, action, approve: true, ...extra,
      });
      if (action === 'inspect') {
        setInspection(value);
        setMessage('Manifesto verificado. Nenhum processo foi iniciado.');
      } else {
        setInspection(null);
        setMessage(action === 'stage' ? 'Pacote importado e inativo.' :
          action === 'register' ? 'Plugin registrado no Control Plane, sem execução.' :
          'Registro desativado e sem permissão de execução.');
        if (action === 'stage') { setSource(''); setSha(''); setApprove(false); }
        await refresh();
      }
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const button = {padding:'8px 12px',borderRadius:8,
    border:'1px solid #43434a',background:'#27272b',color:'#f2f2f2',cursor:'pointer'};
  return <Modal open onOpenChange={open => { if (!open) close(); }}
    title="Pacotes MCP" description="Importação e registro verificados, sem execução automática.">
    <div style={{display:'grid',gap:12,maxWidth:490,padding:'4px 0 16px'}}>
      <label style={{fontSize:12}}>Arquivo .mcpb no workspace
        <input aria-label="Arquivo MCPB" value={source}
          onChange={e => setSource(e.target.value)} maxLength={4096}
          placeholder="plugins/servidor.mcpb"
          style={{display:'block',width:'100%',padding:10,marginTop:6,
            background:'#202024',border:'1px solid #45454c',borderRadius:8,color:'#f3f3f3'}}/>
      </label>
      <label style={{fontSize:12}}>SHA-256 esperado (opcional)
        <input aria-label="SHA-256 esperado" value={sha} maxLength={64}
          onChange={e => setSha(e.target.value)} placeholder="64 caracteres hexadecimais"
          style={{display:'block',width:'100%',padding:10,marginTop:6,
            background:'#202024',border:'1px solid #45454c',borderRadius:8,color:'#f3f3f3'}}/>
      </label>
      <label style={{display:'flex',alignItems:'center',gap:9,fontSize:12}}>
        <input type="checkbox" checked={approve} onChange={e => setApprove(e.target.checked)}/>
        Autorizo apenas a importação, sem execução ou concessão de acesso.
      </label>
      <button style={button} disabled={busy || !approve || !source.trim()}
        onClick={() => perform('stage',{source,expected_sha256:sha.trim() || null})}>
        Importar inativo
      </button>
      <div style={{display:'grid',gap:8}}>
        <strong style={{fontSize:12}}>Pacotes no workspace</strong>
        {!packages.length && <small style={{color:'#a9a9b1'}}>Nenhum pacote importado.</small>}
        {packages.map(pkg => {
          const state = pkg.registration?.status;
          return <section key={pkg.package_sha256} style={{display:'grid',gap:9,
            padding:12,borderRadius:8,background:'#202024',border:'1px solid #36363b'}}>
            <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:12}}>
              <strong style={{fontSize:13}}>{pkg.name} <span style={{fontWeight:400,opacity:.7}}>{pkg.version}</span></strong>
              <small style={{opacity:.7}}>{state === 'REGISTERED' ? 'Registrado' :
                state === 'DISABLED' ? 'Desativado' : 'Inativo'}</small>
            </div>
            <small style={{fontFamily:'monospace',opacity:.7}}>{pkg.package_sha256.slice(0,20)}</small>
            <div style={{display:'flex',flexWrap:'wrap',gap:6}}>
              <button style={button} disabled={busy}
                onClick={() => perform('inspect',{package_sha256:pkg.package_sha256})}>Verificar</button>
              {!state && <button style={button} disabled={busy}
                onClick={() => perform('register',{package_sha256:pkg.package_sha256})}>Registrar no SENTRA</button>}
              {state === 'REGISTERED' && <button style={button} disabled={busy}
                onClick={() => perform('disable',{package_sha256:pkg.package_sha256})}>Desativar registro</button>}
            </div>
            {pkg.registration?.plugin_id && <small style={{color:'#b1b1b8'}}>
              Control Plane: {pkg.registration.plugin_id}</small>}
          </section>;
        })}
      </div>
      {inspection && <div style={{borderTop:'1px solid #35353b',paddingTop:10}}>
        <strong style={{fontSize:12}}>Manifesto conferido</strong>
        <p style={{fontSize:12,marginTop:8}}>{inspection.name} {inspection.version} · {inspection.server_type} · {inspection.entry_point}</p>
        <small style={{color:'#b1b1b8'}}>Autor: {inspection.author_name}. Configuração exigida: {inspection.required_user_config_keys.join(', ') || 'nenhuma'}.</small>
      </div>}
      <small style={{color:'#a9a9b1'}}>Servidores MCPB padrão dependem de um executor MCP stdio autorizado; registrar não os inicia nem expõe ferramentas no ChatGPT.</small>
      {message && <p role="status" style={{color:'#8fd8b6'}}>{message}</p>}
      {error && <p role="alert" style={{color:'#ffa29e'}}>{error}</p>}
    </div>
  </Modal>;
}
