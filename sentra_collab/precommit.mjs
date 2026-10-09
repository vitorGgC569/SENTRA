/**
 * Per-document pre-apply gate. Hocuspocus beforeSync awaits this before readUpdate
 * can mutate the live Y.Doc or broadcast. afterHandleMessage releases the mutex.
 * Host commit MUST atomically fence revision and live grant epoch.
 */
import * as Y from "yjs";
import { validateYDocument, MAX_SNAPSHOT_BYTES, MAX_UPDATE_BYTES,
  workspaceFromDocument } from "./policy.mjs";

const deny = () => { throw Error("collaboration-denied"); };
const roots = ["layout","nodes","notes"];
export function snapshotOf(doc) {
  validateYDocument(doc,Y);
  const snapshot=Y.encodeStateAsUpdate(doc);
  if (snapshot.byteLength > MAX_SNAPSHOT_BYTES) deny();
  return snapshot;
}

export class PrecommitGate {
  constructor({authorize,commitSnapshot,commitTimeoutMs=4000}) {
    if (typeof authorize !== "function" || typeof commitSnapshot !== "function" ||
        !Number.isInteger(commitTimeoutMs)||commitTimeoutMs<1||commitTimeoutMs>60000) deny();
    this.commitTimeoutMs=commitTimeoutMs;
    this.authorize=authorize;
    this.commitSnapshot=commitSnapshot;
    this.revisions=new Map();
    this.tails=new Map();
    this.pending=new WeakMap();
    this.quarantined=new Set(); // ambiguous commit requires explicit sidecar restart
  }
  setRevision(documentName,revision) {
    workspaceFromDocument(documentName);
    if (!Number.isSafeInteger(revision) || revision < 0) deny();
    this.revisions.set(documentName,revision);
  }
  async acquire(key) {
    const previous=this.tails.get(key) ?? Promise.resolve();
    let unlock;
    const active=new Promise(resolve=>{unlock=resolve;});
    const tail=previous.then(()=>active);
    this.tails.set(key,tail);
    await previous;
    let released=false;
    return () => {
      if (released) return;
      released=true;
      if (this.tails.get(key) === tail) this.tails.delete(key);
      unlock();
    };
  }
  async authorizeSync({context,documentName,document,type,payload,connection}) {
    if (!connection || connection.context !== context || ![0,1,2].includes(type) ||
        !(payload instanceof Uint8Array) || payload.byteLength > MAX_UPDATE_BYTES) deny();
    // A failed/ambiguous host commit must NEVER be replayed on this live Y.Doc.
    // A new sidecar must load the durable authoritative snapshot before serving.
    const action=(type===0 || connection.readOnly) ? "read" : "write";
    // Existing peers may make read-only/no-op handshakes while quarantined;
    // mutating updates are denied after candidate equivalence is checked.
    await this.authorize(context,documentName,action);
    if (type===0) return;
    if (!payload.byteLength || this.pending.has(connection)) deny();
    const release=await this.acquire(documentName);
    let commitStarted=false;
    try {
      await this.authorize(context,documentName,action);
      const before=snapshotOf(document);
      const candidate=new Y.Doc();
      let after;
      try {
        for (const root of roots) candidate.getMap(root);
        Y.applyUpdate(candidate,before);
        Y.applyUpdate(candidate,payload);
        after=snapshotOf(candidate);
      } finally {candidate.destroy();}
      if (connection.readOnly) {
        if (!Buffer.from(before).equals(Buffer.from(after))) deny();
      } else if (!Buffer.from(before).equals(Buffer.from(after))) {
        if(this.quarantined.has(documentName))deny();
        const expectedRevision=this.revisions.get(documentName);
        if (!Number.isSafeInteger(expectedRevision)) deny();
        // The host must atomically check current grant, epoch, expectedRevision,
        // update storage, then return the new revision. No asynchronous broadcast
        // occurs until this call resolves successfully.
        commitStarted=true;
        // Uncertain timeout is NEVER retried here: late DB commit may still land.
        // Quarantine document and require authoritative snapshot reload/restart.
        let timer;
        const response=await Promise.race([
          Promise.resolve().then(()=>this.commitSnapshot({
            workspaceId:workspaceFromDocument(documentName),
            principalId:context.principalId, epoch:context.epoch, context,
            expectedRevision, snapshot:after
          })),
          new Promise((_,reject)=>{
            timer=setTimeout(()=>reject(Error("collaboration-commit-uncertain")),
              this.commitTimeoutMs);
          })
        ]).finally(()=>clearTimeout(timer));
        if (!response || response.revision !== expectedRevision+1) deny();
        // Commit linearization point: a later revoke does not undo a valid commit.
        this.revisions.set(documentName,response.revision);
      }
      this.pending.set(connection,release);
    } catch {
      if(commitStarted)this.quarantined.add(documentName);
      release();
      deny();
    }
  }
  recoveryState(documentName) {
    workspaceFromDocument(documentName);
    return Object.freeze({quarantined:this.quarantined.has(documentName),
      revision:this.revisions.get(documentName)??null});
  }
  finish(connection) {
    const release=this.pending.get(connection);
    if (release) {
      this.pending.delete(connection);
      release();
    }
  }
}
