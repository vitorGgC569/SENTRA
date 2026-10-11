import React, { useEffect, useState } from 'react';
import { api, route } from './api';
import { Modal } from './primitives';

export function SkillLibraryDialog({ ws, close }) {
  const [items, setItems] = useState([]), [error, setError] = useState('');
  const [source, setSource] = useState('local'), [path, setPath] = useState('');
  const [sha, setSha] = useState(''), [folder, setFolder] = useState('');
  const [work, setWork] = useState(''), [agent, setAgent] = useState('');
  const [busy, setBusy] = useState(false), [preview, setPreview] = useState(null);
  async function refresh() { const result = await api(route('/api/center/skill-library', { ws })); setItems(result.items); }
  useEffect(() => { refresh().catch(e => setError(e.message)); }, [ws]);
  async function action(kind, parameters) {
    setBusy(true); setError('');
    try {
      const result = await api('/api/center/skill-library', { ws, approve: true, action: kind, parameters });
      if (kind === 'disclose') setPreview(result); else await refresh();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  function importPackage(event) {
    event.preventDefault();
    action(source === 'local' ? 'import' : source, source === 'local' ? { path } :
      { repository: path, commit_sha: sha, subdirectory: folder });
  }
  return <Modal open onOpenChange={open => { if (!open) close(); }} title="Biblioteca de skills"
    description="Importe uma revisão e ative-a para uma tarefa. Os recursos são contexto e não concedem acesso à máquina.">
    <form onSubmit={importPackage} style={{ display: 'grid', gap: 9 }}>
      <label>Origem <select value={source} onChange={e => setSource(e.target.value)}>
        <option value="local">Pasta do workspace</option><option value="git">Git local</option>
        <option value="github">GitHub</option></select></label>
      <label>{source === 'github' ? 'Proprietário/repositório' : 'Caminho no workspace'}
        <input required value={path} onChange={e => setPath(e.target.value)} /></label>
      {source !== 'local' && <><label>Commit SHA completo
        <input required pattern="[a-f0-9]{40}" value={sha} onChange={e => setSha(e.target.value)} /></label>
        <label>Subpasta da skill <input value={folder} onChange={e => setFolder(e.target.value)} /></label></>}
      <button disabled={busy}>Importar revisão</button>
    </form>
    <div style={{ display: 'grid', gap: 9, padding: '16px 0' }}>
      <label>Tarefa (WorkItem) <input value={work} onChange={e => setWork(e.target.value)} /></label>
      <label>Agente responsável <input value={agent} onChange={e => setAgent(e.target.value)} /></label>
      {items.map(item => <section key={item.package_id}>
        <strong>{item.name}</strong><p>{item.description}</p>
        <small>Revisão {item.package_id.slice(0, 12)} · {item.git_sha || 'snapshot local'}{item.revoked ? ' · revogada' : ''}</small>
        <div style={{ display: 'flex', gap: 8 }}>
          <button disabled={busy || item.revoked || !work || !agent} onClick={() => action('activate',
            { package_id: item.package_id, work_item_id: work, agent_id: agent })}>Ativar para a tarefa</button>
          <button disabled={busy || item.revoked || !work || !agent} onClick={() => action('disclose',
            { package_id: item.package_id, work_item_id: work, agent_id: agent })}>Ler SKILL.md</button>
          <button disabled={busy || item.revoked} onClick={() => action('revoke',
            { package_id: item.package_id, expected_revision: item.revision })}>Revogar</button>
        </div>
      </section>)}
      {preview && <pre tabIndex={0} style={{ maxHeight: 280, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{preview.content}</pre>}
      {error && <p role="alert">{error}</p>}
    </div>
  </Modal>;
}
