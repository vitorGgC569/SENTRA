/** Document CRDT schema. Markdown is the portable source of rich documents. */
export const DOCUMENT_PREFIX = 'sentra-document:v1:';
const ID = /^[A-Za-z0-9_-]{1,80}$/;
const forbidden = new Set(['__proto__', 'constructor', 'prototype']);
export function documentScope(name) {
  if (typeof name !== 'string' || !name.startsWith(DOCUMENT_PREFIX)) return null;
  const parts = name.slice(DOCUMENT_PREFIX.length).split(':');
  if (parts.length !== 2 || parts.some(p => !ID.test(p) || forbidden.has(p)))
    throw Error('document-scope-denied');
  return {workspaceId: parts[0], documentId: parts[1]};
}
export function initializeDocument(doc, Y, name) {
  if (documentScope(name)) { doc.getText('content'); doc.getMap('metadata'); }
  else for (const key of ['layout', 'nodes', 'notes']) doc.getMap(key);
}
export function documentProjection(doc, Y) {
  for (const [key, value] of doc.share) {
    if (!((key === 'content' && value instanceof Y.Text) ||
          (key === 'metadata' && value instanceof Y.Map))) throw Error('document-schema-denied');
  }
  const content = doc.getText('content').toString();
  const metadata = doc.getMap('metadata').toJSON();
  if (new TextEncoder().encode(content).length > 524288 || content.includes('\0') ||
      Object.keys(metadata).some(k => !['title', 'format', 'language'].includes(k)) ||
      Object.values(metadata).some(v => typeof v !== 'string') ||
      !metadata.title?.trim() || metadata.title.length > 240 ||
      !['markdown', 'text', 'code'].includes(metadata.format) ||
      (metadata.language && !/^[A-Za-z0-9_+-]{1,40}$/.test(metadata.language)))
    throw Error('document-schema-denied');
  return {content, metadata};
}
export function sanitizeDocumentAwareness(states, context, claim) {
  if (!(states instanceof Map) || states.size > 3) throw Error('document-awareness-denied');
  for (const [id, value] of states) {
    if (value && Object.keys(value).length === 0) { states.delete(id); continue; }
    if (!Number.isSafeInteger(id) || id < 0 ||
        (claim.clientId !== undefined && claim.clientId !== id)) throw Error('document-awareness-denied');
    if (value === null) { if (claim.clientId !== id) states.delete(id); continue; }
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('document-awareness-denied');
    claim.clientId = id;
    const clean = {user: {id: context.principalId}};
    if (value.cursor !== undefined) {
      const cursor = value.cursor;
      if (!cursor || Object.keys(cursor).some(k => !['anchor', 'head'].includes(k)) ||
          !['anchor', 'head'].every(k => typeof cursor[k] === 'string' &&
            cursor[k].length <= 1024 && /^[A-Za-z0-9+/=]+$/.test(cursor[k])))
        throw Error('document-cursor-denied');
      clean.cursor = {anchor: cursor.anchor, head: cursor.head};
    }
    states.set(id, clean);
  }
  if (states.size > 1) throw Error('document-awareness-denied');
  return states;
}
