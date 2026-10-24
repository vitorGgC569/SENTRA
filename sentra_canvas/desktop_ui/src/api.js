import { createNativeAuthRecovery } from './native-auth-recovery.js';
import { canvasMaintenanceActive } from './shell-maintenance.js';

// Bearer is module-private, never exposed to React props, logs, DOM or URLs.
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has('token')) {
  const value = fragment.get('token');
  history.replaceState(null, '', location.pathname + location.search);
  if (value) sessionStorage.setItem('sentra_native_token', value);
}
const bearer = sessionStorage.getItem('sentra_native_token');
export const hasCredential = Boolean(bearer);
// Viewer identity arbitrates a terminal; it grants no permission. Session
// storage separates windows and preserves identity through a page reload.
let terminalViewer;
try {
  terminalViewer=sessionStorage.getItem('sentra_terminal_viewer_v1');
  if(!/^[a-f0-9]{32}$/.test(terminalViewer||'')){
    terminalViewer=crypto.randomUUID().replaceAll('-','');
    sessionStorage.setItem('sentra_terminal_viewer_v1',terminalViewer);
  }
} catch { terminalViewer=null; }
const requestReauthorization = createNativeAuthRecovery({
  onFailure: () => window.dispatchEvent(new Event('sentra:auth-recovery-failed')),
});
export function isLocalAuthRecovery(error) { return error?.reauthorizing === true; }
export class ApiError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}
export async function api(path, data, options = {}) {
  if (!path.startsWith('/api/')) throw new ApiError('Rota de controle inválida.');
  if (!bearer) throw new ApiError('Abra o desktop pelo SENTRA para autorizar esta janela.', 401);
  const headers = { Authorization: 'Bearer ' + bearer };
  if(terminalViewer)headers['X-Sentra-Input-Client']=terminalViewer;
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch(path, {
      method: data === undefined ? 'GET' : 'POST', headers,
      body: data === undefined ? undefined : JSON.stringify(data),
      cache: 'no-store', credentials: 'omit', redirect: 'error',
      signal: options.signal,
    });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    // Shell reads use POST as transport, but they do not send a mutation.
    // A transient broker restart cannot turn a read into an uncertain send.
    const readOnly = options.readOnly === true || data === undefined;
    const error = new ApiError(readOnly
      ? 'Não foi possível consultar o runtime local.'
      : 'Envio não confirmado. Consulte o estado antes de repetir a ação.');
    error.maintenance = readOnly && canvasMaintenanceActive();
    throw error;
  }
  const value = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && value.error === 'local bearer token required') {
      // A broker restart rotates the bearer. Ask the trusted native window
      // to navigate with the current credential, never expose it to JS and
      // NEVER retry this request, especially when it was a mutation.
      const native = window.pywebview?.api;
      if (native?.reauthorize) {
        requestReauthorization(native);
        // A single owner-verified navigation is pending. This request is not
        // retried, especially if it was a POST with an uncertain receipt.
        const error = new ApiError('Reconectando à sessão local.', 401);
        error.reauthorizing = true;
        throw error;
      }
      throw new ApiError('A janela perdeu a autorização local. Reabra o aplicativo SENTRA atualizado.', 401);
    }
    throw new ApiError(value.error || 'A operação não foi aceita pelo runtime.', response.status);
  }
  return value;
}
export function route(path, fields) {
  return path + '?' + new URLSearchParams(fields).toString();
}

// Streaming is observation-only. The caller cannot select arbitrary headers,
// bearer values, origins or a mutation method.
export async function apiStream(projectId, { after, signal, epoch } = {}) {
  if (!bearer) throw new ApiError('Abra o desktop pelo SENTRA para autorizar esta janela.', 401);
  const headers = { Authorization: 'Bearer ' + bearer, Accept: 'text/event-stream' };
  if(terminalViewer)headers['X-Sentra-Input-Client']=terminalViewer;
  if (after != null) {
    if (!Number.isSafeInteger(after) || after < 0) throw new ApiError('Cursor inválido.', 400);
    headers['Last-Event-ID'] = String(after);
  }
  const response = await fetch(route('/api/shell/stream', { project_id: projectId, ...(epoch ? {epoch} : {}) }), {
    method: 'GET', headers, cache: 'no-store', credentials: 'omit', redirect: 'error', signal,
  });
  if (!response.ok) {
    if (response.status === 401) {
      const native = window.pywebview?.api;
      if (native?.reauthorize) {
        requestReauthorization(native);
        const error = new ApiError('Reconectando à sessão local.', 401);
        error.reauthorizing = true;
        throw error;
      }
    }
    const error = new ApiError('Não foi possível acompanhar a conexão.', response.status);
    error.retryAfter = Number(response.headers.get('Retry-After')) || 0;
    throw error;
  }
  if (!response.body || !response.headers.get('Content-Type')?.startsWith('text/event-stream')) {
    await response.body?.cancel();
    throw new ApiError('Feed incompatível com esta versão do aplicativo.', 501);
  }
  return response;
}

export async function apiBinary(path, options = {}) {
  if (!path.startsWith('/api/shell/generated-media?') || !bearer) throw new ApiError('Arquivo não autorizado.', 401);
  const response = await fetch(path, { headers: { Authorization: 'Bearer ' + bearer },
    cache: 'no-store', credentials: 'omit', redirect: 'error', signal: options.signal });
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    if (response.status === 401 && value.error === 'local bearer token required') {
      const native = window.pywebview?.api;
      if (native?.reauthorize) {
        requestReauthorization(native);
        const error = new ApiError('Reconectando à sessão local.', 401);
        error.reauthorizing = true;
        throw error;
      }
    }
    throw new ApiError(value.error || 'Arquivo ainda não confirmado.', response.status);
  }
  const maximum = options.maxBytes || 20 * 1024 * 1024;
  if (Number(response.headers.get('Content-Length')) > maximum) throw new ApiError('Arquivo excede o limite de tamanho.');
  const blob = await response.blob();
  if (blob.size > maximum) throw new ApiError('Arquivo excede o limite de tamanho.');
  return blob;
}
