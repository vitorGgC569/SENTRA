/**
 * SENTRA CRIT-003: opt-in LOCAL SQLite host reference, not an auth integration.
 * SQLite BEGIN IMMEDIATE serializes grants, nonce consumption and snapshot CAS
 * across separate processes sharing one LOCAL database file. No service starts.
 * A real SENTRA control plane must own membership, identity and issuance.
 * Requires Node.js 24+ built-in node:sqlite; never provide production secrets.
 */
import {DatabaseSync} from "node:sqlite";
import {randomBytes, createHash} from "node:crypto";
import {isAbsolute} from "node:path";
import * as Y from "yjs";
import {workspaceFromDocument, MAX_SNAPSHOT_BYTES} from "./policy.mjs";
import {snapshotOf} from "./precommit.mjs";

const deny=()=>{throw Error("collaboration-denied");};
const ID=/^[A-Za-z0-9_-]{1,80}$/;
const validId=s=>{if(typeof s!=="string"||!ID.test(s))deny();return s;};
const validWs=s=>workspaceFromDocument("sentra-collab:v1:"+validId(s));
const natural=n=>Number.isSafeInteger(n)&&n>=0;
const digest=t=>createHash("sha256").update(t).digest("hex");
function safeSnapshot(value) {
  if(!(value instanceof Uint8Array)||value.byteLength>MAX_SNAPSHOT_BYTES)deny();
  const doc=new Y.Doc();
  try {
    for(const root of ["layout","nodes","notes"])doc.getMap(root);
    Y.applyUpdate(doc,value);
    snapshotOf(doc);
    return Buffer.from(value);
  }catch{deny();}finally{doc.destroy();}
}
export class SQLiteHost {
  #db;
  #now;
  #closed=false;
  #fault;
  constructor({filename,now=()=>Date.now(),fault}={}) {
    if(typeof filename!=="string"||!isAbsolute(filename)||
       filename===":memory:"||typeof now!=="function"||
       (fault!==undefined&&typeof fault!=="function"))deny();
    this.#now=now;this.#fault=fault;
    // Reject malformed storage access; don't create parent directories or logs.
    this.#db=new DatabaseSync(filename,{timeout:3000});
    try {
      this.#db.exec("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=3000");
      this.#db.exec(`
        CREATE TABLE IF NOT EXISTS members (
          workspace TEXT NOT NULL, principal TEXT NOT NULL,
          permission TEXT NOT NULL CHECK(permission IN ('read','write','none')),
          epoch INTEGER NOT NULL CHECK(epoch >= 0),
          PRIMARY KEY(workspace,principal)
        );
        CREATE TABLE IF NOT EXISTS issued (
          fingerprint TEXT PRIMARY KEY, workspace TEXT NOT NULL,
          principal TEXT NOT NULL, permission TEXT NOT NULL,
          epoch INTEGER NOT NULL, expires INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS nonces (
          fingerprint TEXT PRIMARY KEY, consumed INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS snapshots (
          workspace TEXT PRIMARY KEY, revision INTEGER NOT NULL,
          bytes BLOB NOT NULL
        );
      `);
    }catch{this.#db.close();deny();}
    this.callbacks=Object.freeze({
      resolveGrant:p=>this.resolveGrant(p),
      checkGrant:p=>this.checkGrant(p),
      consumeNonce:p=>this.consumeNonce(p),
      loadSnapshot:p=>this.loadSnapshot(p),
      commitSnapshot:p=>this.commitSnapshot(p)
    });
  }
  #ensure(){if(this.#closed)deny();}
  #transaction(fn){
    this.#ensure();
    let opened=false;
    try {
      this.#db.exec("BEGIN IMMEDIATE");opened=true;
      const answer=fn();
      this.#db.exec("COMMIT");opened=false;
      return answer;
    }catch{
      if(opened){try{this.#db.exec("ROLLBACK");}catch{/* never mask denial */}}
      deny();
    }
  }
  #member(ws,principal){
    return this.#db.prepare("SELECT permission,epoch FROM members WHERE workspace=? AND principal=?")
      .get(ws,principal);
  }
  #allows(context,action){
    if(!context||!["read","write"].includes(action)||!ID.test(context.workspaceId??"")||
       !ID.test(context.principalId??"")||!natural(context.epoch)||
       !natural(context.expiresAt)||this.#now()>=context.expiresAt)return false;
    const membership=this.#member(context.workspaceId,context.principalId);
    return !!membership&&membership.epoch===context.epoch&&
      ["read","write"].includes(membership.permission)&&
      ["read","write"].includes(context.permission)&&
      (action!=="write"||(membership.permission==="write"&&context.permission==="write"));
  }
  setAccess(workspaceId,principalId,permission) {
    validWs(workspaceId);validId(principalId);
    if(!["read","write","none"].includes(permission))deny();
    return this.#transaction(()=>{
      const old=this.#member(workspaceId,principalId);
      const epoch=(old?.epoch??0)+1;
      if(!natural(epoch))deny();
      this.#db.prepare(`INSERT INTO members (workspace,principal,permission,epoch) VALUES (?,?,?,?)
        ON CONFLICT(workspace,principal) DO UPDATE SET permission=excluded.permission,epoch=excluded.epoch`)
        .run(workspaceId,principalId,permission,epoch);
      return epoch;
    });
  }
  revoke(workspaceId,principalId){return this.setAccess(workspaceId,principalId,"none");}
  issueCredential(workspaceId,principalId,{ttlMs=60000}={}) {
    validWs(workspaceId);validId(principalId);
    if(!Number.isSafeInteger(ttlMs)||ttlMs<1||ttlMs>900000)deny();
    return this.#transaction(()=>{
      const membership=this.#member(workspaceId,principalId);
      if(!membership||!["read","write"].includes(membership.permission))deny();
      const expiresAt=this.#now()+ttlMs;
      if(!natural(expiresAt))deny();
      const token=randomBytes(32).toString("hex");
      this.#db.prepare(`INSERT INTO issued
        (fingerprint,workspace,principal,permission,epoch,expires)
        VALUES (?,?,?,?,?,?)`).run(digest(token),workspaceId,principalId,
          membership.permission,membership.epoch,expiresAt);
      return token;
    });
  }
  async resolveGrant({token,workspaceId}={}) {
    this.#ensure();validWs(workspaceId);
    if(typeof token!=="string"||token.length<24||token.length>4096)deny();
    try {
      const row=this.#db.prepare(`SELECT workspace,principal,permission,epoch,expires
        FROM issued WHERE fingerprint=?`).get(digest(token));
      if(!row||row.workspace!==workspaceId)deny();
      const context={workspaceId:row.workspace,principalId:row.principal,
        permission:row.permission,epoch:row.epoch,expiresAt:row.expires};
      if(!this.#allows(context,"read"))deny();
      return context;
    }catch{deny();}
  }
  async checkGrant({action,...context}={}) {
    this.#ensure();
    try{return this.#allows(context,action);}catch{return false;}
  }
  async consumeNonce({fingerprint,workspaceId,principalId,epoch,expiresAt}={}) {
    if(typeof fingerprint!=="string"||!/^[a-f0-9]{64}$/.test(fingerprint)||
       !natural(epoch)||!natural(expiresAt))return false;
    validWs(workspaceId);validId(principalId);
    return this.#transaction(()=>{
      const row=this.#db.prepare(`SELECT workspace,principal,permission,epoch,expires
        FROM issued WHERE fingerprint=?`).get(fingerprint);
      if(!row||row.workspace!==workspaceId||row.principal!==principalId||
         row.epoch!==epoch||row.expires!==expiresAt||
         !this.#allows({workspaceId,principalId,permission:row.permission,epoch,expiresAt},"read"))
        return false;
      const outcome=this.#db.prepare(`INSERT OR IGNORE INTO nonces(fingerprint,consumed)
        VALUES (?,?)`).run(fingerprint,this.#now());
      return outcome.changes===1;
    });
  }
  async loadSnapshot({workspaceId}={}) {
    this.#ensure();validWs(workspaceId);
    try {
      const row=this.#db.prepare("SELECT revision,bytes FROM snapshots WHERE workspace=?")
        .get(workspaceId);
      if(!row)return {revision:0,snapshot:null};
      if(!natural(row.revision))deny();
      const snapshot=new Uint8Array(row.bytes);
      safeSnapshot(snapshot);
      return {revision:row.revision,snapshot};
    }catch{deny();}
  }
  async commitSnapshot({workspaceId,principalId,epoch,context,expectedRevision,snapshot}={}) {
    validWs(workspaceId);validId(principalId);
    if(!natural(epoch)||!natural(expectedRevision)||!context||
       context.workspaceId!==workspaceId||context.principalId!==principalId||
       context.epoch!==epoch)deny();
    // Validate outside BEGIN IMMEDIATE to bound transaction duration.
    const bytes=safeSnapshot(snapshot);
    return this.#transaction(()=>{
      if(!this.#allows(context,"write"))deny();
      const row=this.#db.prepare("SELECT revision FROM snapshots WHERE workspace=?")
        .get(workspaceId);
      if((row?.revision??0)!==expectedRevision||!natural(expectedRevision+1))deny();
      const result=this.#db.prepare(`INSERT INTO snapshots(workspace,revision,bytes)
        VALUES (?,?,?) ON CONFLICT(workspace) DO UPDATE
        SET revision=excluded.revision,bytes=excluded.bytes
        WHERE snapshots.revision=?`)
        .run(workspaceId,expectedRevision+1,bytes,expectedRevision);
      if(result.changes!==1)deny();
      this.#fault?.("after-write-before-commit");
      return {revision:expectedRevision+1};
    });
  }
  /**
   * Read-only recovery verdict after a crashed/ambiguous precommit.
   * No implicit replay, no authority upgrade, no mutation of SQLite/Yjs.
   * A diverged state MUST be investigated and reloaded, never overwritten.
   */
  async reconcileCommit({workspaceId,expectedRevision,candidateSnapshot}={}) {
    this.#ensure();validWs(workspaceId);
    if(!natural(expectedRevision)||!natural(expectedRevision+1)||
       !(candidateSnapshot instanceof Uint8Array))deny();
    const candidate=safeSnapshot(candidateSnapshot);
    const persisted=await this.loadSnapshot({workspaceId});
    let status="diverged";
    if(persisted.revision===expectedRevision)status="not-committed";
    if(persisted.revision===expectedRevision+1&&persisted.snapshot&&
       Buffer.from(persisted.snapshot).equals(candidate))status="committed";
    return Object.freeze({status,persistedRevision:persisted.revision,
      expectedRevision,requiresReload:status!=="not-committed"});
  }
  close() {
    if(this.#closed)return;
    this.#closed=true;this.#db.close();
  }
}
