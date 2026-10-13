import React, { useEffect, useRef, useState } from 'react';
import { Paperclip } from 'lucide-react';

const CHUNK_BYTES = 524288;
const digest = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(byte => byte.toString(16).padStart(2, '0')).join('');
function dataURL(bytes) {
  const values = new Uint8Array(bytes); let binary = '';
  for (let index = 0; index < values.length; index += 8192) binary += String.fromCharCode(...values.subarray(index, index + 8192));
  return 'data:application/octet-stream;base64,' + btoa(binary);
}
function restore(key) { try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; } }
function detectKind(file) {
  return file.type.startsWith('image/') || /\.(png|jpe?g)$/i.test(file.name) ? 'image' : file.type === 'application/pdf' || /\.pdf$/i.test(file.name) ? 'pdf'
    : /\.(py|js|jsx|ts|tsx|json|css|html|sql|go|rs|c|cpp|ps1|sh|yaml|yml)$/i.test(file.name) ? 'code' : 'text';
}
export function ShellAttachments({ bridge, scope, availability, attachments, onAttachments, onBusy, disabled }) {
  const storageKey = 'sentra_shell_upload:' + scope.project_id + ':' + scope.conversation_id;
  const [upload, setUpload] = useState(() => restore(storageKey)), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [kind, setKind] = useState('auto'), [fileReady, setFileReady] = useState(false);
  const file = useRef(null), current = useRef(upload), locked = useRef(false), cancelled = useRef(false), alive = useRef(true);
  const attachmentsRef = useRef(attachments); attachmentsRef.current = attachments;
  const bridgeRef = useRef(bridge); bridgeRef.current = bridge;
  const available = availability?.available === true;
  function remember(value) {
    current.current = value;
    if (alive.current) setUpload(value);
    try { if (value) sessionStorage.setItem(storageKey, JSON.stringify(value)); else sessionStorage.removeItem(storageKey); } catch { /* The current attempt remains in memory. */ }
  }
  function applyReceipt(value) {
    if (!Array.isArray(value.attachments) || !value.attachments.length || value.attachments.some(item => !item.attachment_id || !item.sha256 || item.stored === false)) {
      throw Error('O servidor não confirmou o armazenamento completo do arquivo.');
    }
    if (!alive.current) { remember({ ...current.current, phase: 'complete', receipts: value.attachments }); return; }
    const merged = new Map(attachmentsRef.current.map(item => [item.attachment_id, item]));
    for (const item of value.attachments) merged.set(item.attachment_id, item);
    onAttachments([...merged.values()]); remember(null); file.current = null; setFileReady(false);
  }
  useEffect(() => {
    alive.current = true;
    if (current.current?.receipts) applyReceipt({ attachments: current.current.receipts });
    return () => { alive.current = false; cancelled.current = true; };
  }, []);
  useEffect(() => { onBusy(busy || Boolean(upload)); }, [busy, Boolean(upload), onBusy]);
  async function exclusive(work) {
    if (locked.current) return; locked.current = true; cancelled.current = false; setBusy(true); setError('');
    try { await work(); } catch (e) {
      if (alive.current) setError(e.message);
      if (current.current) remember({ ...current.current, phase: e.uncertain || current.current.pending ? 'uncertain' : 'paused', reason: e.message });
    } finally { locked.current = false; if (alive.current) setBusy(false); }
  }
  async function choose(selected) {
    if (!selected || disabled || locked.current) return;
    await exclusive(async () => {
      const chosenKind = current.current?.kind || (kind === 'auto' ? detectKind(selected) : kind);
      const budget = chosenKind === 'image' ? 8 * 1024 * 1024 : 20 * 1024 * 1024;
      if (!selected.size || selected.size > budget) throw Error(chosenKind === 'image' ? 'A imagem deve ter até 8 MiB.' : 'O documento deve ter até 20 MiB.');
      const hash = await digest(await selected.arrayBuffer());
      if (current.current) {
        if (selected.size !== current.current.total_bytes || hash !== current.current.total_sha256) throw Error('Selecione o mesmo arquivo; tamanho e SHA-256 precisam coincidir com o upload pendente.');
        file.current = selected; setFileReady(true); return;
      }
      if (attachmentsRef.current.length >= Math.min(4, availability?.max_attachments || 4)) throw Error('A mensagem já tem o máximo de quatro anexos.');
      file.current = selected; setFileReady(true);
      const request = { action: 'attachment_upload_begin', ...scope, request_key: crypto.randomUUID(), kind: chosenKind,
        name: selected.name.slice(0, 256), total_bytes: selected.size, total_sha256: hash };
      remember({ kind: chosenKind, name: request.name, total_bytes: request.total_bytes, total_sha256: hash,
        received_bytes: 0, received_chunks: 0, chunk_bytes: CHUNK_BYTES, begin_key: request.request_key, pending: request, phase: 'starting' });
      const result = await bridgeRef.current(request);
      if (!result.upload_id || result.chunk_bytes > CHUNK_BYTES || !result.chunk_bytes) throw Error('O servidor não retornou um upload bounded.');
      remember({ ...current.current, upload_id: result.upload_id, chunk_bytes: result.chunk_bytes, phase: 'paused', pending: null });
    });
    // The user explicitly resumes a staged upload. No implicit restart after an ambiguous response.
  }
  async function consult() {
    await exclusive(async () => {
      const value = current.current;
      const requestKey = value.pending?.request_key || value.complete_key || value.begin_key;
      const result = await bridgeRef.current({ action: 'attachment_upload_status', ...scope, request_key: requestKey,
        ...(!value.pending && value.upload_id ? { upload_id: value.upload_id } : {}) });
      if (result.attachments?.length) { applyReceipt(result); return; }
      if (result.state === 'aborted') { remember(null); file.current = null; setFileReady(false); return; }
      if (result.expired) { remember({ ...value, phase: 'expired' }); return; }
      if (result.state === 'uncertain') { remember({ ...value, phase: 'uncertain' }); return; }
      const received = Number.isInteger(result.received_chunks) ? result.received_chunks : value.received_chunks;
      const acknowledged = value.pending?.action === 'attachment_upload_chunk' ? received > value.pending.index
        : value.pending?.action === 'attachment_upload_begin' ? Boolean(result.upload_id) : false;
      remember({ ...value, upload_id: result.upload_id || value.upload_id, received_chunks: received,
        received_bytes: result.received_bytes ?? value.received_bytes, phase: 'paused',
        pending: acknowledged ? null : value.pending });
    });
  }
  async function resume() {
    if (!file.current || current.current?.phase === 'uncertain') return;
    await exclusive(async () => {
      let value = current.current;
      if (!value.upload_id) throw Error('Consulte a abertura do upload antes de continuar.');
      while (value.received_bytes < value.total_bytes && alive.current && !cancelled.current) {
        const bytes = await file.current.slice(value.received_bytes, Math.min(value.total_bytes, value.received_bytes + value.chunk_bytes)).arrayBuffer();
        const request = value.pending || { action: 'attachment_upload_chunk', ...scope, upload_id: value.upload_id,
          index: value.received_chunks, data_url: dataURL(bytes), chunk_sha256: await digest(bytes), request_key: crypto.randomUUID() };
        remember({ ...value, pending: request, phase: 'uploading' });
        const result = await bridgeRef.current(request);
        if (result.received_chunks !== request.index + 1 || !Number.isInteger(result.received_bytes)) throw Error('O índice do chunk não foi confirmado. Consulte o upload antes de continuar.');
        value = { ...current.current, received_chunks: result.received_chunks, received_bytes: result.received_bytes, pending: null, phase: 'paused' };
        remember(value);
      }
      if (cancelled.current || !alive.current) return;
      const completeKey = value.complete_key || crypto.randomUUID();
      const request = value.pending || { action: 'attachment_upload_complete', ...scope, upload_id: value.upload_id, request_key: completeKey };
      remember({ ...value, complete_key: completeKey, pending: request, phase: 'finishing' });
      applyReceipt(await bridgeRef.current(request));
    });
  }
  async function abort() {
    if (!current.current?.upload_id) { await consult(); return; }
    await exclusive(async () => {
      const value = current.current, key = value.abort_key || crypto.randomUUID();
      const request = { action: 'attachment_upload_abort', ...scope, upload_id: value.upload_id, request_key: key };
      remember({ ...value, abort_key: key, pending: request, phase: 'aborting' });
      const result = await bridgeRef.current(request);
      if (result.state !== 'aborted') throw Error('O cancelamento do upload ainda não foi confirmado.');
      remember(null); file.current = null; setFileReady(false);
    });
  }
  return <details className="shell-attachments"><summary><Paperclip size={14} /> Anexos</summary>
    {!available && <p>{availability?.reason || 'O adaptador de anexos desta conversa não está configurado.'}</p>}
    {available && <div><label>Tipo<select value={kind} disabled={busy || Boolean(upload)} onChange={e => setKind(e.target.value)}><option value="auto">Detectar pelo arquivo</option><option value="image">Imagem PNG/JPEG</option><option value="pdf">PDF</option><option value="text">Texto</option><option value="code">Código</option></select></label>
      <label>{upload ? 'Escolher o mesmo arquivo para retomar' : 'Escolher arquivo'}<input type="file" disabled={busy || disabled} accept="image/png,image/jpeg,application/pdf,text/plain,.md,.py,.js,.jsx,.ts,.tsx,.json,.css,.html,.sql,.go,.rs,.ps1,.yaml,.yml" onChange={e => { const selected = e.target.files[0]; e.target.value = ''; void choose(selected); }} /></label>
      <small>Até quatro anexos · imagens 8 MiB · documentos 20 MiB · chunks de 512 KiB.</small></div>}
    {upload && <div className="shell-upload-progress" role="status"><strong>{upload.name}</strong><progress max={upload.total_bytes} value={upload.received_bytes || 0} />
      <span>{upload.received_bytes || 0} / {upload.total_bytes} bytes · {upload.phase === 'uncertain' ? 'Resposta não confirmada' : upload.phase === 'expired' ? 'Upload expirado' : busy ? 'Transferindo…' : 'Upload pausado'}</span>
      <div><button disabled={busy} onClick={consult}>Consultar progresso</button><button disabled={!available || busy || !fileReady || upload.phase === 'uncertain' || upload.phase === 'expired' || disabled} onClick={resume}>Continuar upload</button>
        {busy && <button onClick={() => { cancelled.current = true; }}>Pausar após este chunk</button>}<button disabled={busy} onClick={abort}>Cancelar upload</button></div></div>}
    {error && <p role="alert" className="shell-error">{error}</p>}
    {attachments.map(item => <div key={item.attachment_id}><span>{item.name} · {item.bytes} bytes · armazenado</span><details><summary>Referência e integridade</summary>{item.attachment_id}<br />SHA-256: {item.sha256}</details><button disabled={busy || disabled} onClick={() => onAttachments(attachments.filter(row => row.attachment_id !== item.attachment_id))}>Remover da mensagem</button></div>)}
  </details>;
}
