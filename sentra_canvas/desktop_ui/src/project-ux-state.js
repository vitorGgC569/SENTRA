// Pure state helpers: UI preferences and passive projections, never grants.
const SHA = /^[a-f0-9]{64}$/;
export const DOCK_DEFAULTS = Object.freeze({ files: true, details: false });
export function projectDockKey(ws) {
  return typeof ws === 'string' && /^[\w-]{1,100}$/.test(ws) ? 'sentra.project.docks.v1.' + ws : null;
}
export function loadProjectDocks(storage, ws) {
  const key = projectDockKey(ws);
  if (!key) return { ...DOCK_DEFAULTS };
  try {
    const state = JSON.parse(storage?.getItem(key) || '{}');
    return { files: state.files !== false, details: state.details === true };
  } catch { return { ...DOCK_DEFAULTS }; }
}
export function saveProjectDocks(storage, ws, value) {
  const key = projectDockKey(ws);
  if (!key) return false;
  try {
    storage?.setItem(key, JSON.stringify({ files: value.files === true, details: value.details === true }));
    return true;
  } catch { return false; }
}
export function filterProjectEntries(items, query) {
  const term = String(query || '').trim().toLocaleLowerCase();
  return term ? items.filter(item => item.name.toLocaleLowerCase().includes(term)) : items;
}
export function dpiForScale(scale) {
  // Positive integral Windows DPI scaling 100/125/150; do not accept huge user-controlled rasters.
  return scale === 125 ? 90 : scale === 150 ? 108 : 72;
}
export function nextRevision(previousSha, response) {
  if (!SHA.test(previousSha || '') || !SHA.test(response?.sha256 || response?.source_sha256 || '')) {
    return 'invalid';
  }
  return previousSha === (response.sha256 || response.source_sha256) ? 'same' : 'changed';
}
export function pngDataUrl(payload) {
  if (payload?.rendered !== true || payload?.mime !== 'image/png' ||
      !Number.isInteger(payload.width) || !Number.isInteger(payload.height) ||
      payload.width < 1 || payload.height < 1 || payload.width * payload.height > 2500000 ||
      typeof payload.image_base64 !== 'string' || payload.image_base64.length > 4194304 ||
      !/^[A-Za-z0-9+/]+={0,2}$/.test(payload.image_base64) ||
      !payload.image_base64.startsWith('iVBORw0KGgo')) return null;
  return 'data:image/png;base64,' + payload.image_base64;
}
// Only missing/unavailable read-only visual capability permits a second GET.
export function isPdfTextFallbackAllowed(error) {
  return error?.status === 404 || error?.status === 501 || error?.status === 503;
}
export function validatedPdfVisualResponse(payload, request) {
  if (payload?.read_only !== true || payload?.grants_created !== false ||
      payload?.ocr_used !== false || payload?.path !== request.path ||
      payload?.page !== request.page || payload?.dpi !== request.dpi ||
      !Number.isInteger(payload?.pages) || payload.pages < payload.page || payload.pages > 200 ||
      !SHA.test(payload?.source_sha256 || "")) return null;
  return pngDataUrl(payload);
}
export function projectShortcut(event, { editing = false } = {}) {
  const mod = event.ctrlKey || event.metaKey;
  if (event.altKey) return null;
  if (mod && event.key.toLowerCase() === 'k') return 'search';
  if (mod && event.key.toLowerCase() === 's' && editing) return 'review';
  if (mod && event.key.toLowerCase() === 'b') return 'files';
  if (mod && event.key.toLowerCase() === 'i') return 'details';
  return null;
}
