/**
 * IN-MEMORY REFERENCE ONLY — never use as an authentication or storage service.
 * Models the five mandatory host callbacks with a serialized transaction,
 * epoch/revision fencing and deterministic ambiguous post-commit faults.
 * No listener, HTTP routes, users, passwords, or automatic SENTRA integration.
 */
import {randomBytes, createHash} from "node:crypto";
import * as Y from "yjs";
import {workspaceFromDocument, MAX_SNAPSHOT_BYTES} from "./policy.mjs";
import {snapshotOf} from "./precommit.mjs";

const deny=()=>{throw Error("collaboration-denied");};
const key=(ws,id)=>ws+":"+id;
const digest=value=>createHash("sha256").update(value).digest("hex");
const id=/^[a-zA-Z0-9_-]{1,80}$/;
const validId=value=>{if(typeof value!=="string"||!id.test(value))deny();return value;};
const validWs=value=>workspaceFromDocument("sentra-collab:v1:"+validId(value));
const safeInt=n=>Number.isSafeInteger(n)&&n>=0;
const copy=bytes=>new Uint8Array(bytes);
function checkedSnapshot(snapshot) {
  if(!(snapshot instanceof Uint8Array)||snapshot.byteLength>MAX_SNAPSHOT_BYTES)deny();
  const doc=new Y.Doc();
  try {
    for(const root of ["layout","nodes","notes"])doc.getMap(root);
    Y.applyUpdate(doc,snapshot);
    snapshotOf(doc); // strict, display-only schema and encoded quota
  }catch{deny();}finally{doc.destroy();}
  return copy(snapshot);
}

export class ReferenceHost {
  #members=new Map();
  #credentials=new Map(); // only SHA-256 digests, never plaintext credentials
  #nonces=new Set();
  #documents=new Map();
  #tail=Promise.resolve();
  #faults=new Set();
  #beforeCommit;
  #now;
  constructor({now=()=>Date.now(),beforeCommit=async()=>{}}={}) {
    if(typeof now!=="function"||typeof beforeCommit!=="function")deny();
    this.#now=now;
    this.#beforeCommit=beforeCommit;
    this.callbacks=Object.freeze({
      resolveGrant:args=>this.resolveGrant(args),
      checkGrant:args=>this.checkGrant(args),
      consumeNonce:args=>this.consumeNonce(args),
      loadSnapshot:args=>this.loadSnapshot(args),
      commitSnapshot:args=>this.commitSnapshot(args)
    });
  }
  #transaction(fn) {
    // Serializes all simulated host authority/storage mutations in one instance.
    const result=this.#tail.then(fn);
    this.#tail=result.then(()=>undefined,()=>undefined);
    return result;
  }
  setAccess(workspaceId,principalId,permission) {
    validWs(workspaceId);validId(principalId);
    if(!["read","write","none"].includes(permission))deny();
    const identity=key(workspaceId,principalId);
    const epoch=(this.#members.get(identity)?.epoch??0)+1;
    this.#members.set(identity,{workspaceId,principalId,permission,epoch});
    return epoch;
  }
  revoke(workspaceId,principalId) {
    return this.setAccess(workspaceId,principalId,"none");
  }
  issueCredential(workspaceId,principalId,{ttlMs=60000}={}) {
    validWs(workspaceId);validId(principalId);
    if(!Number.isSafeInteger(ttlMs)||ttlMs<1||ttlMs>900000)deny();
    const member=this.#members.get(key(workspaceId,principalId));
    if(!member||!["read","write"].includes(member.permission))deny();
    const token=randomBytes(32).toString("hex");
    this.#credentials.set(digest(token),{
      ...member,expiresAt:this.#now()+ttlMs
    });
    return token; // issue ONLY to the designated fixture client; never log
  }
  #allows(context,action) {
    if(!context||!["read","write"].includes(action))return false;
    const m=this.#members.get(key(context.workspaceId,context.principalId));
    return !!m&&m.epoch===context.epoch&&
      ["read","write"].includes(m.permission)&&
      (action!=="write"||(m.permission==="write"&&context.permission==="write"))&&
      safeInt(context.epoch)&&typeof context.expiresAt==="number"&&
      this.#now()<context.expiresAt;
  }
  async resolveGrant({token,workspaceId}={}) {
    if(typeof token!=="string")deny();
    validWs(workspaceId);
    const record=this.#credentials.get(digest(token));
    if(!record||record.workspaceId!==workspaceId||
       !this.#allows(record,"read"))deny();
    return {...record};
  }
  async checkGrant(context) {
    return this.#allows(context,context?.action);
  }
  async consumeNonce({fingerprint,workspaceId,principalId,epoch,expiresAt}={}) {
    return this.#transaction(()=>{
      if(typeof fingerprint!=="string"||!/^[a-f0-9]{64}$/.test(fingerprint)||
         !this.#credentials.has(fingerprint)||this.#nonces.has(fingerprint))return false;
      const credential=this.#credentials.get(fingerprint);
      if(credential.workspaceId!==workspaceId||
         credential.principalId!==principalId||credential.epoch!==epoch||
         credential.expiresAt!==expiresAt||!this.#allows(credential,"read"))return false;
      this.#nonces.add(fingerprint);
      return true;
    });
  }
  async loadSnapshot({workspaceId}={}) {
    validWs(workspaceId);
    const value=this.#documents.get(workspaceId);
    return {revision:value?.revision??0,
      snapshot:value ? copy(value.snapshot) : null};
  }
  // Simulates an ACK lost AFTER a successful durable commit. This is NOT a rollback.
  faultAfterCommitOnce(workspaceId) {
    validWs(workspaceId);
    this.#faults.add(workspaceId);
  }
  async commitSnapshot(request) {
    return this.#transaction(async()=>{
      const {workspaceId,principalId,epoch,context,expectedRevision,snapshot}=request??{};
      validWs(workspaceId);validId(principalId);
      if(!safeInt(epoch)||!safeInt(expectedRevision)||
         context?.workspaceId!==workspaceId||context?.principalId!==principalId||
         context?.epoch!==epoch)deny();
      // This hook can inject deterministic concurrency or latency; it is not
      // part of a real production host's atomic transaction.
      await this.#beforeCommit(request);
      if(!this.#allows(context,"write"))deny();
      const current=this.#documents.get(workspaceId);
      if((current?.revision??0)!==expectedRevision)deny();
      const safe=checkedSnapshot(snapshot);
      const revision=expectedRevision+1;
      this.#documents.set(workspaceId,{revision,snapshot:safe});
      if(this.#faults.delete(workspaceId)) {
        // Client receives a failure while the committed snapshot remains.
        throw Error("collaboration-commit-ambiguous");
      }
      return {revision};
    });
  }
  snapshotRevision(workspaceId) {
    validWs(workspaceId);
    return this.#documents.get(workspaceId)?.revision??0;
  }
}
