import { api, ApiError } from './api.js';
import { canvasMaintenanceActive } from './shell-maintenance.js';
import { confirmedConversation } from './shell-navigation.js';

const projectReviewActions = new Set(['project_file_list', 'project_file_preview', 'project_file_diff', 'project_file_pdf_text',
  'project_file_pdf_visual', 'project_watch_start', 'project_watch_poll', 'project_watch_close']);
const reads = new Set(['home', 'space_list', 'space_get', 'dot_list', 'conversation_list', 'conversation_get', 'conversation_request_status', 'message_request_status', 'message_list', 'message_content', 'events',
  'dot_preferences_get', 'dot_remove_preflight', 'dot_retire_authority_status', 'dot_retire_authority_reconcile', 'dot_vm_retire_preflight',
  'access_status', 'goal_status', 'dot_canvas_get', 'dot_computer_get', 'dot_computer_read',
  'dot_vm_status', 'dot_vm_frame', 'dot_vm_images', 'dot_vm_reconcile_status',
  'network_home', 'network_status',
  'capabilities_home', 'capabilities_catalog', 'capabilities_connectors', 'capabilities_models', 'capabilities_usage',
  'document_list', 'document_get', 'document_history', 'document_diff', 'document_export', 'voice_status', 'attachment_upload_status',
  'machine_list', 'input_status', 'machine_observe', 'code_status', 'code_discovery', 'turn_permission_list', 'interaction_list', 'coordinator_approval_list',
  'skill_list', 'skill_review', 'skill_versions', 'skill_latest', 'skill_disclose', 'skill_activations', 'skill_learning_review',
  'plugin_bundle_list', 'plugin_bundle_inspect', 'plugin_supervision', 'plugin_transport_status', 'plugin_connection_proof', ...projectReviewActions]);
const actions = new Set([...reads, 'space_create', 'dot_create', 'dot_update', 'conversation_create', 'message_send', 'coordinate',
  'dot_preference_set', 'dot_order_move', 'dot_order_place', 'dot_archive_local', 'dot_restore_local',
  'dot_pause_family', 'dot_resume_family', 'dot_delete_request', 'dot_retire_authority_close',
  'dot_computer_action',
  'dot_vm_configure', 'dot_vm_execute', 'dot_vm_input', 'dot_vm_handoff', 'dot_vm_reconcile',
  'access_set', 'access_approve', 'access_reject', 'dot_canvas_terminal', 'dot_canvas_terminal_close', 'dot_canvas_handoff', 'dot_canvas_task_submit', 'dot_canvas_task_cancel', 'goal_set', 'goal_stop', 'goal_complete', 'goal_loop_start', 'goal_loop_stop', 'goal_loop_step', 'dot_canvas_move', 'dot_canvas_link', 'dot_canvas_unlink',
  'document_create', 'document_save', 'document_restore', 'document_delete', 'document_session', 'document_session_close',
  'voice_start', 'voice_signal', 'voice_stop', 'voice_revoke', 'attachment_register',
  'attachment_upload_begin', 'attachment_upload_chunk', 'attachment_upload_complete', 'attachment_upload_abort',
  'input_handoff', 'remote_viewer_open', 'remote_viewer_close', 'machine_execute', 'code_propose', 'code_execute', 'code_cancel', 'turn_permission_grant', 'turn_permission_revoke', 'interaction_reply', 'coordinator_approval_reply',
  'skill_import', 'skill_git', 'skill_github', 'skill_revoke', 'skill_activate', 'skill_deactivate', 'skill_upgrade', 'skill_rollback', 'skill_replace', 'skill_learning_stage',
  'plugin_bundle_stage', 'plugin_bundle_register', 'plugin_bundle_disable', 'plugin_bundle_update', 'plugin_bundle_rollback', 'plugin_bundle_uninstall', 'plugin_supervision_sweep',
  'network_enable', 'network_disable', 'network_invite', 'network_revoke', 'network_converse', 'network_delegate', 'network_review',
  'capability_enable', 'capability_disable', 'capability_invoke']);
const recoverable = new Set(['space_create', 'dot_create', 'dot_update', 'conversation_create', 'coordinate',
  'dot_preference_set', 'dot_order_move', 'dot_order_place', 'dot_archive_local', 'dot_restore_local',
  'dot_pause_family', 'dot_resume_family', 'dot_delete_request', 'dot_retire_authority_close',
  'dot_computer_action',
  'dot_vm_configure', 'dot_vm_execute', 'dot_vm_input', 'dot_vm_handoff', 'dot_vm_reconcile',
  'access_set', 'access_approve', 'access_reject', 'dot_canvas_terminal', 'dot_canvas_terminal_close', 'dot_canvas_handoff', 'dot_canvas_task_submit', 'dot_canvas_task_cancel', 'goal_set', 'goal_stop', 'goal_complete', 'goal_loop_start', 'goal_loop_stop', 'goal_loop_step', 'dot_canvas_move', 'dot_canvas_link', 'dot_canvas_unlink',
  'input_handoff', 'remote_viewer_open', 'remote_viewer_close', 'machine_execute', 'code_execute', 'code_cancel', 'turn_permission_grant', 'turn_permission_revoke', 'coordinator_approval_reply',
  'skill_import', 'skill_git', 'skill_github', 'skill_revoke', 'skill_activate', 'skill_deactivate', 'skill_upgrade', 'skill_rollback', 'skill_replace', 'skill_learning_stage',
  'plugin_bundle_stage', 'plugin_bundle_register', 'plugin_bundle_disable', 'plugin_bundle_update', 'plugin_bundle_rollback', 'plugin_bundle_uninstall', 'plugin_supervision_sweep',
  'network_enable', 'network_disable', 'network_invite', 'network_revoke', 'network_converse', 'network_delegate', 'network_review',
  'capability_enable', 'capability_disable', 'capability_invoke']);
