import React, { useEffect, useRef, useState } from 'react';
import { ArrowUp, Download, MessageCircle, Search, Users } from 'lucide-react';
import { OperationReceipt, Status } from './shell-receipts';
import { ShellVoice } from './shell-voice';
import { ConversationMarkdown } from './shell-markdown';
import { ShellGeneratedAssets } from './shell-generated-assets';
import { DotMascot } from './shell-mascot';
import { ShellAttachments } from './shell-attachments';
import { completeMessage, messageContentKey } from './shell-message-content';
import { ShellTurnPermissions } from './shell-turn-permissions';
import { ShellAccess } from './shell-access';
import { ShellGoalDialog } from './shell-goals';
import { shellCommand } from './shell-commands';
import { mergeMessages } from './shell-chat-state';
import { api, route } from './api';
import { Modal } from './primitives';

function readDraft(key) {
  try { return JSON.parse(sessionStorage.getItem(key)) || { content: '', pending: null }; }
  catch { return { content: '', pending: null }; }
}
function downloadMarkdown(conversation, messages) {
  const text = '# ' + conversation.title + '\n\n' + messages.map(message =>
    '## ' + (message.role || 'message') + '\n\n' + message.content + '\n\n' +
    (message.receipt_id ? '> Recibo: ' + message.receipt_id + '\n' : '')).join('\n');
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url;
  anchor.download = (conversation.title || 'conversa').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 100) + '.md';
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function ShellConversation({ conversation, dot, bridge, onCoordinate, onModel, onCanvas, onTools, onChanged, voice }) {
  const scope = { project_id: conversation.project_id, space_id: conversation.space_id, conversation_id: conversation.conversation_id };
  const draftKey = 'sentra_shell_draft:' + scope.project_id + ':' + scope.conversation_id;
  const initial = useRef(readDraft(draftKey));
  const [content, setContent] = useState(initial.current.content), [pending, setPending] = useState(initial.current.pending);
  const [messages, setMessages] = useState([]), [page, setPage] = useState(null), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [loading, setLoading] = useState(true), [filter, setFilter] = useState('');
  const [loadError, setLoadError] = useState('');
  const [receipt, setReceipt] = useState(null), [follow, setFollow] = useState(true);
  const [fileApproval, setFileApproval] = useState(null), [fileApprovalBusy, setFileApprovalBusy] = useState(false);
  const [fileTestBusy, setFileTestBusy] = useState(false), [fileTest, setFileTest] = useState(null);
  const [fileConsent, setFileConsent] = useState(null);
  const [fileJobsOpen, setFileJobsOpen] = useState(false);
  const [fileJobs, setFileJobs] = useState([]);
  const [fileJobsLoading, setFileJobsLoading] = useState(false);
  const [fileJobsError, setFileJobsError] = useState('');
  const [terminalApproval, setTerminalApproval] = useState(null);
  const [deliveryChecks, setDeliveryChecks] = useState({});
  const [deliveryLoading, setDeliveryLoading] = useState('');
  const [livePreview, setLivePreview] = useState(null);
  const activityRef = useRef(false), refreshRef = useRef(null), liveRefreshRef = useRef(null);
  const messagesRef = useRef(messages); messagesRef.current = messages;
  const lastMessage = messages[messages.length - 1];
  const activeResponse = Boolean(busy || pending || (lastMessage?.role === 'user' &&
    ['sending', 'queued', 'running', 'dispatched', 'pending'].includes(lastMessage.status)));
  activityRef.current = activeResponse;
  useEffect(() => {
    let active = true, timer, refreshing = false;
    const refresh = async () => {
      if (!active || refreshing) return;
      clearTimeout(timer); refreshing = true;
      try {
        if (document.hidden) return;
        const result = await api(route('/api/shell/live', {
          project_id: scope.project_id, space_id: scope.space_id,
          conversation_id: scope.conversation_id,
        }));
        if (active) setLivePreview(['generating', 'confirming'].includes(result?.status) ? result : null);
      } catch { if (active) setLivePreview(null); }
      finally { refreshing = false; if (active) timer = setTimeout(refresh, activityRef.current ? 350 : 4000); }
    };
    liveRefreshRef.current = refresh;
    void refresh();
    return () => { active = false; clearTimeout(timer); liveRefreshRef.current = null; };
  }, [scope.project_id, scope.space_id, scope.conversation_id]);
  function adoptFileWorkItem(job) {
    if (!job) { setFileApproval(null); return; }
    const caps = job.granted_capabilities || [];
    setFileApproval({ work_item_id: job.work_item_id, grants: caps });

  }
  function adoptTerminalWorkItem(job) {
    const caps = job?.granted_capabilities || [];
    if (!job || !['terminal:start', 'terminal:read', 'terminal:write', 'terminal:close']
      .every(cap => caps.includes(cap))) { setTerminalApproval(null); return; }
    setTerminalApproval({ work_item_id: job.work_item_id, grants: caps });
  }
  async function inspectDelivery(message) {
    const oid = message?.operation_id;
    if (!oid || deliveryLoading) return;
    setDeliveryLoading(oid);
    try {
      const result = await api(route('/api/shell/delivery', { ...scope, operation_id: oid }));
      setDeliveryChecks(old => ({ ...old, [oid]: result }));
    } catch (e) {
      setDeliveryChecks(old => ({ ...old, [oid]: { status: 'read_error',
        message: 'Não foi possível consultar o registro: ' + e.message } }));
    } finally { setDeliveryLoading(''); }
  }
  async function fetchFileJobs() {
    try {
      return await api(route('/api/center/task/files', {
        ws: scope.project_id, conversation_id: scope.conversation_id,
      }));
    } catch (error) {
      if (error.status !== 404) throw error;
      // During a coordinated backend restart only, use the existing
      // read-only policy-filtered machine catalog; it cannot create Grants.
      const fallback = await api(route('/api/center/machines', { ws: scope.project_id }));
      const available = new Set((fallback.machines || []).filter(machine =>
        machine.kind === 'workspace-files' && machine.agent_id === dot?.agent_id)
        .map(machine => machine.machine_id));
      return { machine_configured: available.size > 0,
        items: (fallback.work_items || []).filter(item =>
          available.has(item.machine_id) && item.conversation_id === scope.conversation_id)
          .map(item => ({
            work_item_id: item.work_item_id, machine_id: item.machine_id,
            state: 'RUNNING', objective: item.objective,
            requested_capabilities: item.capabilities || [],
            granted_capabilities: item.capabilities || [],
            authorized: Boolean(item.capabilities?.length),
          })) };
    }
  }
  async function refreshFileJobs() {
    setFileJobsLoading(true); setFileJobsError('');
    try {
      const result = await fetchFileJobs();
      const jobs = result.items || [];
      setFileJobs(jobs);
      const current = jobs.find(job => job.kind === 'workspace-files' &&
        job.work_item_id === fileApproval?.work_item_id && job.authorized);
      const usable = current || jobs.find(job => job.kind === 'workspace-files' && job.authorized);
      if (usable) adoptFileWorkItem(usable);
      else setFileApproval(null);
      const terminal = jobs.find(job => job.kind === 'terminal' && job.authorized);
      adoptTerminalWorkItem(terminal);
      return jobs;
    } catch (e) { setFileJobsError(e.message); throw e; }
    finally { setFileJobsLoading(false); }
  }
  useEffect(() => {
    let active = true;
    setFileApproval(null); setTerminalApproval(null);
    setDeliveryChecks({}); setFileJobs([]); setFileJobsError(''); setFileTest(null);
    if (dot?.agent_id) {
      fetchFileJobs().then(result => {
        if (!active) return;
        const jobs = result.items || [];
        setFileJobs(jobs);
        const usable = jobs.find(job => job.kind === 'workspace-files' && job.authorized);
        if (usable) adoptFileWorkItem(usable);
        const terminal = jobs.find(job => job.kind === 'terminal' && job.authorized);
        if (terminal) adoptTerminalWorkItem(terminal);
      }).catch(e => { if (active) setFileJobsError(e.message); });
    }
    return () => { active = false; };
  }, [scope.project_id, scope.conversation_id, dot?.agent_id]);
  const [goalDialog, setGoalDialog] = useState(null);
  const [fullContents, setFullContents] = useState({}), [readingContent, setReadingContent] = useState(null);
  const fullCache = useRef(new Map());
  const [attachments, setAttachments] = useState(initial.current.attachments || []), [attachmentBusy, setAttachmentBusy] = useState(false);
  const [pendingAttachment, setPendingAttachment] = useState(initial.current.pendingAttachment || null), [exporting, setExporting] = useState(false);
  const alive = useRef(true), list = useRef(null), loadingRef = useRef(false), submitLock = useRef(false);
  const bridgeRef = useRef(bridge); bridgeRef.current = bridge;
  useEffect(() => {
    try { sessionStorage.setItem(draftKey, JSON.stringify({ content, pending, attachments, pendingAttachment })); } catch { /* Current draft remains in memory. */ }
  }, [content, pending, attachments, pendingAttachment, draftKey]);
  useEffect(() => {
    alive.current = true;
    let active = true, timer;
    const load = async () => {
      if (!active || loadingRef.current || document.hidden) return;
      loadingRef.current = true;
      try {
        const result = await bridgeRef.current({ action: 'message_list', ...scope, offset: 0, limit: 50 });
        if (!alive.current) return;
        setMessages(old => mergeMessages(old, result.items || [])); setPage(previous => previous || result.page);
        setReceipt(previous => previous?.message_id ? result.items?.find(row => row.message_id === previous.message_id) || previous : previous);
        if (result.page?.total > 50) {
          const latest = await bridgeRef.current({ action: 'message_list', ...scope, offset: Math.max(0, result.page.total - 50), limit: 50 });
          if (alive.current) setMessages(old => mergeMessages(old, latest.items || []));
          if (alive.current) setReceipt(previous => previous?.message_id ? latest.items?.find(row => row.message_id === previous.message_id) || previous : previous);
        }
        setLoadError('');
      } catch (e) { if (alive.current) setLoadError(e.message); }
      finally { loadingRef.current = false; if (alive.current) setLoading(false); }
    };
    const poll = async () => {
      clearTimeout(timer);
      await load();
      if (active) { clearTimeout(timer); timer = setTimeout(poll, activityRef.current ? 500 : 6000); }
    };
    refreshRef.current = poll;
    void poll();
    return () => { active = false; alive.current = false; clearTimeout(timer); refreshRef.current = null; };
  }, [conversation.conversation_id, conversation.project_id]);
  useEffect(() => {
    if (activeResponse) { void refreshRef.current?.(); void liveRefreshRef.current?.(); }
  }, [activeResponse]);
  useEffect(() => {
    const resume = () => { if (!document.hidden) { void refreshRef.current?.(); void liveRefreshRef.current?.(); } };
    document.addEventListener('visibilitychange', resume);
    return () => document.removeEventListener('visibilitychange', resume);
  }, []);
  useEffect(() => { if (follow && list.current) list.current.scrollTop = list.current.scrollHeight; }, [messages, receipt, livePreview?.content, follow]);
  useEffect(() => {
    if (!pending) return;
    const canonical = messages.find(message => message.request_key === pending.request_key && !message.optimistic);
    if (canonical && !['uncertain', 'unconfirmed'].includes(canonical.status)) {
      setPending(null); setAttachments([]);
    }
  }, [messages, pending]);
  useEffect(() => {
    const restored = initial.current.pending;
    if (restored) setMessages(old => mergeMessages(old, [{ ...scope, role: 'user', content: restored.content,
      message_id: 'local-' + restored.request_key, request_key: restored.request_key,
      optimistic: true, status: 'uncertain', created_at: new Date().toISOString() }]));
  }, []);
  useEffect(() => {
    const before = e => { if (content.trim() || pending) { e.preventDefault(); e.returnValue = ''; } };
    addEventListener('beforeunload', before); return () => removeEventListener('beforeunload', before);
  }, [content, pending]);
  async function loadMore() {
    setBusy(true);
    try {
      const result = await bridge({ action: 'message_list', ...scope, offset: page.next_offset, limit: 50 });
      setMessages(old => mergeMessages(old, result.items || [])); setPage(result.page); setFollow(false);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function send(reconcile = false, messageContent = content) {
    if (submitLock.current || attachmentBusy || pendingAttachment || (!reconcile && (busy || !messageContent.trim() || pending))) return;
    const nativeImage = !reconcile && /^\/image(?:\s|$)/i.test(messageContent.trim());
    if (nativeImage) {
      messageContent = messageContent.trim().replace(/^\/image\s*/i, '');
      if (!messageContent.trim()) { setError('Descreva a imagem depois de /image.'); return; }
    }
    const command = !reconcile && !nativeImage && shellCommand(messageContent);
    if (command) {
      setContent('');
      if (command.name === 'model') onModel(command.argument); else setGoalDialog({ argument: command.argument });
      return;
    }
    submitLock.current = true; setBusy(true); setError('');
    const request = reconcile ? pending : { action: 'message_send', ...scope, content: messageContent, request_key: crypto.randomUUID(),
      ...(nativeImage ? { native_generation:'image' } : {}),
      ...(attachments.length ? { attachments: attachments.map(item => item.attachment_id) } : {}) };
    if (!request) { submitLock.current = false; setBusy(false); return; }
    // Persist the exact payload and key before touching transport, including across a reload.
    setPending(request);
    if (!reconcile) {
      setMessages(old => mergeMessages(old, [{ ...scope, message_id: 'local-' + request.request_key,
        request_key: request.request_key, role: 'user', content: request.content, optimistic: true,
        status: 'sending', created_at: new Date().toISOString() }]));
      setContent(''); setFollow(true);
    }
    try { sessionStorage.setItem(draftKey, JSON.stringify({ content, pending: request, attachments, pendingAttachment })); } catch { /* Memory copy is retained. */ }
    try {
      const result = await bridge(request);
      if (!alive.current) return;
      setReceipt(result);
      setMessages(old => mergeMessages(old, [{ ...scope, message_id: result.message_id, role: 'user', content: request.content,
        request_key: request.request_key, optimistic: false, status: result.status, operation_id: result.operation_id,
        receipt_id: result.receipt_id, created_at: new Date().toISOString() }]));
      if (result.status === 'uncertain') { setError('O envio permanece incerto. Consulte esta mesma chave antes de enviar outra mensagem.'); return; }
      setPending(null); setContent(''); setAttachments([]);
      void refreshRef.current?.();
      setFollow(true); onChanged();
    } catch (e) {
      if (!alive.current) return;
      const known = messagesRef.current.find(message => message.request_key === request.request_key && !message.optimistic);
      if (e.uncertain && known && !['uncertain', 'unconfirmed'].includes(known.status)) {
        setReceipt(known); setPending(null); setAttachments([]); return;
      }
      setError(e.message);
      if (!e.uncertain) {
        setPending(null); setContent(request.content);
        setMessages(old => old.filter(message => !(message.optimistic && message.request_key === request.request_key)));
      } else {
        setMessages(old => old.map(message => message.request_key === request.request_key && message.optimistic ?
          { ...message, status: 'uncertain' } : message));
        setReceipt({ status: 'uncertain', request_key: request.request_key });
      }
    } finally { submitLock.current = false; if (alive.current) setBusy(false); }
  }
  async function attach(request = pendingAttachment) {
    if (!request) return;
    setBusy(true);
    setPendingAttachment(request);
    try {
      const result = await bridge(request);
      const stored = result.attachments;
      if (!Array.isArray(stored) || stored.some(item => !item.attachment_id || !item.sha256)) throw Error('O servidor não confirmou o armazenamento do anexo.');
      setAttachments(old => [...old.filter(item => !stored.some(row => row.attachment_id === item.attachment_id)), ...stored]);
      setPendingAttachment(null); return true;
    } catch (e) { setError(e.message); if (!e.uncertain) setPendingAttachment(null); return false; } finally { setBusy(false); }
  }
  async function exportConversation() {
    if (exporting) return; setExporting(true); setError('');
    try {
      let offset = 0, values = [];
      do {
        const result = await bridge({ action: 'message_list', ...scope, offset, limit: 200 });
        values = mergeMessages(values, result.items || []); offset = result.page?.next_offset ?? null;
      } while (offset !== null);
      const complete = [];
      for (const message of values) complete.push(await readComplete(message));
      if (alive.current) downloadMarkdown(conversation, complete);
    } catch (e) { setError(e.message); } finally { if (alive.current) setExporting(false); }
  }
  async function readComplete(message) {
    const key = messageContentKey(message);
    if (fullCache.current.has(key)) return fullCache.current.get(key);
    const value = await completeMessage(message, bridgeRef.current, scope, () => alive.current);
    if (alive.current && message.content_truncated) {
      fullCache.current.set(key, value); setFullContents(old => ({ ...old, [key]: value.content }));
    }
    return value;
  }
  async function readOriginal(message, exportingMessage = false) {
    if (readingContent) return;
    setReadingContent(messageContentKey(message)); setError('');
    try { const value = await readComplete(message);
      if (alive.current && exportingMessage) downloadMarkdown({ ...conversation, title: (conversation.title || 'Conversa') + ' — mensagem' }, [value]);
    } catch (e) { if (alive.current) setError(e.message); }
    finally { if (alive.current) setReadingContent(null); }
  }
  async function revokeWorkspaceFiles() {
    if ((!fileApproval?.work_item_id && !terminalApproval?.work_item_id) || fileApprovalBusy || fileTestBusy) return;
    if (fileConsent !== 'revoke') return;
    setFileApprovalBusy(true); setError('');
    try {
      // Revoke each independently; never blindly retry a mutation if the acknowledgement is lost.
      const identifiers = [...new Set(fileJobs.filter(job => job.authorized)
        .map(job => job.work_item_id).concat([terminalApproval?.work_item_id, fileApproval?.work_item_id])
        .filter(Boolean))];
      for (const work_item_id of identifiers) {
        const result = await api('/api/center/task/revoke', { ws: scope.project_id,
          work_item_id, conversation_id: scope.conversation_id, approve: true });
        if (result.access !== 'revoked') throw Error('Revogação não confirmada para ' + work_item_id);
      }
      setFileApproval(null); setTerminalApproval(null); setFileConsent(null);
      await refreshFileJobs(); onChanged();
    } catch (e) { setError(e.message); setFileJobsOpen(true); } finally { setFileApprovalBusy(false); }
  }
  async function testWorkspaceFiles() {
    if (!fileApproval?.work_item_id || fileTestBusy || busy ||
        !['workspace:file.read', 'workspace:file.write', 'workspace:file.delete']
          .every(cap => fileApproval.grants?.includes(cap))) return;
    const operationLog = [];
    const filename = 'sentra_teste.txt';
    setFileTestBusy(true); setFileTest({ steps: [], status: 'running' }); setError('');
    try {
      const inventory = await bridge({ action: 'machine_list', ...scope });
      const machine = inventory.machines?.find(row => row.kind === 'workspace-files' && row.agent_id === dot?.agent_id);
      const work = inventory.work_items?.find(row => row.work_item_id === fileApproval.work_item_id && row.machine_id === machine?.machine_id);
      if (!machine || !work) throw Error('O WorkItem de arquivos não está mais autorizado nesta conversa.');
      const perform = async (label, capability_id, argumentsValue) => {
        if (!work.capabilities?.includes(capability_id)) throw Error('A capacidade ' + capability_id + ' não está autorizada.');
        const value = await bridge({ action: 'machine_execute', ...scope,
          machine_id: machine.machine_id, work_item_id: work.work_item_id, capability_id,
          arguments: argumentsValue, request_key: crypto.randomUUID() });
        operationLog.push({ label, state: value.state || value.status, operation_id: value.operation_id });
        setFileTest({ steps: [...operationLog], status: 'running' });
        if (value.state !== 'SUCCEEDED') {
          throw Error(label + ': operação não confirmada (' + (value.state || value.status || 'desconhecido') + '). ' +
            'Consulte o operation_id informado antes de tentar outra execução.');
        }
        return value.evidence?.payload || value.evidence || {};
      };
      const initial = await perform('Confirmar ausência inicial', 'workspace:file.read', { action: 'stat', path: filename });
      if (initial.exists !== false) throw Error('Arquivo existente: teste interrompido para preservar seu conteúdo.');
      const text1 = 'Teste inicial do SENTRA';
      const text2 = 'Teste de edição realizado com sucesso';
      const created = await perform('Criar e escrever', 'workspace:file.write', { action: 'write', path: filename, content: text1 });
      if (created.exists !== true) throw Error('O servidor não confirmou a criação.');
      const first = await perform('Ler conteúdo inicial', 'workspace:file.read', { action: 'read', path: filename });
      if (first.content !== text1 || !first.sha256) throw Error('O conteúdo inicial não corresponde à escrita.');
      const edited = await perform('Editar conteúdo', 'workspace:file.write',
        { action: 'edit', path: filename, content: text2, expected_sha256: first.sha256 });
      if (edited.exists !== true) throw Error('A edição não foi confirmada.');
      const second = await perform('Ler conteúdo editado', 'workspace:file.read', { action: 'read', path: filename });
      if (second.content !== text2 || !second.sha256) throw Error('O conteúdo editado não corresponde ao esperado.');
      const removed = await perform('Excluir arquivo', 'workspace:file.delete',
        { action: 'delete', path: filename, expected_sha256: second.sha256 });
      if (removed.exists !== false) throw Error('A exclusão não foi confirmada.');
      const finalState = await perform('Confirmar ausência final', 'workspace:file.read',
        { action: 'stat', path: filename });
      if (finalState.exists !== false) throw Error('O arquivo ainda existe após a exclusão.');
      setFileTest({ steps: [...operationLog], status: 'succeeded' });
    } catch (e) {
      setFileTest({ steps: [...operationLog], status: 'stopped', error: e.message });
    } finally { setFileTestBusy(false); }
  }
  function prepareInteractiveUiDraft(text) {
    // Model-generated UI cannot itself submit a turn or acquire tool grants.
    if (busy || pending || activeResponse || attachmentBusy || pendingAttachment || attachments.length || submitLock.current) {
      setError('Finalize o envio atual e os anexos antes de preparar respostas ao painel.');
      return false;
    }
    if (content.trim() && content !== text && !window.confirm('Substituir o rascunho atual pelas respostas do painel?')) return false;
    setContent(text);
    setError('');
    return true;
  }
  const latest = messages[messages.length - 1];
  const latestStatus = String(latest?.status || '').toLowerCase();
  const waitingApproval = latestStatus === 'waiting_approval' || receipt?.status === 'waiting_approval';
  const inFlight = !loading && !loadError && !error && !waitingApproval &&
    (Boolean(submitLock.current) || (latest?.role === 'user' &&
      ['sending', 'queued', 'running', 'dispatched', 'pending'].includes(latestStatus)));
  const showLivePreview = livePreview && !messages.some(message => message.role === 'assistant' &&
    message.operation_id === livePreview.operation_id);
  return <section className="shell-chat" aria-label={'Conversa com ' + (dot?.name || 'Dot')}>
    <header className="shell-chat-heading"><div className="shell-persona"><DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id} name={dot?.name} status={dot?.status} size="small" decorative />
      <div><h2>{conversation.title || dot?.name || 'Conversa'}</h2><p>{dot?.name} · {dot?.model || 'Modelo não informado'} {dot?.effort && '· ' + dot.effort}</p></div></div>
      <div className="shell-chat-actions"><button onClick={() => onModel('')}>/model</button><button onClick={() => setGoalDialog({ argument: '' })}>/goal</button>
        <button onClick={onCanvas}>Canvas do Dot</button><button onClick={onCoordinate}><Users size={15} /> Coordenar</button>
        <button onClick={() => onTools('history')} aria-label="Pesquisar histórico"><Search size={16} /></button>
        <button onClick={exportConversation} disabled={exporting || !messages.length} title="Exportar conversa em Markdown" aria-label="Exportar conversa"><Download size={16} /></button></div>
    </header>
    <label className="shell-chat-filter"><Search size={14} /><input value={filter} onChange={e => setFilter(e.target.value)} placeholder="Buscar nesta conversa" aria-label="Buscar nas mensagens carregadas" /></label>
    <div className="shell-transcript" ref={list} role="log" aria-live="polite" aria-relevant="additions text"
      onScroll={e => setFollow(e.currentTarget.scrollHeight - e.currentTarget.scrollTop - e.currentTarget.clientHeight < 90)}>
      {page?.next_offset != null && <button disabled={busy} onClick={loadMore}>Carregar mais mensagens</button>}
      {loading && <p className="shell-empty">Consultando mensagens…</p>}
      {!loading && !messages.length && <div className="shell-chat-intro"><DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id} name={dot?.name} status={dot?.status} size="intro" decorative /><h3>Uma conversa que continua.</h3><p>Descreva seu objetivo para {dot?.name || 'este Dot'}.</p></div>}
      {messages.filter(message => String(message.content || '').toLowerCase().includes(filter.toLowerCase())).map(message =>
        <article className={'shell-message ' + (message.role === 'user' ? 'from-user' : '')} key={message.message_id}>
          <header>{message.role === 'assistant' && <DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id} name={dot?.name} status={dot?.status} size="message" decorative />}
            <strong>{message.role === 'user' ? 'Você' : message.role === 'assistant' ? dot?.name || 'Dot' : message.role}</strong>
            <time>{message.created_at ? new Date(message.created_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : ''}</time></header>
          <div className="shell-message-content">{fullContents[messageContentKey(message)] !== undefined ?
            <pre className="shell-message-original">{fullContents[messageContentKey(message)]}</pre> :
            message.role === 'user' ? message.content : <ConversationMarkdown content={message.content}
              onReply={message.role === 'assistant' && !message.content_truncated ? prepareInteractiveUiDraft : undefined} />}</div>
          <ShellGeneratedAssets message={message} scope={scope} /><OperationReceipt value={message} />
          {message.content_truncated && fullContents[messageContentKey(message)] === undefined && <div className="shell-notice">
            Preview do original ({message.content_ref?.total_chars} caracteres). <button disabled={Boolean(readingContent)} onClick={() => readOriginal(message)}>
              {readingContent === messageContentKey(message) ? 'Lendo original…' : 'Ler original completo'}</button></div>}
          {['uncertain', 'unconfirmed'].includes(String(message.status || '').toLowerCase()) &&
            message.operation_id && <div className="shell-delivery-inspection">
              <button type="button" onClick={() => void inspectDelivery(message)}
                disabled={Boolean(deliveryLoading)}>
                {deliveryLoading === message.operation_id ? 'Consultando…' : 'Consultar diagnóstico sem reenviar'}
              </button>
              {deliveryChecks[message.operation_id] && <p role="status">
                {deliveryChecks[message.operation_id].message}
                {deliveryChecks[message.operation_id].reason_code &&
                  <small> · Motivo: {deliveryChecks[message.operation_id].reason_code}</small>}
              </p>}
            </div>}
          {!message.optimistic && <button className="shell-message-export" disabled={Boolean(readingContent)} onClick={() => readOriginal(message, true)}><Download size={12} />Exportar mensagem completa</button>}
          {message.attachments?.map(item => <p key={item.attachment_id}>Anexo: {item.name || item.attachment_id} <Status value={item.status} /></p>)}
        </article>)}
      {showLivePreview && livePreview?.content && <article className="shell-message shell-live-preview" aria-label="Resposta parcial, ainda não confirmada">
        <header><DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id}
          name={dot?.name} status="working" size="message" decorative />
          <strong>{dot?.name || 'Dot'}</strong><small>{livePreview.activity || 'Escrevendo em tempo real'} · prévia</small></header>
        <div className="shell-message-content"><ConversationMarkdown content={livePreview.content} /></div>
      </article>}
      {inFlight && !(showLivePreview && livePreview?.content) && <div className="shell-thinking" role="status" aria-live="polite" aria-label={(dot?.name || 'Dot') + ' está processando a mensagem'}>
        <DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id} name={dot?.name} status="working" size="message" decorative />
        <span className="shell-thinking-label">{busy ? 'Preparando envio' : livePreview?.activity || 'Aguardando resposta'}</span>
        <span className="shell-thinking-dots" aria-hidden="true"><i /><i /><i /></span>
      </div>}
      {waitingApproval && latest?.role === 'user' && <p className="shell-notice" role="status">Aguardando aprovação das permissões necessárias para continuar.</p>}
    </div>
    <div className="shell-composer-wrap">
      {(error || loadError) && <div className="shell-error" role="alert">{error || loadError}</div>}
      {receipt && <OperationReceipt value={receipt} />}
      {fileTest && <div className="shell-file-test" role="status" aria-live="polite">
        <strong>{fileTest.status === 'succeeded' ? 'Teste real de arquivos concluído' :
          fileTest.status === 'running' ? 'Testando arquivos do projeto…' : 'Teste interrompido'}</strong>
        {fileTest.steps.map((step, index) => <div key={index}>{step.state === 'SUCCEEDED' ? '✓ ' : '• '}
          {step.label}: {step.state || 'não confirmado'} {step.operation_id && <small>· {step.operation_id}</small>}</div>)}
        {fileTest.error && <p className="shell-error">{fileTest.error}</p>}
      </div>}
      {pending && <div className="shell-notice" role="status">Envio preservado para consulta. <button disabled={busy} onClick={() => send(true)}>Consultar envio</button><small>Chave: {pending.request_key}</small></div>}
      <form className="shell-composer" onSubmit={e => { e.preventDefault(); void send(); }}>
        {content.trim().startsWith('/') && !content.trim().includes(' ') && <div className="shell-command-menu" role="group" aria-label="Comandos da conversa">
          {['model', 'goal', 'image'].filter(name => ('/' + name).startsWith(content.trim().toLowerCase())).map(name => <button key={name} type="button" onClick={() => { setContent(name === 'image' ? '/image ' : ''); if (name === 'model') onModel(''); else if (name === 'goal') setGoalDialog({ argument: '' }); }}>
            /{name} <span>{name === 'model' ? 'Escolher modelo deste Dot' : name === 'goal' ? 'Objetivo persistente desta conversa' : 'Criar imagem'}</span></button>)}</div>}
        <textarea value={content} onChange={e => setContent(e.target.value)} maxLength={100000} disabled={Boolean(pending)}
          placeholder={'Mensagem para ' + (dot?.name || 'o Dot') + '…'} aria-label="Mensagem"
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
        <div className="shell-composer-bottom">
          <ShellAccess bridge={bridge} scope={scope} onCustomize={() => setFileJobsOpen(true)} />
          <span className="shell-composer-hint">{pending ? 'Envio não confirmado' : 'Enter envia · Shift+Enter quebra linha'}</span>
          <button type="submit" className="shell-send" disabled={busy || attachmentBusy || Boolean(pending) || Boolean(pendingAttachment) || !content.trim()} aria-label="Enviar mensagem"><ArrowUp size={18} /></button>
        </div>
      </form>
      {pendingAttachment && <div className="shell-notice">Registro anterior de anexo ainda não confirmado.<button disabled={busy} onClick={() => attach()}>Consultar mesmo registro</button></div>}
      <div className="shell-chat-optionals"><ShellAttachments bridge={bridge} scope={scope} availability={voice?.attachments}
        attachments={attachments} onAttachments={setAttachments} onBusy={setAttachmentBusy} disabled={busy || Boolean(pending) || Boolean(pendingAttachment)} />
        <ShellVoice bridge={bridge} scope={scope} availability={voice} />
      </div>
    </div>
    {fileJobsOpen && <Modal open title="Personalizar · detalhes e trabalhos" className="shell-modal shell-access-details" onOpenChange={setFileJobsOpen}>
      <div className="shell-form">
        <div className="shell-code-actions">
          <button type="button" onClick={() => onTools('access')}>Confiança do chat</button>
          <button type="button" onClick={() => onTools('terminal')}>Máquinas e terminais</button>
          {(fileApproval || terminalApproval) && <button type="button" onClick={() => setFileConsent('revoke')}>Revogar permissões anteriores</button>}
          {fileApproval && <button type="button" disabled={fileTestBusy || busy} onClick={() => void testWorkspaceFiles()}>Testar arquivos do projeto</button>}
        </div>
      <section className="shell-file-workitems" aria-label="Trabalhos e permissões do Dot">
        <header><strong>Autorizações anteriores do Dot</strong>
          <button type="button" onClick={() => void refreshFileJobs().catch(() => {})} disabled={fileJobsLoading}>
            {fileJobsLoading ? 'Atualizando…' : 'Atualizar lista'}</button></header>
        <p>Permissões concedidas pelo fluxo anterior. As novas definições ficam no menu de acesso da conversa.</p>
        {fileJobsError && <p className="shell-error" role="alert">{fileJobsError}</p>}
        {!fileJobs.length && !fileJobsLoading && <p className="shell-notice">
          Nenhuma autorização anterior. Use o menu de acesso para escolher uma definição ou personalizar.
        </p>}
        {fileJobs.map(job => <div className="shell-file-job" key={job.work_item_id}>
          <div><strong>{job.kind === 'terminal' ? 'Terminal protegido · ' : 'Arquivos · '}
            {job.authorized ? 'Autorizado' : job.state === 'RUNNING' ? 'Permissões incompletas' : 'Inativo'}</strong>
            <small>{job.state} · {job.work_item_id}</small>
            <span>{job.kind === 'terminal' ?
              (job.granted_capabilities || []).filter(cap => cap.startsWith('terminal:')).join(' · ') :
              (job.granted_capabilities?.includes('workspace:file.read') ? 'Leitura' : 'Sem leitura') +
              (job.granted_capabilities?.includes('workspace:file.write') ? ' · Escrita' : '') +
              (job.granted_capabilities?.includes('workspace:file.delete') ? ' · Exclusão' : '')}</span></div>
          <button type="button" disabled={fileApprovalBusy || fileTestBusy ||
              (job.kind === 'terminal' ? terminalApproval : fileApproval)?.work_item_id === job.work_item_id}
            onClick={() => job.kind === 'terminal' ? adoptTerminalWorkItem(job) : adoptFileWorkItem(job)}>
            {(job.kind === 'terminal' ? terminalApproval : fileApproval)?.work_item_id === job.work_item_id ? 'Selecionado' : 'Selecionar'}</button>
        </div>)}
      </section>
      <div><ShellTurnPermissions bridge={bridge} scope={scope} /></div>
      </div>
    </Modal>}
    {fileConsent === 'revoke' && <Modal open onOpenChange={value => { if (!value && !fileApprovalBusy) setFileConsent(null); }}
      busy={fileApprovalBusy} className="shell-modal" title="Revogar permissões anteriores"
      description="Revogar os acessos de arquivos e terminal anteriormente concedidos nesta conversa.">
      <div className="shell-form"><footer><button type="button" disabled={fileApprovalBusy} onClick={() => setFileConsent(null)}>Cancelar</button>
        <button type="button" disabled={fileApprovalBusy} onClick={() => void revokeWorkspaceFiles()}>{fileApprovalBusy ? 'Registrando...' : 'Revogar'}</button></footer></div>
    </Modal>}
    {goalDialog && <ShellGoalDialog scope={scope} dot={dot} bridge={bridge} argument={goalDialog.argument} onClose={() => setGoalDialog(null)} onSend={text => send(false, text)} />}
  </section>;
}
