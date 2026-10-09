// Bearer is module-private, never exposed to React props, logs, DOM or URLs.
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has('token')) {
  const value = fragment.get('token');
  history.replaceState(null, '', location.pathname + location.search);
  if (value) sessionStorage.setItem('sentra_native_token', value);
}
const bearer = sessionStorage.getItem('sentra_native_token');
export const hasCredential = Boolean(bearer);
export class ApiError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}
export async function api(path, data, options = {}) {
  if (!path.startsWith('/api/')) throw new ApiError('Rota de controle inválida.');
  if (!bearer) throw new ApiError('Abra o desktop pelo SENTRA para autorizar esta janela.', 401);
  const headers = { Authorization: 'Bearer ' + bearer };
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
    throw new ApiError(data === undefined
      ? 'Não foi possível consultar o runtime local.'
      : 'Envio não confirmado. Consulte o estado antes de repetir a ação.');
  }
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(value.error || 'A operação não foi aceita pelo runtime.', response.status);
  return value;
}
export function route(path, fields) {
  return path + '?' + new URLSearchParams(fields).toString();
}
