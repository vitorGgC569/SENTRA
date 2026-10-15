import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, Bot, ChevronRight, FileText, Folder, Heart, Home, Layers, Menu, MessageCircle, Monitor, Moon, Plus, RefreshCw, Search, Settings2, Sun, Users, X } from 'lucide-react';
import { shellBridge, rememberNavigation, restoreNavigation, pendingShellMutations, acknowledgeVerifiedPending } from './shell-bridge';
import { ShellConversation } from './shell-conversation';
import { conversationCache } from './shell-conversation-cache';
import { HomeResumePanel } from './shell-home-resume';
import { ShellCoordinateDialog, ShellEntityDialog } from './shell-dialogs';
import { EventList, Status } from './shell-receipts';
import { ProjectDocuments } from './document-panel';
import { DotMascot } from './shell-mascot';
import { ShellMachines } from './shell-machines';
import { ShellCode } from './shell-code';
import { ShellInteractions } from './shell-interactions';
import { ShellApprovalNotifications } from './shell-approval-notifications';
import { ShellDotCanvas } from './shell-dot-canvas';
import { ShellDotComputer } from './shell-dot-computer';
import { ShellDotContextMenu } from './shell-dot-context-menu';
import { rowsInSpace, canvasNavigation, confirmedConversation, rememberWorkSurface, restoreWorkSurface } from './shell-navigation';
import { formatConversationDate } from './shell-dates.js';
import { closeUpdateMenuOnEscape } from './shell-update-menu.js';
import { FailureNotice } from './shell-failure.jsx';
import { NetworkSurface } from './shell-network.jsx';
import { OptionalSurfaces } from './shell-optional.jsx';
import { explainFailure } from './shell-failure';
import { classifyUpdate, versionDecision, BUNDLE_VERSION } from './shell-updates';
import { classifyLocalUpdateOffer, legacyFrontendOffer } from './shell-update-trigger.js';
import { beginCanvasMaintenance, endCanvasMaintenance, canvasMaintenanceActive } from './shell-maintenance.js';
import { createUpdateDeadline } from './shell-update-deadline.js';
import { loadVisualHome, saveVisualHome } from './shell-session-cache.js';
import { usePendingPresentation } from './shell-pending-presentation.js';

