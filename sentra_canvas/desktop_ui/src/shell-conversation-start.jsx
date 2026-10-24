import React, { useEffect, useRef, useState } from 'react';
import { ArrowUp, ChevronDown, LoaderCircle, Plus, Paperclip, X } from 'lucide-react';
import { DotMascot } from './shell-mascot';
import { conversationTitleFromMessage, homeAttachmentError } from './shell-conversation-start.js';

function readStart(key) {
  try { return JSON.parse(sessionStorage.getItem(key)) || {}; } catch { return {}; }
}

export function HomeConversationStart({ projectId, spaceId, dots, preferredDotId, busy, locked, blocked, onStart, onCreateDot, onCreateCanvas, onNetwork, initialAttachment, onAttachmentChange }) {
  const key = 'sentra_home_draft:' + projectId + ':' + spaceId;
  const initial = useRef(readStart(key));
  const [text, setText] = useState(initial.current.text || '');
  const [dotId, setDotId] = useState(initial.current.dotId || preferredDotId || '');
  const [submitting, setSubmitting] = useState(false);
  const [attachment, setAttachment] = useState(initialAttachment || null);
  const [needsAttachment, setNeedsAttachment] = useState(!initialAttachment ? initial.current.attachment || null : null);
  const [attachmentError, setAttachmentError] = useState('');
  const input = useRef(null);
  const filePicker = useRef(null);
  const selected = dots.find(dot => dot.dot_id === dotId) || dots.find(dot => dot.dot_id === preferredDotId) || dots[0];
  const waiting = busy || submitting;
  useEffect(() => {
    try { sessionStorage.setItem(key, JSON.stringify({ text, dotId: selected?.dot_id, attachment: attachment ? { name: attachment.name, size: attachment.size, type: attachment.type } : needsAttachment })); } catch { /* Keep the current text in memory. */ }
  }, [key, text, selected?.dot_id, attachment, needsAttachment]);
  useEffect(() => {
    if (input.current) { input.current.style.height = 'auto'; input.current.style.height = Math.min(220, Math.max(76, input.current.scrollHeight)) + 'px'; }
  }, [text]);
  async function submit(event) {
    event.preventDefault();
    if (waiting || locked || blocked || needsAttachment || !selected || (!text.trim() && !attachment)) return;
    setSubmitting(true);
    try {
      const draft = text.trim() || 'Analise o arquivo ' + attachment.name + '.';
      const started = await onStart(selected, { draft, title: conversationTitleFromMessage(text.trim() || attachment.name), send: true, files: attachment ? [attachment] : [] });
      if (started) { try { sessionStorage.removeItem(key); } catch { /* The conversation owns the transferred draft. */ } }
    } finally { setSubmitting(false); }
  }
  function chooseFile(file) {
    if (!file) return;
    const error = homeAttachmentError(file);
    setAttachmentError(error);
    if (!error) { setAttachment(file); setNeedsAttachment(null); onAttachmentChange?.(file); }
  }
  function analyzeDocuments() {
    if (!text.trim()) setText('Analise este documento e destaque os pontos principais.');
    filePicker.current?.click();
  }
  function generateCode() {
    if (!text.trim()) setText('Quero criar uma funcionalidade neste projeto: ');
    input.current?.focus();
  }
  return <section className="shell-start" aria-label="Nova conversa">
    <div className="shell-start-greeting"><DotMascot mascot={selected?.mascot} identity={selected?.agent_id || selected?.dot_id} name={selected?.name || 'Dot'} status={selected?.status} execution={selected?.execution} size="intro" /><h1>O que vamos criar?</h1></div>
    {dots.length ? <div className="shell-start-action-area"><form className="shell-start-compose" onSubmit={submit} aria-busy={waiting}>
      <input ref={filePicker} className="shell-start-file-input" type="file" tabIndex={-1} aria-label="Selecionar anexo" accept="image/png,image/jpeg,application/pdf,text/plain,.md,.py,.js,.jsx,.ts,.tsx,.json,.css,.html,.sql,.go,.rs,.ps1,.yaml,.yml" disabled={waiting || locked} onChange={event => { chooseFile(event.currentTarget.files?.[0]); event.currentTarget.value = ''; }} />
      {(attachment || needsAttachment) && <div className="shell-start-attachment"><Paperclip size={14} aria-hidden="true" /><span title={(attachment || needsAttachment).name}>{(attachment || needsAttachment).name}</span><button type="button" aria-label="Remover anexo" disabled={waiting || locked} onClick={() => { setAttachment(null); setNeedsAttachment(null); onAttachmentChange?.(null); }}><X size={14} aria-hidden="true" /></button></div>}
      <div className="shell-start-writing"><button className="shell-start-add" type="button" aria-label="Anexar arquivo" title="Anexar arquivo" disabled={waiting || locked} onClick={() => filePicker.current?.click()}><Plus size={19} aria-hidden="true" /></button>
      <label className="shell-sr-only" htmlFor="shell-start-message">Mensagem para o Dot</label>
      <textarea id="shell-start-message" ref={input} value={text} maxLength={100000} disabled={waiting || locked} placeholder="Peça qualquer coisa…" onChange={event => setText(event.target.value)}
        onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} /></div>
      <div className="shell-start-controls"><label className="shell-start-dot"><DotMascot mascot={selected?.mascot} identity={selected?.agent_id || selected?.dot_id} size="nav" decorative /><span className="shell-sr-only">Conversar com</span><select value={selected?.dot_id || ''} onChange={event => setDotId(event.target.value)} disabled={waiting || locked} aria-label="Conversar com">{dots.map(dot => <option key={dot.dot_id} value={dot.dot_id}>{dot.name}</option>)}</select><ChevronDown size={13} aria-hidden="true" /></label>
        <span className="shell-start-model" title={selected?.model}>{selected?.model}</span>
        <button className="shell-start-send" type="submit" disabled={waiting || locked || blocked || Boolean(needsAttachment) || (!text.trim() && !attachment)} aria-label={waiting ? 'Abrindo conversa' : attachment || needsAttachment ? 'Continuar com anexo' : 'Enviar mensagem'}>{waiting ? <LoaderCircle size={18} className="shell-start-spinner" aria-hidden="true" /> : <ArrowUp size={19} aria-hidden="true" />}</button>
      </div>
      {blocked && <p className="shell-start-note" role="status">{blocked}</p>}
      {attachment && <p className="shell-start-note">Você revisa o anexo na conversa antes de enviar.</p>}
      {needsAttachment && <p className="shell-start-note" role="status">Selecione novamente o arquivo pelo botão + para continuar.</p>}
      {attachmentError && <p className="shell-start-note shell-start-file-error" role="alert">{attachmentError}</p>}
    </form><nav className="shell-start-shortcuts" aria-label="Ações rápidas"><button type="button" disabled={waiting || locked || Boolean(blocked)} onClick={analyzeDocuments}>Analisar documentos</button><button type="button" disabled={waiting || locked || Boolean(blocked)} onClick={onCreateCanvas}>Criar novo canvas</button><button type="button" disabled={waiting || locked || Boolean(blocked)} onClick={generateCode}>Gerar código</button><button type="button" disabled={waiting || locked || Boolean(blocked)} onClick={onNetwork}>Explorar rede</button></nav></div> : <div className="shell-start-empty"><p>Crie seu primeiro Dot para começar uma conversa.</p><button className="shell-primary" onClick={onCreateDot} disabled={Boolean(blocked)}>Criar assistente</button></div>}
  </section>;
}
