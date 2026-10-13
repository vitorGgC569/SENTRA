import React, {useCallback, useEffect, useRef, useState} from 'react';
import {DocumentRichEditor} from './document-rich-editor.jsx';
import {DocumentCodeEditor} from './document-code-editor.jsx';
import {DocumentProjectFiles} from './document-project-files.jsx';
import {draftKey, draftStore} from './document-drafts.js';
import {connectDocument} from './collaboration-document.js';
import './document-panel.css';

const value = result => result?.value ?? result;
const noop = () => {};
const labels = {dirty: 'Alterações pendentes', saving: 'Salvando…', saved: 'Salvo', error: 'Falha ao salvar', conflict: 'Conflito de versão', loading: 'Abrindo…', collaborative: 'Colaboração ativa'};
export function ProjectDocuments({bridge, spaceId, projectId, documents, onRefresh = noop, onError = noop, onDirtyChange = noop}) {
  const [scope, setScope] = useState({spaceId, projectId});
  const [items, setItems] = useState(documents?.items ?? documents ?? []);
  const [document, setDocument] = useState(null), [draft, setDraft] = useState(null);
  const [status, setStatus] = useState('saved'), [error, setError] = useState('');
  const [mode, setMode] = useState('rich'), [history, setHistory] = useState([]), [diff, setDiff] = useState('');
  const [historyCursor, setHistoryCursor] = useState(null);
  const [recovery, setRecovery] = useState(null), [presence, setPresence] = useState([]), [collabStatus, setCollabStatus] = useState(null);
  const [nextCursor, setNextCursor] = useState(null), [showFiles, setShowFiles] = useState(false);
  const [pendingCommand, setPendingCommand] = useState(null);
  const generation = useRef(0), current = useRef({}), attempt = useRef(null), collaboration = useRef(null);
  const commandBusy = useRef(false);
  const callbacks = useRef({}); callbacks.current = {bridge, onRefresh, onError, onDirtyChange};
  current.current = {document, draft, status, scope, pendingCommand};
  const dirty = Boolean(pendingCommand) || status === 'dirty' || status === 'saving' || status === 'error' || status === 'conflict';
  const report = useCallback(e => { setError(e.message); callbacks.current.onError(e); }, []);
  const request = useCallback(payload => callbacks.current.bridge({project_id: scope.projectId, space_id: scope.spaceId,
    request_key: crypto.randomUUID(), ...payload}).then(value), [scope.projectId, scope.spaceId]);
  const stopCollaboration = useCallback(() => { collaboration.current?.close(); collaboration.current = null; setCollabStatus(null); setPresence([]); }, []);
  const guard = () => !dirty || window.confirm('Há alterações não confirmadas. Preservar o rascunho e trocar de documento?');
  const refresh = useCallback(async (cursor = null) => {
    const result = await request({action: 'document_list', ...(cursor ? {cursor} : {})});
    setItems(old => cursor ? [...old, ...result.items] : result.items); setNextCursor(result.next_cursor); callbacks.current.onRefresh(result);
  }, [request]);
  useEffect(() => {
    if (spaceId === scope.spaceId && projectId === scope.projectId) return;
    if (callbacks.current.onDirtyChange === noop && !guard()) return;
    generation.current++; stopCollaboration(); setDocument(null); setDraft(null); setRecovery(null); attempt.current = null;
    setStatus('saved'); setScope({spaceId, projectId});
  }, [spaceId, projectId, scope, dirty, stopCollaboration]);
  useEffect(() => {
    let live = true;
    draftStore('get', draftKey(scope.projectId, scope.spaceId, '__commands__')).then(stored => {
      if (live) setPendingCommand(stored?.command ?? null);
    }).catch(report);
    if (scope.spaceId && scope.projectId) request({action: 'document_list'}).then(r => { if (live) {setItems(r.items); setNextCursor(r.next_cursor);} }).catch(e => {if (live) report(e);});
    return () => {live = false;};
  }, [request, report, scope]);
  useEffect(() => { callbacks.current.onDirtyChange({dirty, status, documentId: document?.document_id, spaceId: scope.spaceId, projectId: scope.projectId}); }, [dirty, status, document?.document_id, scope]);
  useEffect(() => {
    const listener = e => { if (current.current.pendingCommand || ['dirty', 'saving', 'error', 'conflict'].includes(current.current.status)) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', listener);
    return () => {window.removeEventListener('beforeunload', listener); collaboration.current?.close();};
  }, []);
  useEffect(() => {
    if (!dirty || !document || !draft) return;
    draftStore('put', draftKey(scope.projectId, scope.spaceId, document.document_id), {
      draft, expectedRevision: document.revision, attempt: attempt.current,
    }).catch(report);
  }, [dirty, draft, document, scope, report]);
  const open = async id => {
    if (!guard()) return;
    const token = ++generation.current; stopCollaboration(); setStatus('loading'); setError(''); setHistory([]); setDiff('');
    try {
      const selected = await request({action: 'document_get', document_id: id});
      const recovered = await draftStore('get', draftKey(scope.projectId, scope.spaceId, id));
      if (generation.current !== token) return;
      setDocument(selected); setDraft(selected); setRecovery(recovered); setStatus('saved'); attempt.current = null;
      setMode(selected.format === 'markdown' ? 'rich' : 'source');
    } catch (e) {if (generation.current === token) {setStatus('error'); report(e);} }
  };
  const edit = patch => {
    if (collaboration.current) {
      if (patch.content !== undefined) {
        try { collaboration.current.setContent(patch.content); } catch (e) {report(e);}
      }
      return;
    }
    setDraft(old => ({...old, ...patch})); setStatus('dirty'); setError('');
  };
  const save = useCallback(async () => {
    const live = current.current;
    if (!live.document || !live.draft || collaboration.current || live.status === 'saving' || live.status === 'conflict') return;
    const token = generation.current;
    const snapshot = attempt.current?.draft ?? {...live.draft};
    const body = attempt.current?.body ?? {action: 'document_save', document_id: live.document.document_id,
      title: snapshot.title, content: snapshot.content, format: snapshot.format, language: snapshot.language,
      parent_id: snapshot.parent_id, expected_revision: live.document.revision, mutation_id: crypto.randomUUID()};
    body.request_key = body.mutation_id;
    attempt.current = {body, draft: snapshot}; setStatus('saving');
    try {
      await draftStore('put', draftKey(live.scope.projectId, live.scope.spaceId, live.document.document_id), {
        draft: live.draft, expectedRevision: live.document.revision, attempt: attempt.current,
      });
      const saved = await request(body);
      if (generation.current !== token) return;
      if (!saved.receipt_id || !saved.committed) throw Error('Salvamento ainda não confirmado por recibo.');
      attempt.current = null; setDocument(saved);
      const latest = current.current.draft;
      const changed = ['content', 'title', 'format', 'language', 'parent_id'].some(k => latest[k] !== snapshot[k]);
      if (changed) {setDraft({...latest, revision: saved.revision}); setStatus('dirty');}
      else {setDraft(saved); setStatus('saved'); await draftStore('delete', draftKey(live.scope.projectId, live.scope.spaceId, live.document.document_id));}
      refresh().catch(report);
    } catch (e) {
      if (generation.current !== token) return;
      setStatus(e.status === 409 ? 'conflict' : 'error'); report(e);
    }
  }, [request, refresh, report]);
  useEffect(() => {
    if (status !== 'dirty' || !draft || !document || collaboration.current || pendingCommand) return;
    const timer = setTimeout(save, 900); return () => clearTimeout(timer);
  }, [draft, document, status, save, pendingCommand]);
  const sendCommand = async (payload, replay = false) => {
    if (commandBusy.current || (pendingCommand && !replay)) throw Error('Consulte a ação pendente antes de criar outra alteração.');
    commandBusy.current = true;
    const body = {...payload}; body.mutation_id ||= crypto.randomUUID(); body.request_key = body.mutation_id;
    const key = draftKey(scope.projectId, scope.spaceId, '__commands__');
    try {
      await draftStore('put', key, {command: body}); setPendingCommand(body);
      const result = await request(body);
      if (!result.receipt_id) throw Error('Ação ainda não confirmada por recibo.');
      await draftStore('delete', key); setPendingCommand(null); return result;
    } catch (e) {
      if (e.status >= 400 && e.status < 500) {await draftStore('delete', key); setPendingCommand(null);}
      throw e;
    } finally {commandBusy.current = false;}
  };
  const retryCommand = async () => {
    if (!pendingCommand) return;
    try {
      const result = await sendCommand(pendingCommand, true); await refresh();
      if (result.deleted) {generation.current++; stopCollaboration(); setDocument(null); setDraft(null); setStatus('saved');}
      else if (result.document_id) await open(result.document_id);
    } catch(e){report(e);}
  };
  const create = async () => {
    if (!guard()) return;
    const title = window.prompt('Nome do documento', 'Sem título'); if (!title?.trim()) return;
    try {
      const created = await sendCommand({action: 'document_create', title, content: '', format: 'markdown',
        parent_id: document?.document_id ?? null, expected_revision: 0, mutation_id: crypto.randomUUID()});
      await refresh(); await open(created.document_id);
    } catch (e) {report(e);}
  };
  const loadHistory = async (beforeRevision = null) => {
    try {const result = await request({action: 'document_history', document_id: document.document_id,
      ...(typeof beforeRevision === 'number' ? {before_revision: beforeRevision} : {})});
      setHistory(old => typeof beforeRevision === 'number' ? [...old, ...result.items] : result.items); setHistoryCursor(result.next_revision);
    } catch (e) {report(e);}
  };
  const restore = async revision => {
    if (!guard() || !window.confirm('Restaurar esta versão como uma nova revisão?')) return;
    try {
      const restored = await sendCommand({action: 'document_restore', document_id: document.document_id,
        revision, expected_revision: document.revision, mutation_id: crypto.randomUUID()});
      stopCollaboration(); setDocument(restored); setDraft(restored); setStatus('saved'); attempt.current = null;
      await draftStore('delete', draftKey(scope.projectId, scope.spaceId, restored.document_id)); await refresh(); await loadHistory();
    } catch (e) {report(e);}
  };
  const remove = async () => {
    if (!guard() || !window.confirm(`Excluir “${document.title}”? O histórico será preservado.`)) return;
    try {
      await sendCommand({action: 'document_delete', document_id: document.document_id, expected_revision: document.revision, mutation_id: crypto.randomUUID()});
      generation.current++; stopCollaboration(); setDocument(null); setDraft(null); setStatus('saved'); await refresh();
    } catch (e) {report(e);}
  };
  const exportDocument = async () => {
    try {
      const exported = await request({action: 'document_export', document_id: document.document_id});
      const url = URL.createObjectURL(new Blob([exported.content], {type: exported.media_type}));
      const anchor = window.document.createElement('a'); anchor.href = url; anchor.download = exported.filename; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {report(e);}
  };
  const collaborate = async () => {
    if (dirty) {report(Error('Confirme o salvamento antes de iniciar a colaboração.')); return;}
    const token = generation.current;
    try {
      const connection = await connectDocument({bridge, projectId: scope.projectId, spaceId: scope.spaceId, documentId: document.document_id,
        onChange: (content, local) => {if (generation.current === token) {setDraft(old => ({...old, content})); if (local) setStatus('dirty');}},
        onConfirmed: confirmed => {if (generation.current === token) {
          setDocument(confirmed); setDraft(old => ({...old, revision: confirmed.revision})); setStatus('collaborative');
          draftStore('delete', draftKey(scope.projectId, scope.spaceId, confirmed.document_id)).catch(report);
        }},
        onPresence: setPresence, onStatus: setCollabStatus, onError: report});
      if (generation.current !== token) {connection.close(); return;}
      collaboration.current = connection; setMode('source'); setStatus('collaborative');
    } catch (e) {report(e);}
  };
  const recover = () => {
    if (!recovery) return;
    setDraft({...document, ...recovery.draft}); attempt.current = recovery.attempt ?? null;
    setStatus(recovery.expectedRevision !== document.revision ? 'conflict' : recovery.attempt ? 'error' : 'dirty'); setRecovery(null);
  };
  const depth = item => {let level = 0, parent = item.parent_id; const seen = new Set([item.document_id]);
    while (parent && !seen.has(parent) && level < 8) {seen.add(parent); level++; parent = items.find(i => i.document_id === parent)?.parent_id;} return level;};
  return <section className="document-panel" aria-label="Documentos do Space">
    <aside className="document-library">
      <div className="document-library-heading"><h3>Documentos</h3><button onClick={create}>Novo</button></div>
      {items.map(item => <button key={item.document_id} className={item.document_id === document?.document_id ? 'selected' : ''}
        style={{paddingLeft: 12 + depth(item) * 12}} onClick={() => open(item.document_id)}>{item.title}<small>r{item.revision}</small></button>)}
      {!items.length && <p>Nenhum documento neste Space.</p>}
      {nextCursor && <button onClick={() => refresh(nextCursor).catch(report)}>Mais documentos</button>}
    </aside>
    <main className="document-workarea">
      <button onClick={() => setShowFiles(old => !old)}>{showFiles ? 'Ocultar arquivos' : 'Arquivos, código e PDF'}</button>
      {showFiles && <DocumentProjectFiles bridge={bridge} projectId={scope.projectId} onError={report}/>}
      <p className="document-status" role="status" aria-live="polite">{labels[status] ?? status}</p>
      {pendingCommand && <div className="document-recovery" role="status">Uma alteração aguarda confirmação. <button onClick={retryCommand}>Consultar ação pendente</button></div>}
      {error && <p role="alert" className="document-error">{error}</p>}
      {recovery && <div className="document-recovery">Há um rascunho neste computador. <button onClick={recover}>Recuperar</button><button onClick={async () => {await draftStore('delete', draftKey(scope.projectId, scope.spaceId, document.document_id)); setRecovery(null);}}>Descartar rascunho</button></div>}
      {document && draft ? <>
        <input className="document-title" aria-label="Título do documento" maxLength={240} value={draft.title} disabled={Boolean(collaboration.current)} onChange={e => edit({title: e.target.value})}/>
        <div className="document-actions">
          <button onClick={save} disabled={!dirty || status === 'saving' || status === 'conflict'}>{status === 'error' ? 'Consultar/repetir salvamento' : 'Salvar'}</button>
          <button onClick={() => setMode(mode === 'rich' ? 'source' : 'rich')} disabled={draft.format !== 'markdown' || Boolean(collaboration.current)}>{mode === 'rich' ? 'Fonte Markdown' : 'Editor rico'}</button>
          <button onClick={loadHistory}>Histórico</button><button onClick={exportDocument}>Exportar</button>
          <button onClick={remove}>Excluir</button>
          {collaboration.current ? <button onClick={async () => {stopCollaboration(); await open(document.document_id);}}>Encerrar colaboração</button> : <button onClick={collaborate} disabled={dirty}>Colaborar</button>}
        </div>
        <div className="document-options">
          <label>Formato <select value={draft.format} disabled={Boolean(collaboration.current)} onChange={e => {edit({format: e.target.value}); setMode(e.target.value === 'markdown' ? 'rich' : 'source');}}><option value="markdown">Markdown</option><option value="text">Texto</option><option value="code">Código</option></select></label>
          {draft.format === 'code' && <label>Linguagem <input value={draft.language || ''} maxLength={40} onChange={e => edit({language: e.target.value})}/></label>}
          <label>Página superior <select value={draft.parent_id || ''} disabled={Boolean(collaboration.current)} onChange={e => edit({parent_id: e.target.value || null})}><option value="">Raiz</option>{items.filter(i => i.document_id !== document.document_id).map(i => <option key={i.document_id} value={i.document_id}>{i.title}</option>)}</select></label>
        </div>
        {status === 'conflict' && <div className="document-recovery">O servidor mudou. Seu rascunho permanece aqui.
          <button onClick={async () => {try {const latest = await request({action: 'document_get', document_id: document.document_id}); setDocument(latest); setStatus('dirty'); attempt.current = null;} catch(e){report(e);}}}>Usar revisão atual e revisar meu rascunho</button>
          <button onClick={() => open(document.document_id)}>Abrir versão do servidor</button>
        </div>}
        {mode === 'rich' && draft.format === 'markdown' ? <DocumentRichEditor content={draft.content} onChange={content => edit({content})}/> : draft.format === 'code' ?
          <DocumentCodeEditor content={draft.content} language={draft.language} onChange={content => edit({content})}
            readOnly={Boolean(collaboration.current) && !collabStatus?.writable} collaborative={Boolean(collaboration.current)}
            onCursor={(anchor, head) => collaboration.current?.cursor(anchor, head)} onUndo={() => collaboration.current?.undo()} onRedo={() => collaboration.current?.redo()}/> :
          <textarea className="document-source" aria-label={draft.format === 'code' ? 'Código fonte' : 'Fonte do documento'} spellCheck={draft.format !== 'code'}
            value={draft.content} readOnly={Boolean(collaboration.current) && !collabStatus?.writable}
            onChange={e => edit({content: e.target.value})} onSelect={e => collaboration.current?.cursor(e.target.selectionStart, e.target.selectionEnd)}/>
        }
        {collabStatus && <p role="status">{collabStatus.synced ? 'Sincronizado' : 'Conectando ou reconectando…'} · {presence.length} presença(s)
          <button disabled={!collabStatus.writable} onClick={() => collaboration.current?.undo()}>Desfazer minha edição</button>
          <button disabled={!collabStatus.writable} onClick={() => collaboration.current?.redo()}>Refazer</button>
          {presence.map(p => <small key={p.clientId}>{p.user?.id ?? 'Colaborador'}{Number.isInteger(p.cursor.anchor) ? ` · cursor ${p.cursor.anchor}` : ''}</small>)}
        </p>}
        {history.length > 0 && <ol className="document-history">{history.map(version => <li key={version.revision}>Revisão {version.revision} · {version.document.title}
          <button onClick={() => request({action: 'document_diff', document_id: document.document_id, revision: version.revision}).then(r => setDiff(r.diff)).catch(report)}>Comparar</button>
          <button onClick={() => restore(version.revision)} disabled={dirty}>Restaurar</button></li>)}</ol>}
        {historyCursor && <button onClick={() => loadHistory(historyCursor)}>Versões anteriores</button>}
        {diff && <pre className="document-diff" aria-label="Diferenças entre revisões">{diff}</pre>}
      </> : <p>Selecione ou crie um documento.</p>}
    </main>
  </section>;
}
