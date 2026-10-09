// SENTRA collaboration: display-only document validation.
import {createHash} from 'node:crypto';
export const DOC_PREFIX = 'sentra-collab:v1:';
export const MAX_UPDATE_BYTES = 65536;
export const MAX_SNAPSHOT_BYTES = 1048576;
const ID = /^[A-Za-z0-9_-]{1,80}$/;
const validObject = v => v !== null && typeof v === "object" && !Array.isArray(v);
const allowedKeys = (v, names) => validObject(v) && Object.keys(v).every(k => names.includes(k));
const range = (v, low, high) => typeof v === "number" && Number.isFinite(v) && v >= low && v <= high;
const deny = () => { throw new Error("collaboration-denied"); };
export function workspaceFromDocument(name) {
  if (typeof name !== "string" || !name.startsWith(DOC_PREFIX)) deny();
  const ws = name.slice(DOC_PREFIX.length);
  if (!ID.test(ws)) deny();
  return ws;
}
export function validateCanvasState(state) {
  if (!allowedKeys(state, ["layout","nodes","notes"])) deny();
  const {layout,nodes,notes} = state;
  if (!allowedKeys(layout, ["viewport"]) || !validObject(nodes) || !validObject(notes)) deny();
  if (layout.viewport !== undefined) {
    const v = layout.viewport;
    if (!allowedKeys(v, ["x","y","zoom"]) || Object.keys(v).length !== 3 ||
      !range(v.x,-1e6,1e6) || !range(v.y,-1e6,1e6) || !range(v.zoom,0.1,5)) deny();
  }
  if (Object.keys(nodes).length > 512 || Object.keys(notes).length > 128) deny();
  for (const [id,v] of Object.entries(nodes)) {
    if (!ID.test(id) || !allowedKeys(v, ["x","y","width","height"]) ||
      Object.keys(v).length !== 4 || !range(v.x,-1e6,1e6) ||
      !range(v.y,-1e6,1e6) || !range(v.width,100,2000) || !range(v.height,80,1600)) deny();
  }
  for (const [id,value] of Object.entries(notes))
    if (!ID.test(id) || typeof value !== "string" || value.length > 12000) deny();
  return true;
}
export function validateYDocument(doc, Y) {
  if (!doc?.share || !Y?.Map) deny();
  for (const [name,value] of doc.share) {
    if (!["layout","nodes","notes"].includes(name) || !(value instanceof Y.Map)) {
      deny();
    }
  }
  const state = {layout:{},nodes:{},notes:{}};
  for (const name of Object.keys(state)) {
    const value = doc.share.get(name);
    if (value) state[name] = value.toJSON();
  }
  return validateCanvasState(state);
}
// resolveGrant and checkGrant must consult SENTRA's authoritative workspace policy.
// The token is one-use; a reconnect must request a new grant from its host.
export class AccessGate {
  constructor({resolveGrant, checkGrant, consumeNonce, now = () => Date.now()} = {}) {
    if (typeof resolveGrant !== "function" || typeof checkGrant !== "function" ||
        typeof consumeNonce !== "function") deny();
    this.resolveGrant = resolveGrant;
    this.checkGrant = checkGrant;
    this.consumeNonce = consumeNonce;
    this.now = now;
    this.consumed = new Map();
    this.inFlight = new Set();
  }
  async authenticate({token, documentName}) {
    const workspaceId = workspaceFromDocument(documentName);
    if (typeof token !== "string" || token.length < 24 || token.length > 4096) deny();
    for (const [key,expiry] of this.consumed)
      if (expiry <= this.now()) this.consumed.delete(key);
    const fingerprint = createHash('sha256').update(token).digest('hex');
    if (this.consumed.has(fingerprint) || this.inFlight.has(fingerprint) ||
        this.consumed.size + this.inFlight.size >= 10000) deny();
    this.inFlight.add(fingerprint);
    try {
    let grant;
    try { grant = await this.resolveGrant({token, workspaceId}); }
    catch { deny(); }
    if (!grant || grant.workspaceId !== workspaceId ||
      typeof grant.principalId !== "string" || !ID.test(grant.principalId) ||
      !["read","write"].includes(grant.permission) ||
      !range(grant.expiresAt, this.now()+1, this.now()+900000) ||
      !Number.isSafeInteger(grant.epoch) || grant.epoch < 0) deny();
    const context = Object.freeze({
      workspaceId, principalId: grant.principalId, permission: grant.permission,
      epoch: grant.epoch, expiresAt: grant.expiresAt
    });
    await this.authorize(context, "read");
    // Host MUST atomically consume fingerprint in durable/shared replay storage.
    // Process-local cache is only an additional defense.
    let consumed=false;
    try { consumed=await this.consumeNonce({
      fingerprint, workspaceId, principalId:context.principalId,
      epoch:context.epoch, expiresAt:context.expiresAt
    }); } catch { deny(); }
    if (consumed !== true) deny();
    this.consumed.set(fingerprint, context.expiresAt);
    return context;
    } finally {
      this.inFlight.delete(fingerprint);
    }
  }
  async authorize(context, permission = "read") {
    if (!context || this.now() >= context.expiresAt ||
      typeof context.workspaceId !== "string" || typeof context.principalId !== "string" ||
      !ID.test(context.workspaceId) || !ID.test(context.principalId) ||
      !["read","write"].includes(permission) ||
      (permission === "write" && context.permission !== "write")) deny();
    let result = false;
    try { result = await this.checkGrant({...context, action: permission}); }
    catch { deny(); }
    if (result !== true) deny();
    return true;
  }
}
export function sanitizeAwareness(states, context, claim) {
  if (!(states instanceof Map) || states.size > 3 || !context || !claim) deny();
  // Hocuspocus builds a scratch Awareness with a synthetic empty local state.
  // Never bind an identity to that empty state.
  for (const [id,v] of states) {
    if (validObject(v) && Object.keys(v).length === 0) states.delete(id);
    else if (v === null && claim.clientId !== id) states.delete(id);
  }
  if (states.size > 1) deny();
  for (const [id, input] of states) {
    if (!Number.isSafeInteger(id) || id < 0) deny();
    if (input === null) {
      if (claim.clientId !== id) { states.delete(id); continue; }
      continue; // no unbound client may make another client appear offline
    }
    if (!validObject(input)) deny();
    if (claim.clientId !== undefined && claim.clientId !== id) deny();
    claim.clientId = id;
    const value = {user:{id:context.principalId}};
    if (input.cursor !== undefined) {
      const p = input.cursor;
      if (!allowedKeys(p, ["x","y"]) || Object.keys(p).length !== 2 ||
        !range(p.x,-1e6,1e6) || !range(p.y,-1e6,1e6)) deny();
      value.cursor = {x:p.x,y:p.y};
    }
    if (input.selection !== undefined) {
      if (typeof input.selection !== "string" || !ID.test(input.selection)) deny();
      value.selection = input.selection;
    }
    states.set(id,value);
  }
  return states;
}