const pendingStorage = 'sentra_shell_mutations';
export function pendingShellMutations(projectId) {
  try {
    const values = JSON.parse(sessionStorage.getItem(pendingStorage)) || {};
    return Object.values(values).filter(value => value.project_id === projectId);
  } catch { return []; }
}
function retainMutation(payload, retained) {
  if (!recoverable.has(payload.action)) return;
  if (payload.action === 'machine_execute' && payload.arguments && 'source' in payload.arguments) return;
  try {
    const values = JSON.parse(sessionStorage.getItem(pendingStorage)) || {};
    if (retained) values[payload.request_key] = payload; else delete values[payload.request_key];
    sessionStorage.setItem(pendingStorage, JSON.stringify(values));
  } catch { /* The current window still holds the request. */ }
  window.dispatchEvent(new CustomEvent('sentra:shell-pending'));
}
export class ShellBridgeError extends ApiError {
  constructor(message, status, requestKey, uncertain = false) {
    super(message, status); this.requestKey = requestKey; this.uncertain = uncertain;
  }
}

// The authenticated API client owns the bearer. Navigation and drafts never confer authority.
export async function shellBridge(payload, options = {}) {
  if (!payload || !actions.has(payload.action)) throw new ShellBridgeError('Ação do shell não disponível.', 400);
  if (['owner', 'principal', 'grant', 'permissions'].some(key => key in payload) ||
      ('path' in payload && !projectReviewActions.has(payload.action))) {
    throw new ShellBridgeError('A identidade e o escopo são definidos pelo servidor.', 400);
  }
  if (String(payload.action || '').startsWith('network_') &&
      ['bind', 'host', 'renderer', 'mesh_key', 'fingerprint', 'identity', 'grant_id'].some(key => key in payload)) {
    throw new ShellBridgeError('A rede não aceita bind, identidade nem Grant nesta janela.', 400);
  }
  if (['machine_execute', 'input_handoff', 'remote_viewer_open', 'remote_viewer_close', 'code_propose', 'code_execute', 'code_cancel'].includes(payload.action) &&
      ['operation_id', 'resource_id', 'principal_id', 'grant_id'].some(key => key in payload)) {
    throw new ShellBridgeError('A identidade da operação e o recurso físico são derivados no servidor.', 400);
  }
  const mutation = !reads.has(payload.action);
  if (canvasMaintenanceActive()) {
    // Keep this internal: unrelated observation components must not display
    // "Não foi possível concluir" while native maintenance is intentional.
    const blocked = new ShellBridgeError('', 0);
    blocked.maintenance = true;
    throw blocked;
  }
  const body = { ...payload, project_id: payload.project_id || payload.ws };
  delete body.ws;
  if (!body.project_id) throw new ShellBridgeError('Selecione um projeto.', 400);
  if (mutation && !body.request_key) body.request_key = crypto.randomUUID();
  if (mutation) retainMutation(body, true);
  try {
    const envelope = await api('/api/shell/bridge', body, { ...options, readOnly: !mutation });
    if (envelope.ok !== true || !Object.prototype.hasOwnProperty.call(envelope, 'value')) {
      throw new ShellBridgeError('Resposta do shell não confirmada. Consulte o estado.', 0, body.request_key, mutation);
    }
    if (body.action === 'conversation_create' && !confirmedConversation(envelope.value, body)) {
      throw new ShellBridgeError('A criação ainda não tem uma conversa confirmada. Consulte a mesma intenção.',
        0, body.request_key, true);
    }
    if (mutation) retainMutation(body, envelope.value?.status === 'uncertain' ||
      ['UNCERTAIN', 'RUNNING', 'PENDING', 'RESERVED'].includes(envelope.value?.state));
    return envelope.value;
  } catch (error) {
    if (error.name === 'AbortError') {
      if (!mutation) throw error;
      throw new ShellBridgeError('A confirmação demorou. Consulte a mesma operação antes de repetir a ação.',
        0, body.request_key, true);
    }
    if (error instanceof ShellBridgeError) { if (!error.uncertain) retainMutation(body, false); throw error; }
    if (error.status >= 400 && error.status < 500) retainMutation(body, false);
    const wrapped = new ShellBridgeError(error.message, error.status || 0, body.request_key,
      mutation && (!error.status || error.status >= 500));
    wrapped.reauthorizing = error.reauthorizing === true;
    wrapped.maintenance = !mutation && (error.maintenance === true || canvasMaintenanceActive());
    throw wrapped;
  }
}

export function rememberNavigation(value) {
  try { localStorage.setItem('sentra_shell_navigation', JSON.stringify(value)); } catch { /* Preferences are optional. */ }
}
export function restoreNavigation() {
  try {
    const value = JSON.parse(localStorage.getItem('sentra_shell_navigation'));
    if (value && ['home', 'spaces', 'dots', 'conversations', 'space', 'chat', 'documents', 'canvas'].includes(value.view)) return value;
  } catch { /* Invalid preferences cannot select an authoritative resource. */ }
  return { view: 'home' };
}

export function acknowledgeVerifiedPending(keys) {
  // UI cleanup only. The server journal remains immutable; this helper must
  // be called solely for request keys attested in an owner-scoped receipt.
  if (!Array.isArray(keys) || !keys.length ||
      !keys.every(key => typeof key === 'string' && key.length >= 8)) return;
  try {
    const values = JSON.parse(sessionStorage.getItem(pendingStorage)) || {};
    for (const key of keys) delete values[key];
    sessionStorage.setItem(pendingStorage, JSON.stringify(values));
    window.dispatchEvent(new CustomEvent('sentra:shell-pending'));
  } catch { /* The persistent server ledger is unaffected. */ }
}