const empty = { spaces: [], dots: [], conversations: [], teams: [], documents: [], capabilities: [], activity: { items: [] } };
const primaryNav = [['home', 'Home', Home], ['conversations', 'Conversas', MessageCircle], ['dots', 'Dots', Bot], ['spaces', 'Spaces', Folder]];
const titles = { home: 'Home', spaces: 'Spaces', dots: 'Dots', conversations: 'Conversas', space: 'Space', chat: 'Conversa', documents: 'Documentos', canvas: 'Canvas', network: 'Rede' };
export function OpenDotsShell({ children, projectId, workspaces, models, onProject, onWorkspaceCreate, onCanvasActive, onTools, nativeControls }) {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('sentra_shell_theme') === 'light' ? 'light' : 'dark'; }
    catch { return 'dark'; }
  });
  useEffect(() => {
    document.documentElement.dataset.sentraTheme = theme;
    try { localStorage.setItem('sentra_shell_theme', theme); } catch { /* Keep the in-memory preference. */ }
  }, [theme]);
  const [nav, setNav] = useState(restoreNavigation), [home, setHome] = useState(empty), [detail, setDetail] = useState(null);
  const [collections, setCollections] = useState({}), [pages, setPages] = useState({}), [documents, setDocuments] = useState([]);
  const [dotPreferences, setDotPreferences] = useState([]);
  const [dotPreferenceBusy, setDotPreferenceBusy] = useState(false), [dotDrop, setDotDrop] = useState(null);
  const draggingDot = useRef(null), preferenceMutation = useRef(false);
  const [loading, setLoading] = useState(true), [homeSettled, setHomeSettled] = useState(false), [homeReadError, setHomeReadError] = useState('');
  const [warmVisual, setWarmVisual] = useState(false);
  const [error, setError] = useState(''), [documentError, setDocumentError] = useState('');
  const [search, setSearch] = useState(''), [homeQuery, setHomeQuery] = useState(''), [rail, setRail] = useState(() => !window.matchMedia('(max-width:700px)').matches), [context, setContext] = useState(false);
  const updateMenuRef = useRef(null);
  const [dialog, setDialog] = useState(null), [coordinate, setCoordinate] = useState(false), [events, setEvents] = useState([]);
  const [coordinationKind, setCoordinationKind] = useState('create_team');
  const [machinePanel, setMachinePanel] = useState(false);
  const [computerOpen, setComputerOpen] = useState(false);
  const [codePanel, setCodePanel] = useState(false);
  const [codePending, setCodePending] = useState(false);
  const [eventCursor, setEventCursor] = useState(0), [hasMoreEvents, setHasMoreEvents] = useState(false);
  const [creatingConversation, setCreatingConversation] = useState(false), [pendingConversation, setPendingConversation] = useState(null);
  const [conversationResolution, setConversationResolution] = useState(null);
  const [conversationLookupRevision, setConversationLookupRevision] = useState(0);
  const [conversationError, setConversationError] = useState('');
  const [updateOffer, setUpdateOffer] = useState(null);
  useEffect(() => {
    const failed = () => setUpdateNotice(
      'Não foi possível renovar a autenticação do Canvas. Feche e abra a janela do SENTRA para conectar ao broker atual. Nenhuma mensagem será reenviada.'
    );
    window.addEventListener('sentra:auth-recovery-failed', failed);
    return () => window.removeEventListener('sentra:auth-recovery-failed', failed);
  }, []);
  const updateInFlight = useRef(false);
  const updateUncertain = useRef(false);
  const updateDeadline = useRef(null);
  const [updateNeedsReview, setUpdateNeedsReview] = useState(false);
  const [updatingCode, setUpdatingCode] = useState(false), [updateNotice, setUpdateNotice] = useState(() => {
    try {
      const result = sessionStorage.getItem('sentra_update_outcome') || '';
      sessionStorage.removeItem('sentra_update_outcome');
      return result;
    } catch { return ''; }
  });
  // A read-only native trigger; never builds, restarts or resubmits automatically.
  // Recheck on focus and every 90s only while the user is using the app.
  useEffect(() => {
    let mounted = true;
    let busy = false;
    async function inspectUpdate() {
      if (busy || document.hidden || updatingCode) return;
      const native = window.pywebview?.api;
      if (typeof native?.check_update_notification !== 'function' &&
          typeof native?.check_code_updates !== 'function') return;
      busy = true;
      try {
        const latest = typeof native.check_update_notification === 'function'
          ? classifyLocalUpdateOffer(await native.check_update_notification())
          : legacyFrontendOffer(await native.check_code_updates());
        if (mounted) setUpdateOffer(latest);
      } catch {
        // Do not announce a new version on an unverifiable read.
        if (mounted) setUpdateOffer(null);
      } finally { busy = false; }
    }
    const onVisible = () => { if (!document.hidden) void inspectUpdate(); };
    const checkLater = window.setTimeout(() => void inspectUpdate(), 1500);
    const interval = window.setInterval(() => void inspectUpdate(), 90000);
    window.addEventListener('focus', onVisible);
    window.addEventListener('pywebviewready', onVisible);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      mounted = false;
      window.clearTimeout(checkLater);
      window.clearInterval(interval);
      window.removeEventListener('focus', onVisible);
      window.removeEventListener('pywebviewready', onVisible);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [updatingCode]);
  const updateAvailable = Boolean(updateOffer);
  // The icon is the sole update action. The explicit click authorizes a safe
  // attempt; the native owner still vetoes restart for active operations.
  function applyDetectedUpdate() {
    if (updatingCode || updateInFlight.current) return;
    if (updateOffer?.action === 'apply_code_updates') void refreshCode();
    else void refreshAll();
  }
  const conversationSubmission = useRef(null);
  const [dirty, setDirty] = useState(null);
  const [pendingMutations, setPendingMutations] = useState(() => pendingShellMutations(projectId)), [recovering, setRecovering] = useState(null);
  const pendingPresentation = usePendingPresentation(pendingMutations);
  const visiblePendingMutations = pendingPresentation.filter(value => value.project_id === projectId &&
    !(value.action === 'conversation_create' && creatingConversation && value.request_key === pendingConversation?.request_key));
  const generation = useRef(0), spaceGeneration = useRef(0), currentProject = useRef(projectId), restored = useRef(false);
  const navRef = useRef(nav); navRef.current = nav;
  const projectRef = useRef(onProject); projectRef.current = onProject;
  const currentSpaceId = nav.space_id || home.space?.space_id;
  const space = detail?.space_id === currentSpaceId ? detail : home.spaces.find(row => row.space_id === currentSpaceId) || (home.space?.space_id === currentSpaceId ? home.space : null);
  const dots = rowsInSpace(collections.dot_list || detail?.dots || home.dots, projectId, currentSpaceId);
  const conversations = rowsInSpace(collections.conversation_list || detail?.conversations || home.conversations, projectId, currentSpaceId);
  const spaces = mergeEntities(collections.space_list || home.spaces,
    [home.space, detail?.space_id === currentSpaceId ? detail : null].filter(Boolean), 'space_list')
    .sort((a, b) => Number(b.space_id === currentSpaceId) - Number(a.space_id === currentSpaceId)
      || Number(b.space_id === home.space?.space_id) - Number(a.space_id === home.space?.space_id));
  const teams = detail?.teams || home.teams;
  const conversationScopeKey = JSON.stringify([projectId, currentSpaceId, nav.conversation_id]);
  const matchingResolution = conversationResolution?.key === conversationScopeKey ? conversationResolution : null;
  const conversation = matchingResolution?.status === 'error' ? null : matchingResolution?.value ||
    conversations.find(row => row.conversation_id === nav.conversation_id) || rowsInSpace(home.conversations, projectId, currentSpaceId).find(row => row.conversation_id === nav.conversation_id);
  const dot = dots.find(row => row.dot_id === (conversation?.dot_id || nav.dot_id));
  const preferenceMap = new Map(dotPreferences.map(item => [item.dot_id, item]));
  const rootDots = dots.filter(row => !row.canvas_root_dot_id || row.canvas_root_dot_id === row.dot_id)
    .sort((a, b) => {
      const ap = preferenceMap.get(a.dot_id), bp = preferenceMap.get(b.dot_id);
      return Number(Boolean(ap?.archived_local)) - Number(Boolean(bp?.archived_local))
        || Number(Boolean(bp?.favorite)) - Number(Boolean(ap?.favorite))
        || (ap?.position ?? Number.MAX_SAFE_INTEGER) - (bp?.position ?? Number.MAX_SAFE_INTEGER)
        || (a.created_at || 0) - (b.created_at || 0) || a.dot_id.localeCompare(b.dot_id);
    });
  const orderedPreferenceItems = [...dotPreferences].sort((a, b) => Number(Boolean(a.archived_local)) - Number(Boolean(b.archived_local))
    || Number(Boolean(b.favorite)) - Number(Boolean(a.favorite))
    || a.position - b.position || a.dot_id.localeCompare(b.dot_id));
  const canvasDot = rootDots.find(row => row.dot_id === (dot?.canvas_root_dot_id || dot?.dot_id || nav.dot_id)) || (!nav.dot_id ? rootDots[0] : null);
  const projectRunning = home.run?.state === 'RUNNING';
  const bridge = useCallback((payload, options) => shellBridge({ project_id: currentProject.current, ...payload }, options), []);
  const preferenceGeneration = useRef(0);
  async function loadDotPreferences(project = currentProject.current, spaceId = currentSpaceId) {
    const ticket = ++preferenceGeneration.current;
    if (!project || !spaceId) { setDotPreferences([]); return; }
    try {
      const value = await shellBridge({ action: 'dot_preferences_get', project_id: project, space_id: spaceId });
      if (ticket === preferenceGeneration.current && currentProject.current === project) setDotPreferences(value.items || []);
    } catch (e) { if (ticket === preferenceGeneration.current && !e.maintenance && !canvasMaintenanceActive()) setError(e.message); }
  }
  async function mutateDotPreference(action, fields) {
    if (preferenceMutation.current) return;
    const project = currentProject.current, spaceId = currentSpaceId;
    preferenceMutation.current = true; setDotPreferenceBusy(true);
    try {
      const value = await bridge({ action, project_id: project, space_id: spaceId, ...fields });
      if (currentProject.current === project && (navRef.current.space_id || home.space?.space_id) === spaceId)
        setDotPreferences(value.items || []);
    } finally { preferenceMutation.current = false; setDotPreferenceBusy(false); }
  }
  useEffect(() => {
    const reveal = () => setContext(true);
    window.addEventListener('sentra:shell-context', reveal);
    return () => window.removeEventListener('sentra:shell-context', reveal);
  }, []);
  useEffect(() => {
    const update = () => setPendingMutations(pendingShellMutations(projectId));
    update(); window.addEventListener('sentra:shell-pending', update);
    return () => window.removeEventListener('sentra:shell-pending', update);
  }, [projectId]);
  async function reconcileMutation(payload) {
    if (recovering) return; setRecovering(payload.request_key);
    try {
      if (payload.action === 'conversation_create') {
        await inspectConversationCreation(payload);
        return;
      }
      // Other pending mutations need a dedicated read-only receipt API; a
      // status click cannot blindly redispatch an uncertain side effect.
      setError('A ação ainda exige reconciliação pelo recibo original. Nenhum comando foi reenviado.');
    } catch (e) { setError(e.message); } finally { setRecovering(null); }
  }
  async function reconcileWindowsObservation(payload) {
    if (recovering || updatingCode) return;
    setRecovering(payload.request_key);
    try {
      if (payload.action !== 'dot_vm_execute' ||
          payload.arguments?.action !== 'installation.advance' ||
          payload.arguments?.confirm_launch !== false) throw Error('Somente a consulta Windows sem lançamento pode ser reconciliada.');
      const siblings = pendingShellMutations(projectId);
      const previousStart = siblings.find(entry => entry.action === 'dot_vm_execute' &&
        entry.arguments?.action === 'start' && entry.dot_id === payload.dot_id &&
        entry.space_id === payload.space_id && entry.conversation_id === payload.conversation_id);
      const input = { project_id: payload.project_id, dot_id: payload.dot_id,
        space_id: payload.space_id, conversation_id: payload.conversation_id,
        original_request_key: payload.request_key,
        ...(previousStart ? { blocked_start_key: previousStart.request_key } : {}) };
      const preview = await bridge({ action:'dot_vm_reconcile_status', ...input });
      if (preview.status !== 'eligible' || preview.current_state !== 'UNCERTAIN' ||
          preview.vm_state !== 'poweroff' || preview.worker_returned !== true)
        throw Error('As evidências físicas não permitem reconciliar esta operação.');
      if (!window.confirm('A consulta Windows apresentou falha confirmada. Encerrar SOMENTE esta Operation como FAILED, preservar recibos e liberar seu lease? Não iniciará nem instalará o Windows.')) return;
      const result = await bridge({ action:'dot_vm_reconcile', ...input });
      if (result.status !== 'reconciled' || result.state !== 'FAILED' ||
          result.lease_released !== true ||
          result.original_request_key !== payload.request_key)
        throw Error('Não houve confirmação da reconciliação. O histórico foi preservado.');
      const cleared = [result.original_request_key];
      if (previousStart && preview.start_block_verified === true &&
          result.verified_blocked_start_request_key === previousStart.request_key)
        cleared.push(previousStart.request_key);
      acknowledgeVerifiedPending(cleared);
      setError('Consulta Windows reconciliada como FAILED, com recibo preservado. A VM não foi iniciada. Atualize o painel Computador antes de autorizar um novo Acordar.');
      await refresh();
    } catch (e) { setError(e.message); }
    finally { setRecovering(null); }
  }
  async function refreshData() {
    if (updatingCode) return;
    setUpdatingCode(true); setUpdateNotice('');
    try {
      await refresh();
      await refreshDocuments();
      setUpdateNotice(classifyUpdate('data').notice);
    } catch (e) {
      const copy = explainFailure(e);
      setUpdateNotice(copy.headline + ' ' + copy.safeNext);
    } finally { setUpdatingCode(false); }
  }
  function armUpdateDeadline() {
    updateUncertain.current = false;
    setUpdateNeedsReview(false);
    // Arm before awaiting any native RPC, not after an uncertain navigation.
    updateDeadline.current?.disarm();
    updateDeadline.current = createUpdateDeadline({ timeoutMs: 45000, onTimeout: () => {
      if (!updateInFlight.current) return;
      updateUncertain.current = true;
      endCanvasMaintenance();
      setUpdatingCode(false);
      setUpdateNeedsReview(true);
      setUpdateNotice('A atualização demorou além do limite de verificação. O serviço pode continuar trabalhando. Consulte o estado ou reabra o SENTRA antes de tentar novamente; nenhum comando foi repetido.');
      // Keep updateInFlight locked: retrying an uncertain update could restart
      // a broker while an earlier installation/build is still executing.
    }});
    updateDeadline.current.arm();
  }
  function finishUpdateAttempt() {
    updateDeadline.current?.disarm();
    if (updateUncertain.current) return;
    endCanvasMaintenance();
    updateInFlight.current = false;
    setUpdatingCode(false);
  }
  function waitForUpdateNavigation() {
    // The click-level deadline continues until the browser truly navigates.
    // Unloading this page cancels its timers; a stranded bridge cannot spin
    // forever because the deadline started BEFORE its first await.
  }
  async function refreshCode() {
    if (updatingCode || updateInFlight.current) return;
    updateInFlight.current = true;
    let navigationIssued = false;
    beginCanvasMaintenance();
    armUpdateDeadline();
    setUpdatingCode(true); setUpdateNotice('');
    const code = classifyUpdate('code');
    try {
      const native = window.pywebview?.api;
      if (!native?.check_code_updates || !native?.apply_code_updates) {
        setUpdateNotice(code.notice + ' A compilação local só está disponível na janela nativa. A versão instalada não mudou.');
        return;
      }
      if (pendingShellMutations(projectId).length || pendingConversation) {
        setUpdateNotice('Compilação local bloqueada: há solicitações ainda não confirmadas. Nada foi reenviado e a versão instalada não mudou.');
        return;
      }
      const status = await native.check_code_updates();
      if (!status.safe) {
        setUpdateNotice('Código local não atualizado: ' + (status.reason || 'há operações ou trabalhos ativos.') + ' A versão instalada não mudou.');
        return;
      }
      if (!status.frontend_stale) {
        setUpdateNotice('O código local da interface já está compilado. A versão instalada não foi alterada.');
        return;
      }
      // A click on the update icon is already the user's authorization.
      const built = await native.apply_code_updates();
      if (built.status !== 'built') {
        setUpdateNotice('Compilação não aplicada: ' + (built.reason || built.status) + ' A versão instalada não mudou.');
        return;
      }
      window.location.reload();
      navigationIssued = true;
      waitForUpdateNavigation();
    } catch (e) {
      const copy = explainFailure(e);
      setUpdateNotice(copy.headline + ' ' + copy.safeNext);
    } finally {
      if (!navigationIssued) finishUpdateAttempt();
    }
  }
  async function refreshAll() {
    if (updatingCode || updateInFlight.current) return;
    updateInFlight.current = true;
    let navigationIssued = false;
    let attemptedApply = false;
    beginCanvasMaintenance();
    armUpdateDeadline();
    setUpdatingCode(true); setUpdateNotice('');
    try {
      const native = window.pywebview?.api;
      if (!native?.check_full_updates || !native?.apply_full_updates) {
        setUpdateNotice('Esta janela usa um binário anterior à atualização coordenada. Abra o SENTRA a partir do código-fonte atualizado ou instale o próximo pacote assinado.');
        return;
      }
      // Historical UNCERTAIN requests must remain visible, but they do not
      // by themselves represent running effects. The authenticated backend
      // quiescence gate decides whether the broker may safely restart.
      if (pendingConversation) {
        setUpdateNotice('Atualização adiada: existe um envio de conversa em andamento.');
        return;
      }
      const preservedPending = pendingShellMutations(projectId).length;
      const status = await native.check_full_updates();
      if (!status.safe) { setUpdateNotice('Atualização bloqueada: ' + (status.reason || 'serviços ocupados.')); return; }
      // Avoid restarting an already-current authenticated broker merely to check.
      const offer = typeof native.check_update_notification === 'function'
        ? await native.check_update_notification() : null;
      if (offer?.available === false) {
        setUpdateOffer(null);
        setUpdateNotice('O código local já está atualizado. O Canvas não foi reiniciado.');
        return;
      }
      // Explicit icon click authorizes one locally gated attempt only.
      attemptedApply = true;
      const applied = await native.apply_full_updates();
      if (applied.status === 'unchanged') {
        setUpdateOffer(null);
        setUpdateNotice('O código local já está atualizado. O Canvas não foi reiniciado.');
        return;
      }
      if (applied.status !== 'local_code_updated') {
        setUpdateNotice('Atualização não concluída: ' + (applied.reason || applied.status) + '. Não foi declarada troca de versão.');
        return;
      }
      try { sessionStorage.setItem('sentra_update_outcome', applied.reason +
        (preservedPending ? ' ' + preservedPending + ' solicitação(ões) antiga(s) não confirmada(s) foram preservadas para consulta, sem reenvio.' : '')); }
      catch { /* Best effort: status lives in the Python owner. */ }
      // Broker restart rotates its bearer. A JS reload reuses the expired
      // credential: only the trusted native window may fetch the new owner.
      if (!native.reauthorize) {
        setUpdateNotice('Código aplicado, mas a janela não dispõe de renovação nativa da sessão. Reabra o SENTRA pelo launcher atualizado.');
        return;
      }
      const renewal = await native.reauthorize();
      if (renewal?.authenticated_owner !== true) {
        setUpdateNotice('O Canvas atualizou, mas a autenticação da nova janela não foi confirmada. Reabra o SENTRA; nenhuma operação foi reenviada.');
        return;
      }
      navigationIssued = true;
      waitForUpdateNavigation();
    } catch (e) {
      if (attemptedApply) {
        // The native RPC may be interrupted by the broker rotation. This
        // reconciles the current owner without rerunning apply or any prompt.
        try {
          const renewal = await window.pywebview?.api?.reauthorize?.();
          if (renewal?.authenticated_owner === true) {
            try { sessionStorage.setItem('sentra_update_outcome',
              'Conexão local recuperada. A conclusão da atualização não foi confirmada; consulte a versão antes de tentar novamente.'); } catch {}
            navigationIssued = true;
            waitForUpdateNavigation();
            return;
          }
        } catch { /* Preserve the original uncertainty. */ }
      }
      const copy = explainFailure(e);
      setUpdateNotice(copy.headline + ' ' + copy.safeNext);
    } finally {
      if (!navigationIssued) finishUpdateAttempt();
    }
  }
  function showInstalledVersion() {
    const decision = versionDecision({ installed: null, available: BUNDLE_VERSION, dataRefresh: false });
    const native = window.pywebview?.api;
    if (native?.check_full_updates) {
      void native.check_full_updates().then(status => setUpdateNotice(
        (status.native_executable_stale ? 'O executável instalado é anterior ao código Python atual. ' : 'O executável não está mais antigo que o código detectado. ') +
        'Trocar o executável requer pacote integral assinado; o botão de código e serviços não modifica essa versão.'
      )).catch(error => setUpdateNotice('Verificação da versão não confirmada: ' + error.message));
    } else {
      setUpdateNotice(classifyUpdate('version').notice + ' ' + decision.reason);
    }
  }
  async function refresh() {
    if (!currentProject.current) return;
    const project = currentProject.current, ticket = ++generation.current;
    try {
      const value = await shellBridge({ action: 'home', project_id: project });
      if (ticket !== generation.current || currentProject.current !== project) return;
      if (value.project_id !== project) throw Error('O shell retornou outro projeto.');
      setHome({ ...empty, ...value }); setError(''); setHomeReadError(''); setHomeSettled(true);
      setWarmVisual(false);
      saveVisualHome(project, value);
      setEvents(old => mergeEvents(old, value.activity?.items || []));
      setEventCursor(value.activity?.next_cursor ?? value.activity?.cursor ?? 0);
    } catch (e) {
      // The native owner is rotating the session. Present no terminal error
      // for an observation that was not retried or confirmed yet.
      if (ticket === generation.current && !e.reauthorizing && !e.maintenance && !canvasMaintenanceActive())
        setHomeReadError(e.message || 'A consulta não chegou.');
    }
    finally { if (ticket === generation.current) setLoading(false); }
  }
  async function loadCollection(action, offset = 0, append = false, explicitSpace = currentSpaceId) {
    const project = currentProject.current;
    if (!project || (action !== 'space_list' && !explicitSpace)) return;
    try {
      const value = await shellBridge({ action, project_id: project, ...(action !== 'space_list' ? { space_id: explicitSpace } : {}), offset, limit: 50 });
      if (currentProject.current !== project || (action !== 'space_list' && (navRef.current.space_id || home.space?.space_id) !== explicitSpace)) return;
      setCollections(old => ({ ...old, [action]: append ? mergeEntities(old[action] || [], value.items || [], action) : value.items || [] }));
      setPages(old => ({ ...old, [action]: value.page }));
    } catch (e) {
      if (currentProject.current === project && !e.reauthorizing && !e.maintenance && !canvasMaintenanceActive()) setError(e.message);
    }
  }
  const reportDocumentError = useCallback(value => setDocumentError(value?.message || String(value || '')), []);
  const refreshDocuments = useCallback(async (value) => {
    const project = currentProject.current, id = currentSpaceId;
    if (!project || !id) return;
    if (value?.items) { setDocuments(value.items); setDocumentError(''); return; }
    try {
      const result = await shellBridge({ action: 'document_list', project_id: project, space_id: id });
      if (currentProject.current !== project || (navRef.current.space_id || home.space?.space_id) !== id) return;
      setDocuments(result.items || []); setDocumentError('');
    } catch (e) { if (currentProject.current === project && !e.maintenance && !canvasMaintenanceActive()) setDocumentError(e.message); }
  }, [projectId, currentSpaceId]);
  useEffect(() => {
    if (!projectId) { setLoading(false); return; }
    if (!restored.current && workspaces.length) {
      restored.current = true;
      if (nav.project_id && nav.project_id !== projectId && workspaces.some(row => row.id === nav.project_id)) {
        void projectRef.current(nav.project_id); return;
      }
    }
    currentProject.current = projectId; generation.current++; spaceGeneration.current++;
    // Restore a tightly scoped visual-only snapshot immediately. No status,
    // permission or prior effect is authoritative until the live read completes.
    const cached = loadVisualHome(projectId);
    setHome(cached ? { ...empty, ...cached } : empty);
    setWarmVisual(Boolean(cached));
    setHomeSettled(Boolean(cached));
    setHomeReadError('');
    setDetail(null); setDocuments([]); setCollections({}); setPages({}); setEvents([]); setEventCursor(0);
    setLoading(true); setDocumentError(''); setPendingConversation(null); setConversationError('');
    conversationSubmission.current = null; setCreatingConversation(false);
    setNav(old => ({ ...old, project_id: projectId, ...(old.project_id && old.project_id !== projectId ? { view: 'home', space_id: null, conversation_id: null, dot_id: null } : {}) }));
    void refresh();
  }, [projectId]);
  useEffect(() => {
    void loadDotPreferences(projectId, currentSpaceId);
  }, [projectId, currentSpaceId]);
  useEffect(() => {
    const stored = { ...nav, project_id: projectId };
    rememberNavigation(stored);
    if (nav.view !== 'home') rememberWorkSurface(stored);
    onCanvasActive(nav.view === 'canvas');
  }, [nav, projectId]);
  useEffect(() => {
    const keydown = event => {
      if (event.target.closest('[role=dialog]')) return;
      if (closeUpdateMenuOnEscape(event, updateMenuRef.current)) return;
      if (navRef.current.view === 'canvas') return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); onTools('history'); }
      if (event.key === 'Escape') { setContext(false); if (window.matchMedia('(max-width:700px)').matches) setRail(false); }
    };
    window.addEventListener('keydown', keydown); return () => window.removeEventListener('keydown', keydown);
  }, [onTools]);
  useEffect(() => {
    // Home is the first authoritative read. Do not stampede the broker with
    // secondary queries before its owner/project scope is confirmed.
    if (!projectId || !currentSpaceId || !homeSettled || warmVisual || home.project_id !== projectId) return;
    const ticket = ++spaceGeneration.current;
    let disposed = false;
    setDetail(null); setDocuments([]); setCollections(old => ({ space_list: old.space_list }));
    shellBridge({ action: 'space_get', project_id: projectId, space_id: currentSpaceId }).then(value => {
      if (!disposed && ticket === spaceGeneration.current) { setDetail(value); setError(''); }
    }).catch(e => {
      if (!disposed && ticket === spaceGeneration.current && !e.reauthorizing && !e.maintenance && !canvasMaintenanceActive()) setError(e.message);
    });
    void loadCollection('dot_list', 0, false, currentSpaceId);
    void loadCollection('conversation_list', 0, false, currentSpaceId);
    void refreshDocuments();
    return () => { disposed = true; };
  }, [projectId, currentSpaceId, homeSettled, warmVisual, home.project_id]);
  useEffect(() => {
    if (nav.view === 'spaces') void loadCollection('space_list');
  }, [nav.view, projectId]);
  useEffect(() => {
    if (nav.view !== 'chat' || !nav.conversation_id || !projectId || !currentSpaceId || !homeSettled || warmVisual || home.project_id !== projectId) return;
    let disposed = false;
    const project = projectId, spaceId = currentSpaceId, conversationId = nav.conversation_id;
    const key = JSON.stringify([project, spaceId, conversationId]);
    setConversationResolution(old => ({ key, status: 'loading', value: old?.key === key ? old.value : null, error: '' }));
    // A selected conversation is an entity, independent of catalog pagination.
    // Refresh through the same scoped read after Home/events change; a removed
    // or revoked conversation must not remain alive solely in a stale page.
    shellBridge({ action: 'conversation_get', project_id: project, space_id: spaceId, conversation_id: conversationId }).then(value => {
      if (disposed || currentProject.current !== project) return;
      if (!value || value.project_id !== project || value.space_id !== spaceId || value.conversation_id !== conversationId || typeof value.dot_id !== 'string' || !value.dot_id) {
        const invalid = new Error('A consulta não confirmou a conversa neste Space.');
        invalid.invalidCanonical = true; throw invalid;
      }
      setConversationResolution({ key, status: 'ready', value, error: '' });
    }).catch(error => {
      if (!disposed && currentProject.current === project && !error.reauthorizing && !error.maintenance && !canvasMaintenanceActive()) {
        const unavailable = error.invalidCanonical || [400, 401, 403, 404].includes(error.status);
        if (unavailable) conversationCache.forget({ project_id: project, space_id: spaceId, conversation_id: conversationId });
        setConversationResolution(old => ({ key, status: unavailable ? 'error' : 'recovering',
          value: unavailable ? null : old?.key === key ? old.value : null,
          error: error.message || 'A conversa não está disponível neste Space.' }));
      }
    });
    return () => { disposed = true; };
  }, [projectId, currentSpaceId, nav.view, nav.conversation_id, homeSettled, warmVisual, home.project_id, home.conversations, conversationLookupRevision]);
  useEffect(() => {
    if (!projectId || !currentSpaceId || !homeSettled || warmVisual || home.project_id !== projectId) return;
    let disposed = false, fetching = false, sequence = eventCursor;
    const poll = async () => {
      if (disposed || fetching || document.hidden) return;
      fetching = true;
      try {
        const value = await shellBridge({ action: 'events', project_id: projectId, space_id: currentSpaceId, after_seq: sequence, limit: 50 });
        if (disposed) return;
        setEvents(old => mergeEvents(old, value.items || [])); setHasMoreEvents(Boolean(value.has_more));
        sequence = value.next_cursor ?? value.cursor ?? sequence; setEventCursor(sequence);
        if (value.items?.length) {
          void refresh(); void loadCollection('dot_list', 0, false, currentSpaceId); void loadCollection('conversation_list', 0, false, currentSpaceId);
        }
      } catch (e) { if (!disposed) setError(e.message); } finally { fetching = false; }
    };
    const timer = setInterval(poll, 4000); void poll();
    return () => { disposed = true; clearInterval(timer); };
  }, [projectId, currentSpaceId, homeSettled, warmVisual, home.project_id]);
  function navigate(next) {
    const changesDocumentScope = next.project_id && next.project_id !== projectId || next.space_id && next.space_id !== currentSpaceId;
    if (changesDocumentScope && codePending) { setCodePanel(true); setContext(true); setError('Consulte a operação Code Mode pendente antes de trocar de projeto ou Space.'); return; }
    if (changesDocumentScope && dirty?.dirty && !window.confirm('Há alterações de documento pendentes. O rascunho será preservado; deseja trocar de Space/projeto?')) return;
    setSearch(''); setNav(old => ({ ...old, ...next }));
  }
  async function selectProject(id) {
    if (codePending) { setCodePanel(true); setContext(true); setError('Consulte a operação Code Mode pendente antes de trocar de projeto.'); return; }
    if (dirty?.dirty && !window.confirm('Há alterações pendentes. Preservar o rascunho e trocar de projeto?')) return;
    try { await onProject(id); } catch (e) { setError(e.message); }
  }
  async function selectSpace(row, view = 'space') {
    if (row.project_id !== projectId) await selectProject(row.project_id);
    navigate({ view, project_id: row.project_id, space_id: row.space_id, conversation_id: null, dot_id: null });
  }
  async function inspectConversationCreation(payload = pendingConversation) {
    // Observation-only lookup of the exact durable request_key. A repeated
    // conversation_create POST is NOT a status check.
    if (!payload || conversationSubmission.current) return;
    setCreatingConversation(true);
    setConversationError('');
    try {
      const inspected = await shellBridge({
        action: 'conversation_request_status',
        project_id: payload.project_id, space_id: payload.space_id,
        dot_id: payload.dot_id, request_key: payload.request_key,
      });
      if (currentProject.current !== payload.project_id) return;
      if (inspected.status === 'confirmed' && inspected.confirmed === true &&
          confirmedConversation(inspected.conversation, payload)) {
        acknowledgeVerifiedPending([payload.request_key]);
        setPendingConversation(null);
        setCollections(old => ({ ...old,
          conversation_list: mergeEntities(old.conversation_list || conversations,
            [inspected.conversation], 'conversation_list') }));
        navigate({ view:'chat', space_id:inspected.conversation.space_id,
          dot_id:inspected.conversation.dot_id,
          conversation_id:inspected.conversation.conversation_id });
        void refresh();
      } else {
        setConversationError(inspected.status === 'rejected'
          ? 'A solicitação original foi rejeitada; nenhum novo pedido foi enviado.'
          : 'O recibo desta criação ainda não foi confirmado. Nenhuma nova criação foi solicitada.');
      }
    } catch(e) {
      if (currentProject.current === payload.project_id)
        setConversationError('Não foi possível consultar o recibo original: ' + e.message);
    } finally { if (currentProject.current === payload.project_id) setCreatingConversation(false); }
  }
  async function newConversation(selectedDot) {
    if (pendingConversation) { void inspectConversationCreation(); return; }
    if (conversationSubmission.current || !selectedDot) return;
    setCreatingConversation(true); setConversationError('');
    const payload = { action: 'conversation_create', project_id: selectedDot.project_id,
      space_id: selectedDot.space_id, dot_id: selectedDot.dot_id, request_key: crypto.randomUUID(), title: 'Conversa com ' + selectedDot.name };
    conversationSubmission.current = payload.request_key;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
    setPendingConversation(payload);
    try {
      const value = await bridge(payload, { signal: controller.signal });
      if (currentProject.current !== payload.project_id) return;
      if (!confirmedConversation(value, payload)) {
        setConversationError('A conversa ainda não foi confirmada. Consulte esta criação; nenhum novo pedido será enviado.');
        return;
      }
      setPendingConversation(null);
      setCollections(old => ({ ...old, conversation_list: mergeEntities(old.conversation_list || conversations, [value], 'conversation_list') }));
      navigate({ view: 'chat', space_id: value.space_id, conversation_id: value.conversation_id, dot_id: value.dot_id });
      void refresh();
    } catch (e) { if (currentProject.current === payload.project_id) { setConversationError(e.message); if (!e.uncertain) setPendingConversation(null); } }
    finally { clearTimeout(timeout); if (conversationSubmission.current === payload.request_key) { conversationSubmission.current = null; setCreatingConversation(false); } }
  }
  function openCanvas(row) { if (row) navigate(canvasNavigation(row)); else navigate({ view:'canvas', dot_id:null, conversation_id:null }); }
  function openConversation(row) { navigate({ view: 'chat', space_id: row.space_id, conversation_id: row.conversation_id, dot_id: row.dot_id }); }
  useEffect(() => {
    const reveal = event => {
      const selected = dots.find(row => row.agent_id === event.detail?.agent_id);
      if (!selected) { setError('Este agente ainda não está associado a um Dot autorizado. Atualize o Space.'); return; }
      const existing = conversations.find(row => row.dot_id === selected.dot_id);
      if (existing) openConversation(existing); else void newConversation(selected);
    };
    window.addEventListener('sentra:shell-agent', reveal);
    return () => window.removeEventListener('sentra:shell-agent', reveal);
  }, [dots, conversations, creatingConversation, pendingConversation]);
  function tools(kind) {
    if (['machines', 'registry', 'center', 'activity', 'terminal'].includes(kind)) {
      setContext(true); onTools(kind);
    } else onTools(kind);
  }
  function nextPage(action) {
    const page = pages[action];
    return page?.next_offset != null && <button className="shell-load-more" onClick={() => loadCollection(action, page.next_offset, true)}>Carregar mais · {page.returned} de {page.total}</button>;
  }
  const matches = row => (row.name || row.title || '').toLowerCase().includes(search.toLowerCase());
  function dotCard(row) {
    const isFavorite = preferenceMap.get(row.dot_id)?.favorite === true;
    const archivedLocal = preferenceMap.get(row.dot_id)?.archived_local === true;
    const group = orderedPreferenceItems.filter(item => item.favorite === isFavorite && item.archived_local === archivedLocal);
    const groupIndex = group.findIndex(item => item.dot_id === row.dot_id);
    const hasSameFavoriteAbove = groupIndex > 0;
    const hasSameFavoriteBelow = groupIndex >= 0 && groupIndex < group.length - 1;
    return <article className="shell-dot-card" key={row.dot_id}><DotMascot mascot={row.mascot} identity={row.agent_id || row.dot_id} name={row.name} status={row.status} execution={row.execution} size="card" decorative /><div><h3>{row.name}{archivedLocal && <small> · Arquivado localmente</small>}{isFavorite && <Heart className="shell-dot-favorite" size={13} aria-label="Favorito" fill="currentColor" />}</h3><p>{row.role === "specialist" ? "Especialista" : row.role}</p><details className="shell-dot-model"><summary>Modelo</summary><small>{row.model} {row.effort && '· ' + row.effort}</small></details></div>
      <Status value={row.status} /><footer><button disabled={archivedLocal || creatingConversation || Boolean(pendingConversation)} onClick={() => newConversation(row)}><MessageCircle size={14} /> Conversar</button>
        <button onClick={() => openCanvas(row)}>Canvas</button>
        <ShellDotContextMenu dot={row} favorite={isFavorite} archivedLocal={archivedLocal} canMoveUp={hasSameFavoriteAbove} canMoveDown={hasSameFavoriteBelow}
          onEdit={() => setDialog({ kind: 'dot', dot: row })}
          onFavorite={favorite => void mutateDotPreference('dot_preference_set', { dot_id: row.dot_id, favorite }).catch(e => setError(e.message))}
          onMove={direction => void mutateDotPreference('dot_order_move', { dot_id: row.dot_id, direction }).catch(e => setError(e.message))}
          onArchiveChange={() => loadDotPreferences(projectId, currentSpaceId)}
          bridge={bridge} projectId={projectId} spaceId={currentSpaceId} />
      </footer></article>;
  }
  function sidebarDot(row) {
    const favorite = preferenceMap.get(row.dot_id)?.favorite === true;
    const archivedLocal = preferenceMap.get(row.dot_id)?.archived_local === true;
    const group = rootDots.filter(item => (preferenceMap.get(item.dot_id)?.favorite === true) === favorite &&
      (preferenceMap.get(item.dot_id)?.archived_local === true) === archivedLocal);
    const index = group.findIndex(item => item.dot_id === row.dot_id);
    const active = (dot?.canvas_root_dot_id || dot?.dot_id || nav.dot_id) === row.dot_id;
    const drop = dotDrop?.dot_id === row.dot_id ? dotDrop.edge : '';
    return <ShellDotContextMenu key={row.dot_id} dot={row} favorite={favorite} archivedLocal={archivedLocal}
      canMoveUp={!dotPreferenceBusy && index > 0} canMoveDown={!dotPreferenceBusy && index < group.length - 1}
      onEdit={() => setDialog({ kind: 'dot', dot: row })}
      onCanvas={() => openCanvas(row)}
      onFavorite={value => void mutateDotPreference('dot_preference_set', { dot_id: row.dot_id, favorite: value }).catch(e => setError(e.message))}
      onMove={direction => void mutateDotPreference('dot_order_move', { dot_id: row.dot_id, direction }).catch(e => setError(e.message))}
      onArchiveChange={() => loadDotPreferences(projectId, currentSpaceId)}
      bridge={bridge} projectId={projectId} spaceId={currentSpaceId}
      className={'shell-dot-nav-row' + (active ? ' selected' : '') + (drop ? ' drop-' + drop : '')}
      draggable={!dotPreferenceBusy && !archivedLocal}
      onDragStart={event => {
        if (event.target.closest('.icon-button')) { event.preventDefault(); return; }
        draggingDot.current = { dot_id: row.dot_id, project_id: projectId, space_id: currentSpaceId };
        event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', row.dot_id);
      }}
      onDragOver={event => {
        const source = draggingDot.current;
        if (!source || dotPreferenceBusy || source.dot_id === row.dot_id || source.project_id !== projectId || source.space_id !== currentSpaceId) return;
        event.preventDefault(); event.dataTransfer.dropEffect = 'move';
        const bounds = event.currentTarget.getBoundingClientRect();
        setDotDrop({ dot_id: row.dot_id, edge: event.clientY < bounds.top + bounds.height / 2 ? 'before' : 'after' });
      }}
      onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget)) setDotDrop(null); }}
      onDragEnd={() => { draggingDot.current = null; setDotDrop(null); }}
      onDrop={event => {
        event.preventDefault();
        const source = draggingDot.current, bounds = event.currentTarget.getBoundingClientRect();
        draggingDot.current = null; setDotDrop(null);
        if (!source || source.project_id !== projectId || source.space_id !== currentSpaceId || source.dot_id === row.dot_id) return;
        void mutateDotPreference('dot_order_place', { dot_id: source.dot_id, target_dot_id: row.dot_id,
          edge: event.clientY < bounds.top + bounds.height / 2 ? 'before' : 'after' }).catch(e => setError(e.message));
      }}>
      <button className="shell-dot-nav-open" disabled={archivedLocal || creatingConversation || Boolean(pendingConversation)} aria-current={active ? 'page' : undefined}
        onClick={() => { const existing = conversations.find(item => item.dot_id === row.dot_id); if (existing) openConversation(existing); else void newConversation(row); }}>
        <DotMascot mascot={row.mascot} identity={row.agent_id || row.dot_id} name={row.name} status={row.status} execution={row.execution} size="nav" decorative />
        <span>{row.name}{archivedLocal && ' · arquivo local'}</span>{favorite && <Heart size={12} className="shell-dot-favorite" aria-label="Fixado nos favoritos" fill="currentColor" />}
      </button>
    </ShellDotContextMenu>;
  }
  function conversationRow(row) {
    return <button className="shell-conversation-row" key={row.conversation_id} onClick={() => openConversation(row)}><MessageCircle size={17} /><span><strong>{row.title}</strong><small>{dots.find(item => item.dot_id === row.dot_id)?.name || 'Dot'} · {formatConversationDate(row.updated_at)}</small></span><ChevronRight size={15} /></button>;
  }
  return <div className={'opendots-shell ' + (!rail ? 'shell-rail-closed' : '')} data-theme={theme} data-surface={nav.view}>
    <a className="shell-skip-link" href="#shell-main-focus">Ir ao conteúdo</a>
    <aside className="shell-rail" hidden={!rail}><button className="shell-wordmark" aria-label="SENTRA — Home" onClick={() => navigate({ view: 'home' })}><img className="shell-logo" src="/sentra-logo.png" alt="" width="32" height="32" draggable={false} /><span>SENTRA</span></button>
      <label className="shell-project-label">Projeto<select value={projectId || ''} onChange={e => selectProject(e.target.value)}><option value="" disabled>Selecione um projeto</option>{workspaces.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <nav className="shell-primary-nav" aria-label="Navegação principal">{primaryNav.map(([id, label, Icon]) => <button key={id} onClick={() => navigate({ view: id })} aria-current={nav.view === id ? 'page' : undefined}><Icon size={17} />{label}</button>)}</nav>
      {!!rootDots.length && <><div className="shell-rail-label">SEUS DOTS</div><nav className="shell-dots-nav" aria-label="Dots neste Space" aria-busy={dotPreferenceBusy}>{rootDots.map(sidebarDot)}</nav></>}
      <div className="shell-rail-label"><span>SEUS SPACES</span><button onClick={() => setDialog({ kind: 'space' })} disabled={!projectId} aria-label="Novo Space"><Plus size={15} /></button></div>
      <nav className="shell-space-nav" aria-label="Spaces">{spaces.map(row => <button key={row.space_id} className={row.space_id === currentSpaceId ? 'selected' : ''} onClick={() => selectSpace(row)}><Folder size={15} /><span>{row.name}</span></button>)}
        {!loading && !spaces.length && <p>Nenhum Space neste projeto.</p>}</nav>
      {space && <><div className="shell-rail-label">NESTE SPACE</div><nav className="shell-primary-nav" aria-label="Vistas do Space">
        <button aria-current={nav.view === 'documents' ? 'page' : undefined} onClick={() => navigate({ view: 'documents' })}><FileText size={17} />Documentos</button>
        <button aria-current={nav.view === 'canvas' ? 'page' : undefined} onClick={() => navigate({ view: 'canvas' })}><Layers size={17} />Canvas</button>
        <button aria-current={nav.view === 'network' ? 'page' : undefined} onClick={() => navigate({ view: 'network' })}><Users size={17} />Rede</button></nav></>}
      <div className="shell-rail-footer"><button onClick={() => tools('registry')}><Settings2 size={16} />Ambientes e modelos</button><button onClick={() => onTools('skills')}><Layers size={16} />Skills e ferramentas</button><button onClick={onWorkspaceCreate}><Plus size={16} />Novo projeto</button></div>
    </aside>
    <div className="shell-workspace"><header className="shell-topbar pywebview-drag-region"
      onMouseDown={e => { if (e.target.closest('button, input, select, textarea, a, summary, details')) e.stopPropagation(); }}
      onDoubleClick={e => { if (!e.target.closest('button, input, select, textarea, a, summary, details')) void window.pywebview?.api?.toggle_maximize(); }}>
      <button className="shell-icon" onClick={() => setRail(value => !value)} aria-label={rail ? 'Recolher navegação' : 'Mostrar navegação'} aria-expanded={rail}><Menu size={19} /></button>
      <div className="shell-breadcrumb pywebview-drag-region"><span>{space?.name || workspaces.find(row => row.id === projectId)?.name || 'Seu trabalho'}</span><ChevronRight size={12} /><strong>{titles[nav.view]}</strong></div>
      <div className="shell-topbar-actions">{home.run && <span className="shell-run-label"><Status value={home.run.state} /></span>}
        <button className="shell-icon" onClick={() => setTheme(value => value === 'dark' ? 'light' : 'dark')}
          aria-label={theme === 'dark' ? 'Ativar modo claro' : 'Ativar modo escuro'} title={theme === 'dark' ? 'Modo claro' : 'Modo escuro'}>
          {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button>
        {space && !projectRunning && <button onClick={() => { setCoordinationKind('resume'); setCoordinate(true); }}>Iniciar / retomar projeto</button>}
        <button type="button" className={'shell-icon shell-update-trigger' + (updateAvailable ? ' is-available' : '') + (updatingCode ? ' is-updating' : '')}
          id="shell-update-all" disabled={updatingCode || updateNeedsReview} aria-busy={updatingCode}
          title={updatingCode ? 'Atualizando o SENTRA…' : updateNeedsReview ? 'Atualização não confirmada: consulte o estado antes de repetir.' : updateAvailable ? updateOffer.explanation + ' Clique para atualizar.' : 'Verificar e atualizar código local'}
          aria-label={updatingCode ? 'Atualizando o SENTRA' : updateNeedsReview ? 'Atualização não confirmada. Consulte o estado.' : updateAvailable ? 'Atualização do código disponível. Atualizar agora.' : 'Verificar atualizações locais'}
          onClick={applyDetectedUpdate}><RefreshCw size={17} aria-hidden="true" /></button>
        <details className="shell-update-menu" ref={updateMenuRef}>
          <summary aria-label="Mais opções de atualização" title="Mais opções de atualização"><Settings2 size={14} /></summary>
          <div className="shell-update-panel">
            <p>O executável instalado exige pacote integral assinado.</p>
            <button type="button" id="shell-update-data" disabled={updatingCode} onClick={() => void refreshData()}>Atualizar dados</button>
            <button type="button" id="shell-update-code" disabled={updatingCode} onClick={() => void refreshCode()}>Atualizar código local</button>
            <button type="button" id="shell-update-version" onClick={showInstalledVersion}>Versão instalada</button>
          </div>
        </details>
        <button className="shell-icon" onClick={() => setContext(value => !value)} aria-label="Mostrar painel contextual" aria-expanded={context}><Activity size={17} /></button>{nativeControls}</div></header>
      <span className="shell-sr-only" role="status" aria-live="polite">
        {updatingCode ? 'Atualização do SENTRA em andamento. Aguarde a reinicialização.' : ''}
      </span>
      {updateNotice && <div className="shell-update-feedback" role="status">{updateNotice}
        <button type="button" onClick={() => setUpdateNotice('')} aria-label="Fechar aviso">Fechar</button></div>}
      {(conversationError || error) && <FailureNotice message={conversationError || error} uncertain={Boolean(pendingConversation) || /incert|uncertain/i.test(conversationError || error)} onConsult={() => { if (pendingConversation) void inspectConversationCreation(); else void refresh(); }} onDismiss={() => { setError(''); setConversationError(''); }} />}
      {!!visiblePendingMutations.length && <details className="shell-pending-operations"><summary>{visiblePendingMutations.length} solicitação(ões) aguardando confirmação</summary>
        {visiblePendingMutations.map(payload => <div key={payload.request_key}><span>{payload.action} · {payload.request_key}</span><button disabled={Boolean(recovering)} onClick={() => reconcileMutation(payload)}>Consultar mesma intenção</button>{payload.action === 'dot_vm_execute' && payload.arguments?.action === 'installation.advance' && payload.arguments?.confirm_launch === false && <button type="button" disabled={Boolean(recovering)} onClick={() => void reconcileWindowsObservation(payload)}>Reconciliar consulta Windows</button>}</div>)}</details>}
      {pendingConversation && <div className="shell-notice" role="status">{creatingConversation ? 'Abrindo conversa…' : 'Criação de conversa ainda não confirmada.'} <button disabled={creatingConversation} onClick={() => void inspectConversationCreation()}>Consultar criação</button></div>}
      <div className="shell-body">
        {warmVisual && <div className="shell-warm-indicator" role="status">
          {homeReadError ? 'Última visualização disponível, mas o Canvas ainda não confirmou os dados.' : 'Restaurando a última visualização; sincronizando…'}
          {homeReadError && <button type="button" onClick={() => { setHomeReadError(''); void refresh(); }}>Tentar novamente</button>}
        </div>}
        <div className="shell-main" id="shell-main-focus" tabIndex={-1} inert={warmVisual}>
        <div className="shell-canvas-host" hidden={nav.view !== 'canvas'}>{nav.view === 'canvas' && canvasDot && <ShellDotCanvas key={canvasDot.dot_id} dot={canvasDot} roots={rootDots} bridge={bridge}
          onSelect={id => openCanvas(rootDots.find(row => row.dot_id === id))}
          onCreate={root => setDialog({ kind: 'dot', canvasRoot: root.dot_id })}
          onComputer={member => { setComputerOpen(true); const existing = conversations.find(row => row.dot_id === member.dot_id); if (existing) openConversation(existing); else void newConversation(member); }}
          onConversation={member => { const existing = conversations.find(row => row.dot_id === member.dot_id); if (existing) openConversation(existing); else void newConversation(member); }} />}
          {nav.view === 'canvas' && !canvasDot && nav.dot_id && <p className="shell-empty" role="status">Carregando o Canvas deste Dot…</p>}
          <div hidden={Boolean(canvasDot) || Boolean(nav.dot_id)}>{children}</div></div>
        <div className="shell-documents-host" hidden={nav.view !== 'documents'}>{space && <ProjectDocuments bridge={bridge} spaceId={space.space_id} projectId={projectId} documents={documents} onRefresh={refreshDocuments} onError={reportDocumentError} onDirtyChange={setDirty} />}
          {documentError && <div role="alert" className="shell-error">{documentError}<button onClick={refreshDocuments}>Consultar documentos</button></div>}</div>
        <div className="shell-chat-host dot-computer-chat-host" hidden={nav.view !== 'chat'}>{conversation && <><div className="dot-computer-chat-toolbar"><button onClick={() => setComputerOpen(value => !value)} aria-expanded={computerOpen}><Monitor size={14} />{computerOpen ? 'Ocultar computador' : 'Computador'}</button></div><div className={'dot-computer-workspace' + (computerOpen && dot ? ' is-open' : '')}><div className="dot-computer-chat"><ShellConversation key={JSON.stringify([conversation.project_id, conversation.space_id, conversation.conversation_id])} conversation={conversation} dot={dot} bridge={bridge} onCoordinate={() => setCoordinate(true)}
          onModel={argument => setDialog({ kind: 'model', dot, initialModel: models.find(item => (typeof item === 'string' ? item : item.id) === argument || (typeof item === 'string' ? item : item.id)?.endsWith('/' + argument)) })}
          onCanvas={() => openCanvas(dot)}
          onTools={tools} onChanged={refresh} voice={{ ...home.voice, attachments: home.attachments }} /></div>{computerOpen && dot && <ShellDotComputer key={dot.dot_id} dot={dot} conversation={conversation} bridge={bridge} visible={nav.view === 'chat'} onClose={() => setComputerOpen(false)} onConfigure={() => tools('machines')} onCanvas={() => openCanvas(dot)} />}</div></>}
          {nav.view === 'chat' && !conversation && (['error', 'recovering'].includes(matchingResolution?.status) ? <div className="shell-empty" role="alert"><h2>Conversa indisponível neste Space</h2><p>{matchingResolution.error}</p><button type="button" onClick={() => setConversationLookupRevision(value => value + 1)}>Consultar conversa novamente</button><button onClick={() => navigate({ view: 'conversations' })}>Ver conversas</button></div> : <p className="shell-empty" role="status">Abrindo a conversa…</p>)}</div>
        {!['canvas', 'documents', 'chat'].includes(nav.view) && <main className="shell-content" id="shell-main-content">
          {!projectId ? <div className="shell-welcome"><h1>Um lugar para dar continuidade.</h1><p>Crie ou adicione um projeto para organizar Dots, conversas e documentos.</p><button className="shell-primary" onClick={onWorkspaceCreate}>Criar projeto</button></div> : !homeSettled ? (homeReadError && !loading ? <div className="shell-error" role="alert" data-mutation="false" data-resend="false"><strong>{explainFailure({ read: true, message: homeReadError }).headline}</strong><p>{explainFailure({ read: true, message: homeReadError }).safeNext}</p><button type="button" onClick={() => { setLoading(true); setHomeReadError(''); void refresh(); }}>Consultar de novo</button></div> : <p role="status" aria-busy="true" className="shell-empty">Consultando seu trabalho…</p>) : <>
          {nav.view === 'home' && <><div className="shell-page-heading shell-home-hero"><div><span className="shell-eyebrow">SEU ESPAÇO DE TRABALHO</span><h1>O que vamos fazer hoje?</h1><p>Converse com seus Dots. Continue de onde parou.</p></div><DotMascot mascot={rootDots[0]?.mascot} identity={rootDots[0]?.agent_id || rootDots[0]?.dot_id} name={rootDots[0]?.name || 'Dot'} status={rootDots[0]?.status} execution={rootDots[0]?.execution} size="hero" decorative /></div>
            <HomeResumePanel home={home} surface={restoreWorkSurface()} onNavigate={navigate} onConversation={openConversation} />
            <section className="shell-home-start"><MessageCircle size={24} /><div><h2>Uma ideia pode virar trabalho.</h2><p>Escolha um Dot e comece uma conversa.</p></div><button className="shell-primary" onClick={() => navigate({ view: 'dots' })}>Escolher Dot <ChevronRight size={15} /></button></section>
            <div className="shell-section-heading"><h2>Seus Dots</h2><button onClick={() => setDialog({ kind: 'dot' })} disabled={!space || !projectRunning} title={!projectRunning ? 'Inicie o projeto para admitir um Dot.' : undefined}><Plus size={14} />Novo Dot</button></div>
            <div className="shell-dot-grid">{rootDots.slice(0, 6).map(dotCard)}</div>{!home.dots.length && <p className="shell-empty">Crie um Dot especializado no Space deste projeto.</p>}
            <div className="shell-section-heading"><h2>Conversas recentes</h2><button onClick={() => navigate({ view: 'conversations' })}>Ver todas</button></div><div className="shell-conversation-list">{home.conversations.slice(0, 8).map(conversationRow)}</div>
            <div className="shell-section-heading"><h2>Spaces</h2><button onClick={() => setDialog({ kind: 'space' })}><Plus size={14} />Novo Space</button></div><div className="shell-space-grid">{home.spaces.map(row => <button key={row.space_id} className="shell-space-card" onClick={() => selectSpace(row)}><Folder size={22} /><h3>{row.name}</h3><p>{row.description || 'Conversas, contexto e documentos neste projeto.'}</p><span>Abrir Space <ChevronRight size={14} /></span></button>)}</div></>}
          {['dots', 'conversations', 'spaces'].includes(nav.view) && <><div className="shell-page-heading"><span className="shell-eyebrow">{space?.name || 'SEU PROJETO'}</span><h1>{titles[nav.view]}</h1><p>{nav.view === 'dots' ? 'Especialistas com contexto e continuidade.' : nav.view === 'spaces' ? 'Projetos organizados para seguir em frente.' : 'Decisões e trabalho na mesma conversa.'}</p></div>
            <div className="shell-list-toolbar"><label className="shell-search"><Search size={15} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder={'Buscar ' + titles[nav.view].toLowerCase()} aria-label="Filtrar lista" /></label>
              {nav.view !== 'conversations' ? <button onClick={() => setDialog({ kind: nav.view === 'spaces' ? 'space' : 'dot' })} disabled={nav.view === 'dots' && (!space || !projectRunning)} title={nav.view === 'dots' && !projectRunning ? 'Inicie o projeto para admitir um Dot.' : undefined}><Plus size={15} />{nav.view === 'spaces' ? 'Novo Space' : 'Novo Dot'}</button> : <button onClick={() => onTools('history')}><Search size={15} />Histórico completo</button>}</div>
            {nav.view === 'dots' && <><div className="shell-dot-grid">{rootDots.filter(matches).map(dotCard)}</div>{!rootDots.length && <p className="shell-empty">Nenhum Dot neste Space.</p>}{nextPage('dot_list')}</>}
            {nav.view === 'conversations' && <><div className="shell-conversation-list">{conversations.filter(matches).map(conversationRow)}</div>{!conversations.length && <p className="shell-empty">Escolha um Dot para iniciar uma conversa.</p>}{nextPage('conversation_list')}</>}
            {nav.view === 'spaces' && <><div className="shell-space-grid">{spaces.filter(matches).map(row => <button key={row.space_id} className="shell-space-card" onClick={() => selectSpace(row)}><Folder size={22} /><h3>{row.name}</h3><p>{row.description}</p><span>Abrir <ChevronRight size={14} /></span></button>)}</div>{nextPage('space_list')}</>}
          </>}
          {nav.view === 'space' && space && <><div className="shell-page-heading"><span className="shell-eyebrow">SPACE</span><h1>{space.name}</h1><p>{space.description || 'Seu contexto, conversas e documentos.'}</p></div>
            <div className="shell-space-shortcuts"><button onClick={() => navigate({ view: 'documents' })}><FileText size={18} />Documentos</button><button onClick={() => navigate({ view: 'canvas' })}><Layers size={18} />Abrir Canvas</button><button onClick={() => navigate({ view: 'network' })}><Users size={18} />Rede de Dots</button><button onClick={() => setCoordinate(true)}><Users size={18} />Coordenar equipe</button><button onClick={() => onTools('files')}><Folder size={18} />Arquivos do projeto</button></div>
            <div className="shell-section-heading"><h2>Dots neste Space</h2><button onClick={() => setDialog({ kind: 'dot' })} disabled={!projectRunning} title={!projectRunning ? 'Inicie o projeto para admitir um Dot.' : undefined}><Plus size={14} />Novo Dot</button></div><div className="shell-dot-grid">{rootDots.map(dotCard)}</div>{nextPage('dot_list')}
            <div className="shell-section-heading"><h2>Conversas</h2></div><div className="shell-conversation-list">{conversations.map(conversationRow)}</div>{nextPage('conversation_list')}
            <div className="shell-section-heading"><h2>Equipes</h2></div>{teams.map(team => <article className="shell-team" key={team.team_id || team.id}><Users size={17} /><strong>{team.name}</strong><Status value={team.status || team.state} /></article>)}
            <OptionalSurfaces document={home.optional_surfaces} />
          </>}
          {nav.view === 'network' && <NetworkSurface document={home.network} bridge={bridge} spaceId={space?.space_id} dots={rootDots} />}
          </>}
        </main>}
      </div>
      <aside className="shell-context" hidden={!context} aria-label="Painel contextual"><header><h2>Seu trabalho</h2><button className="shell-icon" aria-label="Fechar painel contextual" onClick={() => setContext(false)}><X size={17} /></button></header>
        <button className="shell-desktop-toggle" disabled={!space} onClick={() => setCodePanel(value => !value)} aria-expanded={codePanel}>Code Mode · propostas e resultados</button>
        <div hidden={!codePanel}>{space && <ShellCode key={projectId + ':' + space.space_id} bridge={bridge} scope={{ project_id: projectId, space_id: space.space_id,
          ...(conversation ? { conversation_id: conversation.conversation_id } : {}) }} onPendingChange={setCodePending} onConfigure={() => tools('machines')} />}</div>
        <button className="shell-desktop-toggle" disabled={!space} onClick={() => setMachinePanel(value => !value)} aria-expanded={machinePanel}>Desktop remoto e posse de entrada</button>
        {machinePanel && space && <ShellMachines key={projectId + ':' + space.space_id} bridge={bridge} scope={{ project_id: projectId, space_id: space.space_id }} visible={context}
          onConfigure={() => tools('machines')} />}
        <div className="shell-context-tools"><button onClick={() => navigate({ view: 'documents' })}><FileText size={15} />Documentos</button><button onClick={() => onTools('files')}><Folder size={15} />Arquivos e diff</button><button onClick={() => tools('terminal')}><Layers size={15} />Terminal</button><button onClick={() => tools('machines')}><Bot size={15} />Navegador e máquinas</button><button onClick={() => onTools('web')}><Activity size={15} />Entrega e retomada</button><button onClick={() => onTools('access')}>Permissões</button><button onClick={() => onTools('plugins')}>Plugins MCP</button></div>
        <div id="shell-inspector-slot" />
        <ShellInteractions key={projectId} bridge={bridge} projectId={projectId} visible={context} />
        <div className="shell-context-summary">{home.run && <Status value={home.run.state} />}<small>{home.capabilities.length} capacidades concedidas</small></div>
        <h3>Atividade e recibos</h3><EventList items={events.filter(event => !event.space_id || event.space_id === currentSpaceId)} />
        {!events.length && <p className="shell-empty">Nenhuma atividade registrada.</p>}{hasMoreEvents && <p role="status">Recuperando próximos eventos…</p>}
      </aside></div>
    </div>
    {dialog && <ShellEntityDialog key={(dialog.dot?.dot_id || dialog.kind) + ':' + currentSpaceId} kind={dialog.kind} dot={dialog.dot} canvasRoot={dialog.canvasRoot} initialModel={typeof dialog.initialModel === 'string' ? dialog.initialModel : dialog.initialModel?.id} space={space} projectId={projectId} models={models} bridge={bridge}
      onClose={() => setDialog(null)} onCreated={async value => { if (dialog.canvasRoot && value.dot_id) await bridge({ action: 'dot_canvas_terminal', space_id: space.space_id, dot_id: dialog.canvasRoot, member_dot_id: value.dot_id, request_key: crypto.randomUUID() }); await refresh(); if (dialog.kind === 'space') await selectSpace(value); else { await loadCollection('dot_list'); } }} />}
    <ShellApprovalNotifications bridge={bridge} projectId={projectId} shellError={conversationError || error}
      onOpenConversation={(conversationId, spaceId) => navigate({ view:'chat', space_id:spaceId, conversation_id:conversationId })} />
    {coordinate && space && <ShellCoordinateDialog initialKind={coordinationKind} space={space} conversation={conversation} dots={dots} teams={teams} bridge={bridge} onClose={() => { setCoordinate(false); setCoordinationKind('create_team'); }} onChanged={async () => { await refresh(); await loadCollection('dot_list'); }} />}
  </div>;
}
function mergeEntities(previous, incoming, action) {
  const key = { space_list: 'space_id', dot_list: 'dot_id', conversation_list: 'conversation_id' }[action];
  const map = new Map(previous.map(row => [row[key], row]));
  for (const row of incoming) map.set(row[key], row);
  return [...map.values()];
}
function mergeEvents(previous, incoming) {
  const values = new Map(previous.map(event => [event.event_id, event]));
  for (const event of incoming) values.set(event.event_id, event);
  return [...values.values()].sort((a, b) => b.seq - a.seq).slice(0, 500);
}
