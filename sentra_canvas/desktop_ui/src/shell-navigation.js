export function rowsInSpace(rows, projectId, spaceId) {
  return (rows || []).filter(row => row.project_id === projectId && row.space_id === spaceId);
}

export function canvasNavigation(dot) {
  return { view: 'canvas', project_id: dot.project_id, space_id: dot.space_id,
    dot_id: dot.canvas_root_dot_id || dot.dot_id, conversation_id: null };
}

export function confirmedConversation(value, request) {
  return Boolean(value && value.status !== 'uncertain' && typeof value.conversation_id === 'string'
    && value.conversation_id && value.project_id === request.project_id
    && value.space_id === request.space_id && value.dot_id === request.dot_id);
}

const WORK_VIEWS = new Set(['spaces', 'dots', 'conversations', 'space', 'chat', 'documents', 'canvas', 'network']);
const WORK_KEY = 'sentra_shell_last_work';

export function workSurface(value) {
  if (!value || !WORK_VIEWS.has(value.view)) return null;
  const text = field => typeof value[field] === 'string' && value[field] ? value[field] : null;
  return { view: value.view, project_id: text('project_id'), space_id: text('space_id'),
    dot_id: text('dot_id'), conversation_id: text('conversation_id') };
}

export function rememberWorkSurface(value, storage) {
  const surface = workSurface(value);
  const target = storage || globalThis.localStorage;
  if (!surface || !target) return surface;
  try { target.setItem(WORK_KEY, JSON.stringify(surface)); } catch { /* A missing preference cannot block navigation. */ }
  return surface;
}

export function restoreWorkSurface(storage) {
  const target = storage || globalThis.localStorage;
  if (!target) return null;
  try { return workSurface(JSON.parse(target.getItem(WORK_KEY))); }
  catch { return null; }
}

// Local preferences are a navigation hint, never an authorization source. Only
// offer resume for entities present in the current authoritative project read.
export function resumableWorkSurface(value, home) {
  const surface = workSurface(value);
  if (!surface || !home?.project_id || surface.project_id !== home.project_id) return null;
  const spaces = home.spaces || [];
  if (surface.space_id && !spaces.some(row => row.space_id === surface.space_id && row.project_id === surface.project_id)) return null;
  if (surface.view === 'chat') {
    const row = (home.conversations || []).find(item => item.conversation_id === surface.conversation_id && item.project_id === surface.project_id && item.space_id === surface.space_id);
    return row ? { ...surface, dot_id: row.dot_id } : null;
  }
  if (surface.dot_id && !(home.dots || []).some(row => row.dot_id === surface.dot_id && row.project_id === surface.project_id && row.space_id === surface.space_id)) return null;
  if (['space', 'documents', 'network', 'canvas'].includes(surface.view) && !surface.space_id) return null;
  return { ...surface, conversation_id: null };
}
