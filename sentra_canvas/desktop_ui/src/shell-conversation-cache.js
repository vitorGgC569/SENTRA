// Private RAM only. Cached text is presentation, never a receipt or permission.
const identifier = value => typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,160}$/.test(value);
function scopeKey(scope) {
  const values = ['project_id', 'space_id', 'conversation_id'].map(key => scope?.[key]);
  return values.every(identifier) ? JSON.stringify(values) : null;
}
export function createConversationCache({ maxEntries = 8, maxBytes = 4 * 1024 * 1024, ttlMs = 300000, now = Date.now } = {}) {
  if (!Number.isSafeInteger(maxEntries) || maxEntries < 1 || !Number.isSafeInteger(maxBytes) || maxBytes < 1 || !Number.isFinite(ttlMs) || ttlMs <= 0) throw Error('Invalid conversation cache bounds');
  const entries = new Map();
  let bytes = 0, hits = 0, misses = 0, evictions = 0;
  function remove(key) { const old = entries.get(key); if (old) { bytes -= old.bytes; entries.delete(key); } }
  function expire() { const time = now(); for (const [key, value] of entries) if (time < value.at || time - value.at >= ttlMs) remove(key); }
  return {
    get(scope) {
      expire(); const key = scopeKey(scope), entry = entries.get(key);
      if (!entry) { misses++; return null; }
      hits++; entries.delete(key); entries.set(key, entry);
      return JSON.parse(entry.json);
    },
    set(scope, messages) {
      const key = scopeKey(scope);
      if (!key || !Array.isArray(messages)) return false;
      const items = [];
      for (const message of messages.slice(-50)) {
        if (!message || typeof message !== 'object' || message.optimistic || !identifier(message.message_id) ||
            !['user', 'assistant', 'system', 'tool'].includes(message.role) || typeof message.content !== 'string' ||
            ['project_id', 'space_id', 'conversation_id'].some(field => message[field] !== scope[field])) return false;
        items.push({ message_id: message.message_id, ...Object.fromEntries(['project_id', 'space_id', 'conversation_id'].map(field => [field, scope[field]])),
          role: message.role, content: message.content,
          created_at: typeof message.created_at === 'string' || typeof message.created_at === 'number' ? message.created_at : null,
          content_truncated: message.content_truncated === true, cached_visual: true });
      }
      const json = JSON.stringify({ items }), size = new TextEncoder().encode(json).byteLength;
      // Do not silently shorten a message to fit; the protected original remains authoritative.
      if (size > maxBytes) { remove(key); return false; }
      expire(); remove(key);
      while (entries.size >= maxEntries || bytes + size > maxBytes) { remove(entries.keys().next().value); evictions++; }
      entries.set(key, { json, bytes: size, at: now() }); bytes += size; return true;
    },
    forget(scope) { remove(scopeKey(scope)); },
    clear() { entries.clear(); bytes = 0; },
    stats() { expire(); return { entries: entries.size, bytes, hits, misses, evictions }; },
  };
}
export const conversationCache = createConversationCache();
if (typeof window !== 'undefined') {
  window.addEventListener('sentra:auth-recovery-failed', () => conversationCache.clear());
  window.addEventListener('pagehide', () => conversationCache.clear());
}
