import React, {useEffect, useRef, useState} from 'react';
import {DocumentCodeEditor} from './document-code-editor.jsx';

// Workspace paths are resolved by Canvas; all previews are passive projections.
export function DocumentProjectFiles({bridge, projectId, onError}) {
  const [folder, setFolder] = useState(''), [entries, setEntries] = useState([]);
  const [selected, setSelected] = useState(null), [preview, setPreview] = useState(null);
  const [kind, setKind] = useState('preview'), [notice, setNotice] = useState('');
  const [dpi, setDpi] = useState(72), [busy, setBusy] = useState(false);
  const generation = useRef(0), watcher = useRef(null), callbacks = useRef({});
  callbacks.current = {bridge, onError};
  const request = async payload => {
    const result = await callbacks.current.bridge({project_id: projectId, request_key: crypto.randomUUID(), ...payload});
    return result?.value ?? result;
  };
  const report = error => {setNotice(error.message); callbacks.current.onError?.(error);};
  const closeWatch = () => {
    if (!watcher.current) return;
    const current = watcher.current; watcher.current = null;
    callbacks.current.bridge({action: 'project_watch_close', project_id: current.projectId,
      watch_id: current.watchId, request_key: crypto.randomUUID()}).catch(() => {});
  };
  const list = async path => {
    const token = generation.current;
    try {const result = await request({action: 'project_file_list', path}); if(generation.current===token){setFolder(result.path); setEntries(result.items);}} catch (e) {if(generation.current===token)report(e);}
  };
  useEffect(() => {
    let active = true; generation.current++; closeWatch(); setPreview(null); setSelected(null); setNotice('');
    request({action: 'project_file_list', path: ''}).then(result => {if (active) {setFolder(''); setEntries(result.items);}}).catch(e => {if (active) report(e);});
    return () => {active = false; generation.current++; closeWatch();};
  }, [projectId]);
  const inspect = async (path, mode = 'preview', page = 1, newDpi = dpi) => {
    const token = ++generation.current; closeWatch(); setBusy(true); setNotice('');
    try {
      let result;
      try {result = await request({action: 'project_file_' + mode, path, page, dpi: newDpi});}
      catch (e) {
        if (mode !== 'pdf_visual' || e.status !== 503) throw e;
        mode = 'pdf_text'; result = await request({action: 'project_file_pdf_text', path, page});
        setNotice('Visualizador PDF indisponível; mostrando texto extraído.');
      }
      if (generation.current !== token) return;
      if (mode === 'pdf_visual' && (result.mime !== 'image/png' || typeof result.image_base64 !== 'string' ||
          result.image_base64.length > 4200000 || !result.image_base64.startsWith('iVBORw0KGgo') ||
          result.width * result.height > 2500000 || result.path !== path)) throw Error('Projeção visual PDF recusada.');
      setSelected(path); setKind(mode); setPreview(result);
      const handle = await request({action: 'project_watch_start', path});
      if (generation.current !== token) {
        await request({action: 'project_watch_close', watch_id: handle.watch_id}); return;
      }
      watcher.current = {watchId: handle.watch_id, projectId};
    } catch (e) {if (generation.current === token) report(e);}
    finally {if (generation.current === token) setBusy(false);}
  };
  useEffect(() => {
    let polling = false;
    const timer = setInterval(async () => {
      if (!watcher.current || polling || window.document.hidden) return;
      const current = watcher.current; polling = true;
      try {
        const result = await request({action: 'project_watch_poll', watch_id: current.watchId});
        if (watcher.current !== current) return;
        if (result.state === 'renamed') {setSelected(result.path); setNotice(`Arquivo renomeado: ${result.previous_path} → ${result.path}. Reabra a revisão.`);}
        if (result.state === 'changed') setNotice('O arquivo mudou externamente. Reabra para revisar a versão atual.');
      } catch (e) {if (watcher.current === current) {closeWatch(); report(e);}}
      finally {polling = false;}
    }, 1000);
    return () => clearInterval(timer);
  }, [projectId]);
  const language = selected?.split('.').at(-1) || '';
  return <section className="document-project-files" aria-label="Arquivos do projeto">
    <div className="document-actions"><strong>Arquivos do projeto</strong><span>{folder || '/'}</span>
      {folder && <button onClick={() => list(folder.split('/').slice(0, -1).join('/'))}>Pasta superior</button>}
      <button onClick={() => list(folder)}>Atualizar pasta</button>
    </div>
    <div className="document-file-list">{entries.map(item => <button key={item.path} disabled={busy} onClick={() => item.directory ? list(item.path) : inspect(item.path, item.path.toLowerCase().endsWith('.pdf') ? 'pdf_visual' : 'preview')}>
      {item.directory ? 'Pasta · ' : ''}{item.name}</button>)}</div>
    {notice && <p role="status">{notice}</p>}
    {selected && <div className="document-actions"><span>{selected}</span>
      <button disabled={busy} onClick={() => inspect(selected, kind, preview?.page || 1)}>Reabrir revisão</button>
      {!selected.toLowerCase().endsWith('.pdf') && <button disabled={busy} onClick={() => inspect(selected, 'diff')}>Diff Git</button>}
      {selected.toLowerCase().endsWith('.pdf') && <>
        <button disabled={busy || preview?.page <= 1} onClick={() => inspect(selected, kind, preview.page - 1)}>Página anterior</button>
        <span>{preview?.page}/{preview?.pages}</span>
        <button disabled={busy || !preview || preview.page >= preview.pages} onClick={() => inspect(selected, kind, preview.page + 1)}>Próxima página</button>
        <select aria-label="Escala do PDF" value={dpi} onChange={e => {const next = Number(e.target.value); setDpi(next); inspect(selected, 'pdf_visual', preview?.page || 1, next);}}><option value={72}>100%</option><option value={90}>125%</option><option value={108}>150%</option></select>
      </>}
    </div>}
    {busy && <p role="status">Abrindo arquivo…</p>}
    {preview && kind === 'preview' && <DocumentCodeEditor content={preview.content} language={language} readOnly onChange={() => {}}/>}
    {preview && kind === 'diff' && <pre className="document-diff">{preview.diff || 'Sem diferenças de trabalho.'}</pre>}
    {preview && kind === 'pdf_text' && <pre className="document-diff">{preview.text || 'Esta página não contém texto extraível. OCR não foi aplicado.'}</pre>}
    {preview && kind === 'pdf_visual' && <img className="document-pdf-page" alt={`Página ${preview.page} de ${preview.pages}`} src={'data:image/png;base64,' + preview.image_base64}/>}
  </section>;
}
