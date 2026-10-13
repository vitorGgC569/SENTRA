import React, { useEffect, useState } from 'react';
import { shellBridge } from './shell-bridge';
import { Modal } from './primitives';

export function SkillLibraryDialog({ ws, close }) {
  const [items, setItems] = useState([]), [error, setError] = useState('');
  const [source, setSource] = useState('local'), [path, setPath] = useState('');
  const [sha, setSha] = useState(''), [folder, setFolder] = useState('');
  const [work, setWork] = useState(''), [agent, setAgent] = useState('');
  const [busy, setBusy] = useState(false), [preview, setPreview] = useState(null);
  const [pending, setPending] = useState(null);
  const [suggestion, setSuggestion] = useState(''), [learningReview, setLearningReview] = useState(null);
  async function refresh() { const result = await shellBridge({ project_id: ws, action: 'skill_list' }); setItems(result.items || []); }
  useEffect(() => { refresh().catch(e => setError(e.message)); }, [ws]);
  async function action(kind, parameters) {
    setBusy(true); setError('');
    try {
      const p = { ...parameters };
      if (kind === 'import') { p.source = p.path; delete p.path; }
      const payload = pending || { project_id: ws, action: 'skill_' + kind, ...p, request_key: crypto.randomUUID() };
      setPending(payload);
      const result = await shellBridge(payload);
      if (result.state === 'UNCERTAIN' || result.status === 'uncertain') { setError('Operação incerta; consulte a mesma chave.'); return; }
      setPending(null);
      const actualKind = payload.action.slice('skill_'.length);
      if (['disclose', 'review', 'versions', 'learning_review'].includes(actualKind)) setPreview(result); else await refresh();
      if (actualKind === 'learning_review') setLearningReview(result);
    } catch (e) { setError(e.message); if (!e.uncertain) setPending(null); } finally { setBusy(false); }
  }
  function importPackage(event) {
    event.preventDefault();
    action(source === 'local' ? 'import' : source, source === 'local' ? { path } :
      { repository: path, commit_sha: sha, subdirectory: folder });
  }
  return <Modal open onOpenChange={open => { if (!open) close(); }} title="Biblioteca de skills"
    description="Importe uma revisão e ative-a para uma tarefa. Os recursos são contexto e não concedem acesso à máquina.">
    <fieldset disabled={busy || Boolean(pending)} style={{ border: 0, padding: 0, margin: 0 }}><form onSubmit={importPackage} style={{ display: 'grid', gap: 9 }}>
      <label>Origem <select value={source} onChange={e => setSource(e.target.value)}>
        <option value="local">Pasta do workspace</option><option value="git">Git local</option>
        <option value="github">GitHub</option></select></label>
      <label>{source === 'github' ? 'Proprietário/repositório' : 'Caminho no workspace'}
        <input required value={path} onChange={e => setPath(e.target.value)} /></label>
      {source !== 'local' && <><label>Commit SHA completo
        <input required pattern="[a-f0-9]{40}" value={sha} onChange={e => setSha(e.target.value)} /></label>
        <label>Subpasta da skill <input value={folder} onChange={e => setFolder(e.target.value)} /></label></>}
      <button disabled={busy}>Importar revisão</button>
    </form></fieldset>
    <section style={{ display: 'grid', gap: 9, padding: '16px 0' }}>
      <strong>Aprendizado revisado</strong>
      <p>Uma sugestão Selo aprovada pode virar uma revisão inativa. A ativação continua explícita e exige as permissões existentes do WorkItem.</p>
      <label>Sugestão protegida <input value={suggestion} disabled={busy || Boolean(pending)} onChange={e => { setSuggestion(e.target.value); setLearningReview(null); }} /></label>
      <button disabled={busy || Boolean(pending) || !suggestion} onClick={() => action('learning_review', { suggestion_id: suggestion })}>Revisar SHA, origem e capabilities</button>
      {learningReview && <button disabled={busy || Boolean(pending)} onClick={() => action('learning_stage',
        { suggestion_id: suggestion, expected_sha256: learningReview.package_id, expected_review_revision: learningReview.review_revision })}>
        Importar esta revisão aprovada e inativa</button>}
    </section>
    <div style={{ display: 'grid', gap: 9, padding: '16px 0' }}>
      <label>Tarefa (WorkItem) <input value={work} onChange={e => setWork(e.target.value)} /></label>
      <label>Agente responsável <input value={agent} onChange={e => setAgent(e.target.value)} /></label>
      {pending && <div role="status">Resposta pendente · {pending.request_key}<button disabled={busy} onClick={() => action('', {})}>Consultar mesma intenção</button></div>}
      {items.map(item => <section key={item.package_id}>
        <strong>{item.name}</strong><p>{item.description}</p>
        <small>Revisão {item.package_id.slice(0, 12)} · {item.git_sha || 'snapshot local'}{item.revoked ? ' · revogada' : ''} · v{item.revision}</small>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button disabled={busy || item.revoked || !work || !agent} onClick={() => action('activate',
            { package_id: item.package_id, work_item_id: work, agent_id: agent })}>Ativar para a tarefa</button>
          <button disabled={busy || item.revoked || !work || !agent} onClick={() => action('disclose',
            { package_id: item.package_id, work_item_id: work, agent_id: agent })}>Ler SKILL.md</button>
          <button disabled={busy || item.revoked || !work || !agent} onClick={() => action('upgrade',
            { name: item.name, new_package_id: item.package_id, work_item_id: work, agent_id: agent })} title="Troca a ativação desta tarefa para esta revisão (mesmo nome e origem)">Atualizar ativação</button>
          <button disabled={busy || item.revoked} onClick={() => action('revoke',
            { package_id: item.package_id, expected_revision: item.revision })}>Revogar</button>
          <button disabled={busy || item.revoked} onClick={() => action('review',
            { package_id: item.package_id })}>Revisar</button>
          <button disabled={busy} onClick={() => action('versions', { name: item.name })}>Histórico de revisões</button>
          <button disabled={busy || !work || !agent} onClick={() => action('deactivate',
            { package_id: item.package_id, work_item_id: work, agent_id: agent })}>Desativar nesta tarefa</button>
          <button disabled={busy || item.revoked || !work || !agent} onClick={() => action('rollback',
            { name: item.name, previous_package_id: item.package_id, work_item_id: work, agent_id: agent })} title="Reverte a ativação desta tarefa para esta revisão anterior aprovada">Reverter para esta revisão</button>
        </div>
      </section>)}
      {preview && <pre tabIndex={0} style={{ maxHeight: 280, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{preview.content ?? JSON.stringify(preview, null, 2)}</pre>}
      {error && <p role="alert">{error}</p>}
    </div>
  </Modal>;
}
