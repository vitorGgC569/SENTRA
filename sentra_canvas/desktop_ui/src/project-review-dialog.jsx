import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FileText, Folder, ArrowUp, GitCompare, RefreshCw, PanelLeft, PanelRight, Search } from 'lucide-react';
import { Modal } from './primitives';
import { api, route } from './api';
import {
  loadProjectDocks, saveProjectDocks, filterProjectEntries,
  dpiForScale, nextRevision, pngDataUrl, projectShortcut,
  isPdfTextFallbackAllowed, validatedPdfVisualResponse,
} from './project-ux-state';

function browserStorage() {
  try { return window.localStorage; } catch { return null; }
}

// Passive workspace browser. The authoritative owner still approves every edit
// using Canvas' existing one-use review token; these UI controls create no grants.
export function ProjectReviewDialog({ ws, close }) {
  const [directory, setDirectory] = useState(''), [entries, setEntries] = useState([]);
  const [selected, setSelected] = useState(''), [content, setContent] = useState(null);
  const [fileInfo, setFileInfo] = useState(null), [tab, setTab] = useState('preview');
  const [pdfInfo, setPdfInfo] = useState(null), [visualUnavailable, setVisualUnavailable] = useState(false);
  const [draft, setDraft] = useState(''), [review, setReview] = useState(null);
  const [reviewedDraft, setReviewedDraft] = useState(null), [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [notice, setNotice] = useState(''), [stale, setStale] = useState(false);
  const [filter, setFilter] = useState(''), [scale, setScale] = useState(100);
  const [docks, setDocks] = useState(() => loadProjectDocks(browserStorage(), ws));
  const searchRef = useRef(null);
  const pendingSearch = useRef(false);
  const sequence = useRef(0);
  const isPdf = selected.toLowerCase().endsWith('.pdf');
  const sourceSha = isPdf ? pdfInfo?.source_sha256 : fileInfo?.sha256;

  useEffect(() => {
    setDocks(loadProjectDocks(browserStorage(), ws));
  }, [ws]);
  const toggleDock = name => setDocks(old => {
    const next = { ...old, [name]: !old[name] };
    saveProjectDocks(browserStorage(), ws, next);
    return next;
  });

  const browse = useCallback(async path => {
    const id = ++sequence.current;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await api(route('/api/center/project-review', { ws, path, action: 'list' }));
      if (id !== sequence.current) return;
      setDirectory(path); setEntries(result.items); setSelected(''); setContent(null);
      setFileInfo(null); setPdfInfo(null); setReview(null); setConsent(false);
      setStale(false); setFilter('');
    } catch (e) { if (id === sequence.current) setError(e.message); }
    finally { if (id === sequence.current) setBusy(false); }
  }, [ws]);

  const inspect = useCallback(async (path, action = 'preview', page = 1, dpi = 72) => {
    const id = ++sequence.current;
    setBusy(true); setError(''); setNotice('');
    try {
      let result, mode = action;
      try {
        result = await api(route('/api/center/project-review', { ws, path, action, page, dpi }));
        if (action === 'pdf_visual' && !validatedPdfVisualResponse(result, { path, page, dpi })) {
          throw new Error('Resposta PDF visual inv?lida: revis?o ou PNG n?o verific?vel.');
        }
      } catch (err) {
        if (action !== 'pdf_visual' || !isPdfTextFallbackAllowed(err)) throw err;
        // Coordinator-owned route may not yet be integrated. Fail closed to
        // already authorized text-only preview, never browser-embed raw PDF.
        result = await api(route('/api/center/project-review', { ws, path, action: 'pdf_text', page }));
        mode = 'pdf_text';
        if (result?.read_only !== true || result?.ocr_used !== false ||
            result?.path !== path || result?.page !== page ||
            !Number.isInteger(result?.pages) || typeof result?.text !== 'string' ||
            !/^[a-f0-9]{64}$/.test(result?.source_sha256 || '')) {
          throw new Error('Pr?via textual PDF inv?lida.');
        }
      }
      if (id !== sequence.current) return;
      setSelected(path); setTab(mode);
      if (mode === 'pdf_text' || mode === 'pdf_visual') {
        setPdfInfo(result); setFileInfo(null); setContent(mode === 'pdf_text' ? result.text : null);
        setVisualUnavailable(action === 'pdf_visual' && mode === 'pdf_text');
      } else if (mode === 'preview') {
        setPdfInfo(null); setFileInfo(result); setContent(result.content); setDraft(result.content);
      } else { setPdfInfo(null); setContent(result.diff); }
      setReview(null); setReviewedDraft(null); setConsent(false); setStale(false);
    } catch (e) { if (id === sequence.current) setError(e.message); }
    finally { if (id === sequence.current) setBusy(false); }
  }, [ws]);

  useEffect(() => { browse(''); return () => { ++sequence.current; }; }, [browse]);

  // Existing read-only owner route is a safe polling fallback while the
  // coordinator integrates action=revision. Probe SHA, debounce and reconfirm;
  // never silently overwrite draft content when another process changes it.
  useEffect(() => {
    if (!selected || !sourceSha || stale) return;
    let disposed = false, pending = null, running = false, lastChanged = '';
    const action = isPdf ? 'pdf_text' : 'preview';
    async function verify() {
      if (disposed || running) return;
      running = true;
      try {
        const result = await api(route('/api/center/project-review', {
          ws, path: selected, action, ...(isPdf ? { page: 1 } : {}),
        }));
        if (disposed) return;
        const rev = isPdf ? result.source_sha256 : result.sha256;
        if (nextRevision(sourceSha, { sha256: rev }) !== 'same') {
          if (lastChanged !== rev) {
            lastChanged = rev;
            clearTimeout(pending);
            pending = setTimeout(() => { if (!disposed) void verify(); }, 400);
          } else {
            setStale(true); setReview(null); setConsent(false);
            setNotice('O arquivo mudou no disco. Reabra para comparar a nova revisão; seu rascunho foi preservado.');
          }
        } else { lastChanged = ''; clearTimeout(pending); pending = null; }
      } catch {
        if (!disposed) {
          setStale(true); setReview(null); setConsent(false);
          setNotice('Não foi possível confirmar a revisão no disco. Reabra o arquivo antes de salvar.');
        }
      } finally { running = false; }
    }
    const interval = setInterval(() => { void verify(); }, 2500);
    return () => { disposed = true; clearInterval(interval); clearTimeout(pending); };
  }, [ws, selected, sourceSha, stale, isPdf]);

  const parent = directory.split('/').slice(0, -1).join('/');
  async function reviewEdit() {
    if (stale || !fileInfo?.editable) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await api('/api/center/project-review', {
        ws, action: 'preview_edit', path: selected, content: draft, expected_sha256: fileInfo.sha256,
      });
      setReview(result); setReviewedDraft(draft); setConsent(false);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function saveEdit() {
    if (!consent || stale || !review?.review_token || reviewedDraft !== draft) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await api('/api/center/project-review', {
        ws, action: 'save', path: selected, content: draft,
        expected_sha256: fileInfo.sha256, approve: true,
        review_token: review.review_token,
      });
      await inspect(selected, 'preview');
      setNotice('Arquivo salvo com revisão SHA-256 confirmada.');
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  useEffect(() => {
    const handle = event => {
      const action = projectShortcut(event, { editing: tab === 'edit' });
      if (!action) return;
      event.preventDefault();
      if (action === 'search') {
        pendingSearch.current = true;
        if (!docks.files) toggleDock('files');
        else { searchRef.current?.focus(); pendingSearch.current = false; }
      }
      else if (action === 'review' && !busy && !stale && draft !== fileInfo?.content) void reviewEdit();
      else if (action === 'files' || action === 'details') toggleDock(action);
    };
    document.addEventListener('keydown', handle);
    return () => document.removeEventListener('keydown', handle);
  });
  useEffect(() => {
    if (docks.files && pendingSearch.current) {
      searchRef.current?.focus(); pendingSearch.current = false;
    }
  }, [docks.files]);
  const visibleEntries = filterProjectEntries(entries, filter);
  const goToFile = item => item.directory ? browse(item.path) :
    inspect(item.path, item.path.toLowerCase().endsWith('.pdf') ? 'pdf_visual' : 'preview', 1, dpiForScale(scale));
  const arrowNavigation = event => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const buttons = [...event.currentTarget.querySelectorAll('button:not(:disabled)')];
    const index = buttons.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    buttons[(index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus();
  };
  const png = tab === 'pdf_visual' ? pngDataUrl(pdfInfo) : null;
  return <Modal open onOpenChange={value => { if (!value) close(); }}
    title="Arquivos do projeto" description="Leitura confinada, revisão SHA-256 e consentimento explícito."
    className="project-review-dialog" aria-modal="true">
    <div className="project-review">
      <div className="project-review-toolbar" role="toolbar" aria-label="Ferramentas do projeto">
        <button type="button" aria-label="Exibir arquivos (Ctrl+B)" aria-pressed={docks.files}
          onClick={() => toggleDock('files')}><PanelLeft size={15}/></button>
        <code title={directory || 'Workspace'}>{directory || 'Workspace'}</code>
        <button type="button" disabled={busy || !directory} aria-label="Pasta anterior"
          onClick={() => browse(parent)}><ArrowUp size={14}/> Voltar</button>
        <button type="button" disabled={busy} aria-label="Atualizar arquivos"
          onClick={() => browse(directory)}><RefreshCw size={14}/></button>
        <button type="button" aria-label="Detalhes do arquivo (Ctrl+I)" aria-pressed={docks.details}
          onClick={() => toggleDock('details')}><PanelRight size={15}/></button>
      </div>
      <div className="project-review-layout" data-files={docks.files} data-details={docks.details}>
        {docks.files && <nav className="project-review-tree" id="project-file-dock" aria-label="Arquivos do workspace">
          <label className="project-review-search"><Search size={14}/>
            <span className="sr-only">Buscar arquivos</span>
            <input ref={searchRef} value={filter} onChange={e => setFilter(e.target.value)}
              type="search" aria-label="Buscar nesta pasta (Ctrl+K)" placeholder="Buscar nesta pasta"/>
          </label>
          <div role="group" aria-label="Conteúdo da pasta" onKeyDown={arrowNavigation}>
            {visibleEntries.map(item => <button key={item.path} type="button"
              aria-current={selected === item.path ? 'true' : undefined}
              disabled={busy} onClick={() => goToFile(item)}>
              {item.directory ? <Folder size={14}/> : <FileText size={14}/>}<span>{item.name}</span>
            </button>)}
            {!visibleEntries.length && !busy && <p>{filter ? 'Nenhum arquivo encontrado.' : 'Pasta vazia.'}</p>}
          </div>
        </nav>}
        <section className="project-review-content" aria-label="Conteúdo do arquivo">
          {selected && <div className="project-review-file" role="toolbar" aria-label="Modos de visualização">
            <span title={selected}>{selected}</span>
            {!isPdf && <>
              <button type="button" disabled={busy || tab === 'preview'}
                onClick={() => inspect(selected, 'preview')}>Código</button>
              <button type="button" disabled={busy || tab === 'diff'}
                onClick={() => inspect(selected, 'diff')}><GitCompare size={13}/> Git diff</button>
            </>}
            {fileInfo?.editable && <button type="button" disabled={busy || tab === 'edit' || stale}
              onClick={() => { setTab('edit'); setReview(null); setConsent(false); }}>Editar</button>}
          </div>}
          {isPdf && pdfInfo && <div className="project-review-pdf-nav" aria-label="Navegação do PDF">
            <span>PDF · página {pdfInfo.page} de {pdfInfo.pages}</span>
            <button type="button" disabled={busy || tab === 'pdf_visual'}
              onClick={() => inspect(selected, 'pdf_visual', pdfInfo.page, dpiForScale(scale))}>Visual</button>
            <button type="button" disabled={busy || tab === 'pdf_text'}
              onClick={() => inspect(selected, 'pdf_text', pdfInfo.page)}>Texto</button>
            <label>Escala <select aria-label="Escala de visualização de PDF" value={scale}
              onChange={event => {
                const value = Number(event.target.value);
                setScale(value);
                if (tab === 'pdf_visual') void inspect(selected, 'pdf_visual', pdfInfo.page, dpiForScale(value));
              }}>
              <option value={100}>100%</option><option value={125}>125%</option><option value={150}>150%</option>
            </select></label>
            <button type="button" disabled={busy || pdfInfo.page <= 1}
              onClick={() => inspect(selected, tab, pdfInfo.page - 1, dpiForScale(scale))}>Anterior</button>
            <button type="button" disabled={busy || pdfInfo.page >= pdfInfo.pages}
              onClick={() => inspect(selected, tab, pdfInfo.page + 1, dpiForScale(scale))}>Próxima</button>
          </div>}
          {png ? <div className="project-review-page" role="region" aria-label="Página PDF renderizada">
            <img src={png} width={pdfInfo.width} height={pdfInfo.height}
              alt={`Página ${pdfInfo.page} de ${pdfInfo.pages} do PDF`} decoding="async"/>
          </div> : content === null ?
            <p className="project-review-hint">Selecione um arquivo para consultar seu conteúdo.</p> :
            tab === 'edit' ? <textarea aria-label="Editor de código" value={draft}
              spellCheck={false} disabled={busy || stale}
              onChange={event => {
                setDraft(event.target.value); setReview(null); setReviewedDraft(null); setConsent(false);
              }} className="project-review-editor"/> :
            <pre tabIndex={0} aria-label={tab === 'diff' ? 'Diff Git' : isPdf ? 'Texto da página PDF' : 'Código do arquivo'}>
              {content || (isPdf ? 'Esta página não contém texto extraível. Nenhum OCR foi executado.' :
                'Nenhuma alteração neste arquivo.')}
            </pre>}
        </section>
        {docks.details && <aside className="project-review-details" aria-label="Detalhes da revisão">
          <h3>Revisão</h3>
          <dl>
            <dt>Arquivo</dt><dd>{selected || 'Nenhum'}</dd>
            <dt>SHA-256</dt><dd title={sourceSha || ''}>{sourceSha || '—'}</dd>
            <dt>Estado</dt><dd>{stale ? 'Mudança externa detectada' : 'Somente leitura'}</dd>
          </dl>
          <p>Este painel não concede permissões a agentes.</p>
        </aside>}
      </div>
      {visualUnavailable && isPdf && <p role="status" className="project-review-note">
        A renderização visual requer a rota local autenticada do Canvas. Prévia textual disponível, sem OCR.
      </p>}
      {tab === 'edit' && fileInfo?.editable && <div className="project-review-save">
        <button type="button" disabled={busy || stale || draft === fileInfo.content} onClick={reviewEdit}>
          Revisar mudanças (Ctrl+S)
        </button>
        {review && <div className="project-review-review">
          <strong>Comparação com a revisão atual</strong>
          <pre tabIndex={0} aria-label="Alterações propostas">{review.diff || 'Sem alterações.'}</pre>
          <label><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)}/>
            Confirmo a escrita deste arquivo no workspace.</label>
          <button type="button"
            disabled={busy || stale || !review.changed || !review.review_token || !consent || reviewedDraft !== draft}
            onClick={saveEdit}>Salvar revisão verificada</button>
        </div>}
      </div>}
      {notice && <p role="status" className="project-review-note">{notice}
        {stale && <button type="button" onClick={() => inspect(selected, isPdf ? 'pdf_visual' : 'preview', 1, dpiForScale(scale))}>Reabrir arquivo</button>}
      </p>}
      {error && <p role="alert" className="form-error">{error}</p>}
      <footer className="project-review-footer">
        Ctrl+K busca · Ctrl+B arquivos · Ctrl+I detalhes · PDF local sem OCR · edição apenas com revisão e consentimento do proprietário.
      </footer>
    </div>
  </Modal>;
}
