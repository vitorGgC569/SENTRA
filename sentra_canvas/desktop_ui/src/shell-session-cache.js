// Fast, session-only visual warm start. Never a source of authority.
// Only the existing authenticated shell reply can populate this snapshot.
// No model output, messages, operations, approvals, tokens or grants are stored.
export const WARM_CACHE_TTL_MS = 120_000;
const prefix = 'sentra_visual_home_v1:';
const limited = (value, max = 120) => typeof value === 'string' ? value.slice(0, max) : '';
const isProjectId = value => typeof value === 'string' && /^[a-zA-Z0-9_.:-]{1,128}$/.test(value);
function spaceOf(value, projectId) {
  if (!value || value.project_id !== projectId || !limited(value.space_id)) return null;
  return {project_id:projectId,space_id:limited(value.space_id),name:limited(value.name)};
}
function dotOf(value, projectId) {
  if (!value || value.project_id !== projectId || !limited(value.space_id) || !limited(value.dot_id)) return null;
  return {project_id:projectId,space_id:limited(value.space_id),dot_id:limited(value.dot_id),
    canvas_root_dot_id:limited(value.canvas_root_dot_id),agent_id:limited(value.agent_id),
    name:limited(value.name),mascot:typeof value.mascot==='string' ? limited(value.mascot,64) : undefined};
}
function conversationOf(value, projectId) {
  if (!value || value.project_id !== projectId || !limited(value.space_id) || !limited(value.conversation_id)) return null;
  return {project_id:projectId,space_id:limited(value.space_id),
    conversation_id:limited(value.conversation_id),dot_id:limited(value.dot_id),
    title:limited(value.title)};
}
function visualHome(value, projectId) {
  return {
    project_id: projectId,
    space:spaceOf(value.space,projectId),
    spaces:(Array.isArray(value.spaces)?value.spaces:[]).slice(0,30).map(x=>spaceOf(x,projectId)).filter(Boolean),
    dots:(Array.isArray(value.dots)?value.dots:[]).slice(0,48).map(x=>dotOf(x,projectId)).filter(Boolean),
    conversations:(Array.isArray(value.conversations)?value.conversations:[]).slice(0,24).map(x=>conversationOf(x,projectId)).filter(Boolean),
    teams:[], documents:[], capabilities:[], activity:{items:[]},
  };
}
export function saveVisualHome(projectId, confirmed, storage = globalThis.sessionStorage, now = Date.now()) {
  if (!isProjectId(projectId) || confirmed?.project_id !== projectId || !storage) return false;
  try {
    const value = JSON.stringify({version:1,at:now,home:visualHome(confirmed,projectId)});
    if (value.length > 26_000) return false;
    storage.setItem(prefix+projectId,value);
    return true;
  } catch { return false; }
}
export function loadVisualHome(projectId, storage = globalThis.sessionStorage, now = Date.now()) {
  if (!isProjectId(projectId) || !storage) return null;
  try {
    const raw = storage.getItem(prefix+projectId);
    if (!raw || raw.length > 26_000) return null;
    const result = JSON.parse(raw);
    if (result.version !== 1 || !Number.isSafeInteger(result.at) ||
        result.at > now || now-result.at > WARM_CACHE_TTL_MS ||
        result.home?.project_id !== projectId) return null;
    // Re-allowlist the untrusted cached data. It is a visual snapshot ONLY.
    return visualHome(result.home,projectId);
  } catch { return null; }
}
