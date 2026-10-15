import React, { useEffect, useRef, useState } from 'react';
import { api, route } from './api';
import { Modal } from './primitives';
import { ShellMessageWindow } from './shell-message-window';
import { readStreamContent } from './shell-stream-content.js';

export function ShellStreamContent({ scope, preview, onAccessDenied }) {
  const [selection, setSelection] = useState(null), [result, setResult] = useState(null);
  const [error, setError] = useState(''), [progress, setProgress] = useState(null);
  const scroll = useRef(null), trigger = useRef(null);
  const operation = preview?.operation_id;
  const scopeKey = JSON.stringify([scope.project_id, scope.space_id, scope.conversation_id, operation]);
  const currentKey = useRef(scopeKey), readEpoch = useRef(0); currentKey.current = scopeKey;
  const denied = useRef(onAccessDenied); denied.current = onAccessDenied;
  function close() { readEpoch.current++; setSelection(null); setResult(null); setError(''); setProgress(null); }
  function select() {
    setResult(null); setError(''); setProgress(null);
    setSelection({ scope: { project_id: scope.project_id, space_id: scope.space_id, conversation_id: scope.conversation_id },
      reference: { ...preview.content_ref }, operation, sequence: preview.sequence, scopeKey, epoch: ++readEpoch.current });
  }
  useEffect(() => { close(); }, [scope.project_id, scope.space_id, scope.conversation_id, operation]);
  useEffect(() => {
    const failed = () => close();
    window.addEventListener('sentra:auth-recovery-failed', failed);
    return () => window.removeEventListener('sentra:auth-recovery-failed', failed);
  }, []);
  useEffect(() => {
    if (!selection) return;
    let active = true;
    const valid = () => active && currentKey.current === selection.scopeKey && readEpoch.current === selection.epoch;
    const controller = new AbortController();
    let timedOut = false, timeout;
    const armTimeout = () => { clearTimeout(timeout); timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 30000); };
    armTimeout();
    void readStreamContent((fields, options) => api(route('/api/shell/stream/content', fields), undefined, options),
      selection.scope, selection.reference, { signal: controller.signal,
        onProgress: value => { if (valid()) { armTimeout(); setProgress(value); } } }).then(value => {
          clearTimeout(timeout);
          if (valid()) { setResult(value); scroll.current?.scrollTo({ top: 0 }); }
        }).catch(error => {
          clearTimeout(timeout);
          if (!valid() || (error.name === 'AbortError' && !timedOut)) return;
          setResult(null);
          if ([401, 403].includes(error.status)) denied.current?.(error);
          setError(timedOut ? 'A consulta ficou sem resposta. A prévia na conversa foi preservada; nenhuma mensagem foi reenviada.' :
            error.status === 404 ? 'Esta prévia não está mais disponível. Consulte uma prévia mais recente ou a mensagem no histórico.' :
            [401, 403].includes(error.status) ? 'O acesso à prévia não está mais autorizado.' : error.message);
        });
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [selection]);
  const newer = selection && preview?.content_ref?.reference_id !== selection.reference.reference_id && preview?.content_ref;
  return <>
    {preview?.content_error && <p className="shell-preview-content-error" role="status">A prévia excedeu o limite recuperável. Consulte o original no histórico quando a mensagem for confirmada.</p>}
    {preview?.truncated && preview?.content_ref && operation && <button ref={trigger} className="shell-read-preview" type="button" onClick={select}>Ver prévia completa</button>}
    {selection?.scopeKey === scopeKey && <Modal open onOpenChange={open => { if (!open) close(); }} title="Prévia salva · ainda não confirmada"
      description="Conteúdo preservado no momento da consulta. A resposta ainda pode mudar." className="shell-modal shell-stream-content-modal"
      onCloseAutoFocus={event => {
        event.preventDefault();
        if (currentKey.current === selection.scopeKey && trigger.current?.isConnected) trigger.current.focus();
      }}>
      <div className="shell-stream-content-panel" data-authoritative="false" data-reference={selection.reference.reference_id}>
        {error && <p className="shell-error" role="alert">{error}</p>}
        {!result && !error && <p role="status">{progress ? `${progress.loaded_chars.toLocaleString('pt-BR')} de ${progress.total_chars.toLocaleString('pt-BR')} caracteres consultados…` : 'Consultando prévia salva…'}</p>}
        {newer && <button type="button" onClick={select}>Consultar prévia mais recente</button>}
        {result && <><p className="shell-preview-count">{result.total_chars.toLocaleString('pt-BR')} caracteres recuperados · prévia</p>
          <div className="shell-stream-full-pages" ref={scroll} tabIndex={0} aria-label="Conteúdo da prévia salva">
            <ShellMessageWindow items={result.items} scrollRef={scroll} follow={false} label="Páginas da prévia salva">{page =>
              <pre className="shell-stream-content-page" data-page={page.message_id}>{page.content}</pre>}</ShellMessageWindow>
          </div></>}
      </div>
    </Modal>}
  </>;
}
