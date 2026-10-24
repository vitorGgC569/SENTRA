import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ShellMessageWindow } from './shell-message-window';
import { ShellStreamContent } from './shell-stream-content.jsx';
import { ArrowUp, Download, MessageCircle, Search, Users, Layers, SlidersHorizontal, Flag } from 'lucide-react';
import { OperationReceipt, Status } from './shell-receipts';
import { ShellVoice } from './shell-voice';
import { ConversationMarkdown } from './shell-markdown';
import { ShellGeneratedAssets } from './shell-generated-assets';
import { DotMascot } from './shell-mascot';
import { ShellAttachments } from './shell-attachments';
import { completeMessage, messageContentKey } from './shell-message-content';
import { ShellTurnPermissions } from './shell-turn-permissions';
import { ShellAccess } from './shell-access';
import {ConversationPermissionCards} from './shell-permission-cards';
import {ConversationTools} from './shell-conversation-tools';
import { ShellGoalDialog } from './shell-goals';
import { shellCommand } from './shell-commands';
import { matchesConversationStart } from './shell-conversation-start.js';
import { mergeMessages } from './shell-chat-state';
import { conversationCache } from './shell-conversation-cache';
import { readRecentMessagePage, recentPageDisposition } from './shell-message-pages';
import { inspectMessageRequest, confirmedMessageRequest } from './shell-message-request-status';
import { api, route } from './api';
import { presentLive, previewStillVisible, reconcileLivePreview } from './shell-live-feed.js';
import { subscribeShellStream } from './shell-stream.js';
import { feedMotion, useReducedMotion } from './experience/cadencia/index.js';
import { Modal, ActionMenu } from './primitives';
// Coucou visual layer: componentes e modelos puros da Frente 3.
import { ChatEventPill, ChatPresence, ChatThinking, ChatTicker, chatEventPillFor, chatPresenceModel, deriveChatTicker } from './shell-chat-visuals.jsx';

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
export function ShellConversation({ conversation, dot, bridge, onCoordinate, onModel, onCanvas, onTools, onChanged, voice, onResource, initialMessage, onInitialMessageHandled }) {
  const scope = { project_id: conversation.project_id, space_id: conversation.space_id, conversation_id: conversation.conversation_id };
  const draftKey = 'sentra_shell_draft:' + scope.project_id + ':' + scope.conversation_id;
  const initial = useRef(readDraft(draftKey));
  const lastAutomaticInspection = useRef(null);
  const startedMessage = useRef(null);
  const [content, setContent] = useState(initial.current.content), [pending, setPending] = useState(initial.current.pending);
  useEffect(()=>{const staged=event=>{if(event.detail?.project_id===scope.project_id&&event.detail?.conversation_id===scope.conversation_id&&!pending)setContent(old=>old.trim()?old:readDraft(draftKey).content||'')};window.addEventListener('sentra:draft-staged',staged);return()=>window.removeEventListener('sentra:draft-staged',staged)},[draftKey,pending]);
  const [messages, setMessages] = useState([]), [page, setPage] = useState(null), [busy, setBusy] = useState(false);
  const [cachedPreview, setCachedPreview] = useState(() => conversationCache.get(scope));
  const [historyVerified, setHistoryVerified] = useState(false);
  const [error, setError] = useState(''), [loading, setLoading] = useState(true), [filter, setFilter] = useState('');
  const [loadError, setLoadError] = useState('');
  const [renderAll, setRenderAll] = useState(false);
  const presentedMessages = useMemo(() => historyVerified || !cachedPreview ? messages :
    mergeMessages(cachedPreview.items, messages.map(message => ({ ...message, cached_visual: false }))), [messages, cachedPreview, historyVerified]);
  const filteredMessages = useMemo(() => {
    const query = filter.toLocaleLowerCase('pt-BR');
    return query ? presentedMessages.filter(message => String(message.content || '').toLocaleLowerCase('pt-BR').includes(query)) : presentedMessages;
  }, [presentedMessages, filter]);
  const [receipt, setReceipt] = useState(null), [follow, setFollow] = useState(true);
  const [recentPage, setRecentPage] = useState(null);
  const pageRef = useRef(page), followRef = useRef(follow);
  pageRef.current = page; followRef.current = follow;
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
  const [connectionState, setConnectionState] = useState('connecting');
  const streamState = useRef('connecting');
  const feedPrevious = useRef({});
  const activityRef = useRef(false), refreshRef = useRef(null), liveRefreshRef = useRef(null);
  const messagesRef = useRef(messages); messagesRef.current = messages;
  const readAccess = useRef(true), accessEpoch = useRef(0);
  const lastMessage = messages[messages.length - 1];
  const activeResponse = Boolean(busy || pending || (lastMessage?.role === 'user' &&
    ['sending', 'queued', 'running', 'dispatched', 'pending'].includes(lastMessage.status)));
  activityRef.current = activeResponse;
  useEffect(() => {
    streamState.current = 'connecting'; setConnectionState('connecting');
    return subscribeShellStream(scope, {
      onState: state => { streamState.current = state; setConnectionState(state); if (state === 'reauth_required') invalidateHistory(); },
      onPreview: value => {
        if (!readAccess.current) return;
        setLivePreview(previous => reconcileLivePreview(value, previous));
        if (value.status === 'committed') void refreshRef.current?.();
      },
    });
  }, [scope.project_id, scope.space_id, scope.conversation_id]);
  useEffect(() => {
    let active = true, timer, refreshing = false;
    setLivePreview(null);
    feedPrevious.current = {};
    const refresh = async () => {
      if (!active || refreshing) return;
      clearTimeout(timer); refreshing = true;
      const epoch = accessEpoch.current;
      try {
        if (document.hidden || ['connected', 'reauth_required'].includes(streamState.current)) return;
        const result = await api(route('/api/shell/live', {
          project_id: scope.project_id, space_id: scope.space_id,
          conversation_id: scope.conversation_id,
        }));
        if (active && readAccess.current && epoch === accessEpoch.current) setLivePreview(previous => reconcileLivePreview(result, previous));
      } catch (error) {
        if (active && epoch === accessEpoch.current) {
          if ([401, 403].includes(error.status)) {
            streamState.current = 'reauth_required';
            setConnectionState('reauth_required'); invalidateHistory();
          } else setLivePreview(previous => reconcileLivePreview(null, previous, { readFailed: true }));
        }
      }
      finally { refreshing = false; if (active) timer = setTimeout(refresh,
        streamState.current === 'connected' ? 10000 : activityRef.current ? 350 : 4000); }
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
    const epoch = accessEpoch.current;
    try {
      const result = await api(route('/api/shell/delivery', { ...scope, operation_id: oid }));
      if (!alive.current || epoch !== accessEpoch.current) return;
      setDeliveryChecks(old => ({ ...old, [oid]: result }));
    } catch (e) {
      if (!alive.current || epoch !== accessEpoch.current) return;
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
  function invalidateHistory() {
    accessEpoch.current++;
    readAccess.current = false;
    conversationCache.forget(scope); setCachedPreview(null); setHistoryVerified(false);
    setLivePreview(null);
    setMessages(old => old.filter(message => message.optimistic));
    setRecentPage(null); pageRef.current = null; setPage(null);
    setReceipt(null); setDeliveryChecks({});
    fullCache.current.clear(); setFullContents({});
  }
  useEffect(() => {
    const invalidate = () => invalidateHistory();
    window.addEventListener('sentra:auth-recovery-failed', invalidate);
    return () => window.removeEventListener('sentra:auth-recovery-failed', invalidate);
  }, [scope.project_id, scope.space_id, scope.conversation_id]);
  useEffect(() => {
    try { sessionStorage.setItem(draftKey, JSON.stringify({ content, pending, attachments, pendingAttachment })); } catch { /* Current draft remains in memory. */ }
  }, [content, pending, attachments, pendingAttachment, draftKey]);
  useEffect(() => {
    alive.current = true;
    let active = true, timer;
    const load = async () => {
      if (!active || loadingRef.current || document.hidden) return;
      loadingRef.current = true;
      const epoch = accessEpoch.current;
      try {
        const result = await readRecentMessagePage(bridgeRef.current, scope);
        if (!active || !alive.current || epoch !== accessEpoch.current) return;
        conversationCache.set(scope, result.items || []);
        const previous = pageRef.current;
        const disposition = recentPageDisposition(previous, result.page, followRef.current);
        if (disposition === 'defer') setRecentPage(result);
        else {
          setRecentPage(null);
          setMessages(old => mergeMessages(disposition === 'replace' ? old.filter(row => row.optimistic) : old, result.items));
          const nextPage = disposition === 'replace' ? result.page : { ...previous, total: result.page.total };
          pageRef.current = nextPage; setPage(nextPage);
        }
        readAccess.current = true; setHistoryVerified(true); setCachedPreview(null);
        setReceipt(previous => previous?.message_id ? result.items?.find(row => row.message_id === previous.message_id) || previous : previous);
        setLoadError('');
      } catch (e) {
        if (active && alive.current && epoch === accessEpoch.current) {
          setLoadError(e.message);
          if ([400, 401, 403, 404].includes(e.status)) {
            invalidateHistory();
          }
        }
      }
      finally { loadingRef.current = false; if (alive.current) setLoading(false); }
    };
    const poll = async () => {
      clearTimeout(timer);
      await load();
      // Live deltas arrive via the scoped preview poll. Full transcript snapshots
      // are heavier and are only needed to confirm durable message completion.
      if (active) { clearTimeout(timer); timer = setTimeout(poll,
        streamState.current === 'connected' ? 30000 : activityRef.current ? 1400 : 6000); }
    };
    refreshRef.current = poll;
    void poll();
    return () => { active = false; alive.current = false; clearTimeout(timer); refreshRef.current = null; };
  }, [conversation.conversation_id, conversation.project_id, conversation.space_id]);
  useEffect(() => {
    if (activeResponse) { void refreshRef.current?.(); void liveRefreshRef.current?.(); }
  }, [activeResponse]);
  useEffect(() => {
    const resume = () => { if (!document.hidden) { void refreshRef.current?.(); void liveRefreshRef.current?.(); } };
    document.addEventListener('visibilitychange', resume);
    return () => document.removeEventListener('visibilitychange', resume);
  }, []);
  useEffect(() => { if (follow && !filter && list.current) list.current.scrollTop = list.current.scrollHeight; }, [messages, receipt, livePreview?.content, follow, filter]);
  useEffect(() => { if (filter && list.current) list.current.scrollTop = 0; }, [filter]);
  useEffect(() => {
    if (!Number.isFinite(livePreview?.received_at_ms)) return;
    const started = livePreview.received_at_ms;
    let second;
    const first = requestAnimationFrame(() => { second = requestAnimationFrame(() => {
      window.dispatchEvent(new CustomEvent('sentra:stream-metric', { detail: {
        kind: 'receive_to_frame', duration_ms: Math.max(0, performance.now() - started),
        sequence: livePreview.sequence,
      } }));
    }); });
    return () => { cancelAnimationFrame(first); if (second) cancelAnimationFrame(second); };
  }, [livePreview?.sequence]);
  useEffect(() => {
    if (!pending) { lastAutomaticInspection.current = null; return; }
    const canonical = messages.find(message => message.request_key === pending.request_key && !message.optimistic);
    if (!busy && canonical && !['uncertain', 'unconfirmed'].includes(canonical.status) && lastAutomaticInspection.current !== pending.request_key) {
      lastAutomaticInspection.current = pending.request_key;
      void inspectPendingSend();
    }
  }, [messages, pending, busy]);
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
    if (page?.previous_offset == null || loadingRef.current) return;
    loadingRef.current = true;
    setBusy(true);
    const epoch = accessEpoch.current;
    try {
      const offset = page.previous_offset, limit = Math.min(50, page.offset - offset);
      const result = await bridge({ action: 'message_list', ...scope, offset, limit });
      if (!alive.current || epoch !== accessEpoch.current) return;
      setMessages(old => mergeMessages(old, result.items || []));
      const nextPage = { ...pageRef.current, offset, previous_offset: offset > 0 ? Math.max(0, offset - 50) : null, tail: true };
      pageRef.current = nextPage; setPage(nextPage);
      setFollow(false);
    } catch (e) {
      if (alive.current && epoch === accessEpoch.current) {
        setError(e.message);
        if ([400, 401, 403, 404].includes(e.status)) invalidateHistory();
      }
    }
    finally { loadingRef.current = false; if (alive.current) setBusy(false); }
  }
  function jumpLatest() {
    if (recentPage) {
      setMessages(old => mergeMessages(old.filter(row => row.optimistic), recentPage.items));
      pageRef.current = recentPage.page; setPage(recentPage.page); setRecentPage(null);
    }
    setFilter(''); setFollow(true);
    list.current?.scrollTo({ top: list.current.scrollHeight });
  }
  async function inspectPendingSend() {
    if (submitLock.current || busy || !pending) return;
    const original = pending;
    const epoch = accessEpoch.current;
    submitLock.current = true; setBusy(true); setError('');
    try {
      const inspected = await inspectMessageRequest(bridge, original, scope);
      if (!alive.current || epoch !== accessEpoch.current) return;
      if (confirmedMessageRequest(inspected, original, scope)) {
        setMessages(old => mergeMessages(old, [inspected.message]));
        setReceipt(inspected.message); setPending(null); setAttachments([]);
        setContent(old => old === original.content ? '' : old);
        void refreshRef.current?.();
      } else {
        setError(inspected.status === 'rejected'
          ? 'O registro original foi rejeitado. Nenhuma mensagem foi reenviada.'
          : 'O envio original ainda não foi confirmado. O rascunho permanece preservado; nenhuma mensagem foi reenviada.');
      }
    } catch (e) {
      if (alive.current) setError('Não foi possível consultar o envio original: ' + e.message);
    } finally { submitLock.current = false; if (alive.current) setBusy(false); }
  }
  async function send(reconcile = false, messageContent = content) {
    // Compatibility for an older caller is observation-only as well. A status
    // check can never pass the old prompt to message_send, even if it was lost.
    if (reconcile) return inspectPendingSend();
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
    const epoch = accessEpoch.current;
    try {
      const result = await bridge(request);
      if (!alive.current || epoch !== accessEpoch.current) return;
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
      if (epoch !== accessEpoch.current) return;
      // A matching history row triggers a read-only receipt inspection above;
      // only that confirmed receipt may release an uncertain restored draft.
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
  // A Home submit is handed off only after conversation creation and history are confirmed.
  // This calls the normal send path, which journals its exact request before transport.
  useEffect(() => {
    if (!matchesConversationStart(initialMessage, scope) || startedMessage.current === initialMessage.id
        || loading || !historyVerified || loadError || !readAccess.current || busy || attachmentBusy || pendingAttachment) return;
    startedMessage.current = initialMessage.id;
    onInitialMessageHandled?.(initialMessage.id);
    if (pending || messages.length) return; // Existing work is never automatically replayed.
    if (initialMessage.files?.length) {
      // The existing uploader stages the file; the user confirms upload and send there.
      window.dispatchEvent(new CustomEvent('sentra:attach-file', { detail: { files: initialMessage.files } }));
      return;
    }
    void send(false, initialMessage.content);
  }, [initialMessage, loading, historyVerified, loadError, busy, pending, messages.length, attachmentBusy, pendingAttachment]);
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
    const epoch = accessEpoch.current;
    try {
      let offset = 0, values = [];
      do {
        const result = await bridge({ action: 'message_list', ...scope, offset, limit: 200 });
        if (!alive.current || epoch !== accessEpoch.current) return;
        values = mergeMessages(values, result.items || []); offset = result.page?.next_offset ?? null;
      } while (offset !== null);
      const complete = [];
      for (const message of values) complete.push(await readComplete(message));
      if (alive.current && epoch === accessEpoch.current) downloadMarkdown(conversation, complete);
    } catch (e) { setError(e.message); } finally { if (alive.current) setExporting(false); }
  }
  async function readComplete(message) {
    const epoch = accessEpoch.current;
    const active = () => alive.current && readAccess.current && epoch === accessEpoch.current;
    if (!active()) throw Error('O acesso ao conteúdo da conversa foi interrompido.');
    const key = messageContentKey(message);
    if (fullCache.current.has(key)) return fullCache.current.get(key);
    const value = await completeMessage(message, bridgeRef.current, scope, active);
    if (!active()) throw Error('O acesso ao conteúdo da conversa foi interrompido.');
    if (message.content_truncated) {
      fullCache.current.set(key, value); setFullContents(old => ({ ...old, [key]: value.content }));
    }
    return value;
  }
  async function readOriginal(message, exportingMessage = false) {
    if (readingContent) return;
    const epoch = accessEpoch.current;
    setReadingContent(messageContentKey(message)); setError('');
    try { const value = await readComplete(message);
      if (alive.current && epoch === accessEpoch.current && exportingMessage) downloadMarkdown({ ...conversation, title: (conversation.title || 'Conversa') + ' — mensagem' }, [value]);
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
  const prepareInteractiveUiDraft = useCallback(function prepareInteractiveUiDraft(text) {
    // Model-generated UI cannot itself submit a turn or acquire tool grants.
    if (busy || pending || activeResponse || attachmentBusy || pendingAttachment || attachments.length || submitLock.current) {
      setError('Finalize o envio atual e os anexos antes de preparar respostas ao painel.');
      return false;
    }
    if (content.trim() && content !== text && !window.confirm('Substituir o rascunho atual pelas respostas do painel?')) return false;
    setContent(text);
    setError('');
    return true;
  }, [busy, pending, activeResponse, attachmentBusy, pendingAttachment, attachments.length, content]);
  const latest = messages[messages.length - 1];
  const latestStatus = String(latest?.status || '').toLowerCase();
  const waitingApproval = latestStatus === 'waiting_approval' || receipt?.status === 'waiting_approval';
  const inFlight = !loading && !loadError && !error && !waitingApproval &&
    (Boolean(submitLock.current) || (latest?.role === 'user' &&
      ['sending', 'queued', 'running', 'dispatched', 'pending'].includes(latestStatus)));
  const live = presentLive(livePreview);
  const reducedMotion = useReducedMotion();
  const beat = feedMotion(livePreview && typeof livePreview === 'object' ? livePreview : { status: 'idle' }, feedPrevious.current);
  useEffect(() => { feedPrevious.current = { activity: beat.activity, content: beat.content }; }, [beat.activity, beat.content]);
  const showLivePreview = previewStillVisible(livePreview, messages);
  // Coucou visual layer: modelos puros calculados a partir do que já está carregado.
  const presence = useMemo(() => chatPresenceModel({ dot, messages: presentedMessages, livePreview, connectionState, busy }),
    [dot, presentedMessages, livePreview, connectionState, busy]);
  const tickerItems = useMemo(() => deriveChatTicker({ messages: presentedMessages, livePreview, limit: 4 }),
    [presentedMessages, livePreview]);
  const heading = conversation.title || dot?.name || 'Conversa';
  const displayConnectionState = !readAccess.current && connectionState !== 'reauth_required' ? 'access_unavailable' : connectionState;
  const connectionLabel = {
    connecting: 'Conectando à conversa…',
    connected: 'Conectado',
    reconnecting: 'Reconectando. O texto recebido está preservado.',
    unavailable: 'Conexão contínua indisponível. Atualizando em modo de compatibilidade.',
    reauth_required: 'Sessão expirada. Reabra a janela para continuar.',
    access_unavailable: 'Acesso à conversa indisponível. Consulte novamente.',
  }[displayConnectionState] || 'Estado da conexão indisponível.';
  return <section className="shell-chat" aria-label={'Conversa com ' + (dot?.name || 'Dot')}>
    <header className="shell-chat-heading shell-chat-heading-refined"><div className="shell-persona"><DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id} name={dot?.name} status={dot?.status} execution={dot?.execution} size="nav" decorative />
      <div className="shell-persona-copy"><h2>{heading}</h2>{dot?.name && heading !== dot.name && <p title={dot?.model}>{dot.name}</p>}</div></div>
      {/* Task evidence stays visible; connection details have one dedicated status row. */}
      {!['idle', 'listening'].includes(presence.state) && <div className="shell-chat-task-state"><ChatPresence dot={dot} model={presence} showIdentity={false} /></div>}
      <div className="shell-chat-actions"><ConversationTools scope={scope} dot={dot} bridge={bridge} onResource={onResource}/><button onClick={onCanvas}><Layers size={15} />Canvas</button><ActionMenu label="Opções da conversa" items={[
        { label: 'Modelo e raciocínio', icon: <SlidersHorizontal size={15} />, action: () => onModel('') },
        { label: 'Definir objetivo', icon: <Flag size={15} />, action: () => setGoalDialog({ argument: '' }) },
        { label: 'Coordenar equipe', icon: <Users size={15} />, action: onCoordinate },
        { separator: true },
        { label: 'Pesquisar histórico', icon: <Search size={15} />, action: () => onTools('history') },
        { label: 'Exportar conversa', icon: <Download size={15} />, action: exportConversation, disabled: exporting || !messages.length },
      ]} /></div>
    </header>
    {/* Coucou visual layer: ticker derivado das mensagens já carregadas, sem polling próprio. */}
    <ChatTicker items={tickerItems} muted={connectionState !== 'connected'} />
    <div className="shell-chat-stream-status shell-chat-connection" role="status" data-state={displayConnectionState}>
      <span className="shell-chat-connection-indicator" aria-hidden="true" /><span>{connectionLabel}</span>
    </div>
    <div className="shell-visually-hidden" role="status" aria-live="polite" aria-atomic="true">
      {latest?.role === 'assistant' && !latest.optimistic && <span key={latest.message_id}>Resposta de {dot?.name || 'Dot'} disponível no histórico da conversa.</span>}
    </div>
    <label className="shell-chat-filter"><Search size={14} /><input value={filter} onChange={e => { setFollow(false); setFilter(e.target.value); }} placeholder="Buscar nesta conversa" aria-label="Buscar nas mensagens carregadas" /></label>
    {messages.length > 80 && <div className="shell-history-display"><button type="button" aria-pressed={renderAll} onClick={() => setRenderAll(value => !value)}>{renderAll ? 'Usar histórico otimizado' : 'Exibir todo o histórico carregado'}</button><small>{filteredMessages.length} {filteredMessages.length === 1 ? (filter ? 'mensagem encontrada' : 'mensagem carregada') : (filter ? 'mensagens encontradas' : 'mensagens carregadas')}</small></div>}
    <div className="shell-transcript" ref={list} role="log" aria-label="Histórico da conversa" aria-live="off" tabIndex={0}
      onScroll={e => setFollow(e.currentTarget.scrollHeight - e.currentTarget.scrollTop - e.currentTarget.clientHeight < 90)}>
      {page?.previous_offset != null && <button disabled={busy} onClick={loadMore}>Carregar mais mensagens</button>}
      {!historyVerified && cachedPreview?.items.length > 0 && <p className="shell-cache-note" role="status">Visualização anterior · atualizando histórico</p>}
      {loading && !cachedPreview?.items.length && <p className="shell-empty">Consultando mensagens…</p>}
      {!loading && historyVerified && !error && !loadError && !presentedMessages.length && !livePreview?.content && <div className="shell-chat-intro shell-chat-intro-compact"><DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id} name={dot?.name} status={dot?.status} execution={dot?.execution} size="small" decorative /><h3>Como posso ajudar?</h3><p>Conte a {dot?.name || 'este Dot'} o que você quer fazer, revisar ou entender neste projeto.</p></div>}
      {!loading && filter && !filteredMessages.length && <p className="shell-empty" role="status">Nenhuma mensagem carregada contém “{filter}”.</p>}
      <ShellMessageWindow items={filteredMessages} scrollRef={list} follow={follow && !filter} enabled={!renderAll && !filter}>{message =>
        message.cached_visual ? <article className="shell-message shell-cached-message" key={message.message_id} data-authoritative="false">
          <header><strong>{message.role === 'user' ? 'Você' : dot?.name || 'Dot'}</strong><small>Visualização anterior</small></header>
          <div className="shell-message-content shell-cached-message-text">{message.content}</div>
          {message.content_truncated && <small>Prévia do conteúdo armazenado</small>}
        </article> : <article className={'shell-message ' + (message.role === 'user' ? 'from-user' : '')} key={message.message_id}>
          <header>{message.role === 'assistant' && <DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id} name={dot?.name} status={dot?.status} execution={dot?.execution} size="message" decorative />}
            <strong>{message.role === 'user' ? 'Você' : message.role === 'assistant' ? dot?.name || 'Dot' : message.role}</strong>
            <time>{message.created_at ? new Date(message.created_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : ''}</time></header>
          {/* Coucou visual layer: pill apenas quando a mensagem traz status, operação ou recibo. */}
          {(() => { const pill = chatEventPillFor(message); return pill ?
            <div className="shell-chat-event-row"><ChatEventPill kind={pill.kind} label={pill.label} detail={pill.detail} /></div> : null; })()}
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
        </article>}</ShellMessageWindow>
      {showLivePreview && beat.content && <article className="shell-message shell-live-preview cadence-activity" aria-label="Resposta parcial, ainda não confirmada" data-authoritative="false" data-partial="true" data-closes-trio="false" data-resend="false" data-stop={beat.stop ? 'true' : 'false'} data-animate={!reducedMotion && beat.animate ? 'true' : 'false'}>
        <header><DotMascot mascot={dot?.mascot} identity={dot?.agent_id || dot?.dot_id}
          name={dot?.name} status={dot?.status} execution={dot?.execution} size="message" decorative />
          <strong>{dot?.name || 'Dot'}</strong><small>{beat.activity || live.activity || 'Prévia'} · prévia</small></header>
        <div className="shell-message-content"><ConversationMarkdown content={beat.content} /></div>
        {livePreview?.truncated && <small className="shell-preview-window">Trecho mais recente de uma resposta ainda não confirmada.</small>}
        <ShellStreamContent scope={scope} preview={livePreview} onAccessDenied={() => {
          invalidateHistory(); setLoadError('O acesso à prévia não está mais autorizado.');
        }} />
      </article>}
      {((inFlight && !(showLivePreview && beat.content)) || (showLivePreview && live && !beat.content)) && <div className="shell-thinking cadence-activity" role="status" aria-live="polite" data-authoritative="false" data-partial="true" data-closes-trio="false" data-stop={beat.stop ? 'true' : 'false'} data-animate={!reducedMotion && beat.animate && !beat.content ? 'true' : 'false'} data-resend="false" aria-label={(dot?.name || 'Dot') + ' está processando a mensagem'}>
        {/* Coucou visual layer: o wrapper autoritativo permanece; só o conteúdo visual muda. */}
        <ChatThinking dot={dot} label={busy ? 'Preparando envio' : beat.activity || live?.activity || 'Aguardando resposta'} />
      </div>}
      {waitingApproval && latest?.role === 'user' && <p className="shell-notice" role="status">Aguardando aprovação das permissões necessárias para continuar.</p>}
      {showLivePreview && !beat.content && livePreview?.content_error && <ShellStreamContent scope={scope} preview={livePreview} />}
    </div>
    {(!follow || recentPage) && <button className="shell-jump-latest" type="button" onClick={jumpLatest}>{recentPage ? 'Há novas mensagens · Ir para o mais recente' : 'Ir para o mais recente'}</button>}
    {/* Coucou visual layer: classe de presença apenas no wrapper; o form e o envio não mudam. */}
    <div className={'shell-composer-wrap shell-chat-composer-wrap is-' + (presence.state || 'idle')}>
      <ConversationPermissionCards scope={scope} dot={dot} bridge={bridge} onResource={onResource}/>
      {(error || loadError) && <div className="shell-error" role="alert">{error || loadError}</div>}
      {receipt && <OperationReceipt value={receipt} />}
      {fileTest && <div className="shell-file-test" role="status" aria-live="polite">
        <strong>{fileTest.status === 'succeeded' ? 'Teste real de arquivos concluído' :
          fileTest.status === 'running' ? 'Testando arquivos do projeto…' : 'Teste interrompido'}</strong>
        {fileTest.steps.map((step, index) => <div key={index}>{step.state === 'SUCCEEDED' ? '✓ ' : '• '}
          {step.label}: {step.state || 'não confirmado'} {step.operation_id && <small>· {step.operation_id}</small>}</div>)}
        {fileTest.error && <p className="shell-error">{fileTest.error}</p>}
      </div>}
      {pending && <div className="shell-notice" role="status">Envio preservado para consulta. <button disabled={busy} onClick={() => void inspectPendingSend()}>Consultar envio</button><small>Chave: {pending.request_key}</small></div>}
      <form className="shell-composer" onSubmit={e => { e.preventDefault(); void send(); }}>
        {content.trim().startsWith('/') && !content.trim().includes(' ') && <div className="shell-command-menu" role="group" aria-label="Comandos da conversa">
          {['model', 'goal', 'image'].filter(name => ('/' + name).startsWith(content.trim().toLowerCase())).map(name => <button key={name} type="button" onClick={() => { setContent(name === 'image' ? '/image ' : ''); if (name === 'model') onModel(''); else if (name === 'goal') setGoalDialog({ argument: '' }); }}>
            /{name} <span>{name === 'model' ? 'Escolher modelo deste Dot' : name === 'goal' ? 'Objetivo persistente desta conversa' : 'Criar imagem'}</span></button>)}</div>}
        <textarea value={content} onChange={e => setContent(e.target.value)} maxLength={100000} disabled={Boolean(pending)}
          placeholder={'Mensagem para ' + (dot?.name || 'o Dot') + '…'} aria-label="Mensagem"
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
        <div className="shell-composer-bottom">
          <ShellAccess inlineRequests bridge={bridge} scope={scope} onCustomize={() => setFileJobsOpen(true)} />
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
