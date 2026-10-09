/**
 * Optional Hocuspocus WS/Yjs sidecar. Deliberately no start-on-import.
 * Caller injects real SENTRA authorization and snapshot storage.
 */
import { Server } from "@hocuspocus/server";
import {LocalAdmission} from "./local_admission.mjs";
import {performance} from "node:perf_hooks";
import { PrecommitGate, snapshotOf } from "./precommit.mjs";
import * as Y from "yjs";
import {applyAwarenessUpdate} from "y-protocols/awareness";
import {readAwarenessFrame} from "./awareness_guard.mjs";
import { AccessGate, workspaceFromDocument,
  sanitizeAwareness, MAX_SNAPSHOT_BYTES, DOC_PREFIX } from "./policy.mjs";
const deny = () => { throw Error("collaboration-denied"); };
const MAX_DOCUMENTS = 128;
export function createCollabServer({
  resolveGrant, checkGrant, consumeNonce, loadSnapshot, commitSnapshot,
  allowedOrigins = [], port = 0, recheckMs = 1000, quotas = {}, migrateNotes = false
} = {}) {
  if (typeof loadSnapshot !== "function" || typeof commitSnapshot !== "function" ||
      typeof consumeNonce !== "function" ||
      !Array.isArray(allowedOrigins) || !Number.isInteger(port) || port < 0 || port > 65535 ||
      !Number.isInteger(recheckMs) || recheckMs < 250) deny();
  const gate = new AccessGate({resolveGrant,checkGrant,consumeNonce});
  const admission=new LocalAdmission(quotas);
  const sessions = new Map();
  const awarenessOwners = new Map();
  const check = async (context, documentName, action = "read") => {
    if (!context || context.workspaceId !== workspaceFromDocument(documentName)) deny();
    return gate.authorize(context,action);
  };
  const precommit=new PrecommitGate({authorize:check,commitSnapshot});
  const documentSnapshot=snapshotOf;
  const server = new Server({
    address: "127.0.0.1", port, quiet: true, stopOnSignals: false,
    timeout: 30000, debounce: 150, maxDebounce: 600,
    maxUnauthenticatedQueueSize: 65536,
    maxUnauthenticatedQueueMessages: 8, maxPendingDocuments: 1,
    websocketOptions: {maxPayload: 81920},
    async onUpgrade({request}) {
      // Browser Origins must be explicitly allowlisted by the host.
      const origin = request.headers?.origin;
      if (origin && !allowedOrigins.includes(origin)) deny();
    },
    async onConnect({documentName}) {
      workspaceFromDocument(documentName);
      if (server.hocuspocus.documents.size >= MAX_DOCUMENTS &&
          !server.hocuspocus.documents.has(documentName)) deny();
    },
    async onAuthenticate({token,documentName,socketId,connectionConfig}) {
      const started=performance.now();
      let authenticated=false;
      try {
        const context = await gate.authenticate({token,documentName});
        authenticated=true;
        admission.admit(socketId+":"+documentName,context,performance.now()-started);
        connectionConfig.readOnly = context.permission !== "write";
        sessions.set(socketId + ":" + documentName, {context, documentName, claim:{}});
        return context;
      }catch{
        if(!authenticated)admission.reject();
        deny();
      }
    },
    async connected({socketId,documentName,connection}) {
      const session = sessions.get(socketId + ':' + documentName);
      if (!session) deny();
      session.connection = connection;
    },
    async onTokenSync() {
      // Reauthenticate via a fresh socket and one-time token, never elevate in place.
      deny();
    },
    async onLoadDocument({documentName,context}) {
      await check(context,documentName,"read");
      const workspaceId = workspaceFromDocument(documentName);
      const stored = await loadSnapshot({workspaceId});
      if (!stored || !Number.isSafeInteger(stored.revision) || stored.revision < 0 ||
          (stored.snapshot !== null && !(stored.snapshot instanceof Uint8Array))) deny();
      if (stored.snapshot?.byteLength > MAX_SNAPSHOT_BYTES) deny();
      const doc=new Y.Doc();
      for (const name of ["layout","nodes","notes"]) doc.getMap(name);
      if (stored.snapshot) Y.applyUpdate(doc,stored.snapshot);
      documentSnapshot(doc);
      let revision=stored.revision;
      // Production enables an explicit compatible migration of legacy strings.
      // Commit under the authenticated writer before publishing the new structs.
      if(migrateNotes&&context.permission==='write'){
        let changed=false;const notes=doc.getMap('notes');
        doc.transact(()=>{
          for(const [id,value] of notes.entries())if(typeof value==='string'){
            const text=new Y.Text();text.insert(0,value);notes.set(id,text);changed=true;
          }
        });
        if(changed){
          await check(context,documentName,'write');
          const ack=await commitSnapshot({workspaceId,principalId:context.principalId,
            epoch:context.epoch,context,expectedRevision:revision,snapshot:Y.encodeStateAsUpdate(doc)});
          if(ack?.revision!==revision+1)deny();revision=ack.revision;
        }
      }
      precommit.setRevision(documentName,revision);
      return doc;
    },
    async afterLoadDocument({document,documentName,context}) {
      await check(context,documentName,"read");
      // Hocuspocus owns a separate Y.Doc; materialize root maps on that Doc.
      for (const name of ["layout", "nodes", "notes"]) document.getMap(name);
      documentSnapshot(document);
    },
    async beforeHandleMessage({context,documentName,update,socketId,connection,document}) {
      if (!(update instanceof Uint8Array) || update.length > 81920) deny();
      await check(context,documentName);
      admission.frame(socketId+":"+documentName,update.length);
      // Upstream scratch Awareness.getStates() DOES NOT CONTAIN null entries.
      // Authenticate tombstones from the raw authenticated frame before
      // Hocuspocus can interpret/remit them.
      const awareness=readAwarenessFrame(update,documentName);
      if (awareness?.state === null) {
        const session=sessions.get(socketId+":"+documentName);
        const clientId=awareness.clientId;
        const identityKey=documentName+":"+clientId;
        if (!session||!connection||session.claim.clientId!==clientId||
            awarenessOwners.get(identityKey)!==socketId||
            !document.awareness.getStates().has(clientId))deny();
        applyAwarenessUpdate(document.awareness,awareness.payload,
          {source:"connection",connection});
        if(document.awareness.getStates().has(clientId))deny();
        awarenessOwners.delete(identityKey);
        // The upstream receiver's scratch state has no null, hence no
        // duplicate forwarding; the document above broadcasts its removal.
      }
    },
    async beforeSync(payload) {
      return precommit.authorizeSync(payload);
    },
    async afterHandleMessage({connection}) {
      precommit.finish(connection);
    },
    async beforeHandleAwareness({context,documentName,socketId,states,connection}) {
      await check(context,documentName);
      const session = sessions.get(socketId + ":" + documentName);
      if (!session || !connection) deny();
      sanitizeAwareness(states,context,session.claim);
      for (const [clientId] of states) {
        const key = documentName + ":" + clientId;
        if (awarenessOwners.has(key) && awarenessOwners.get(key) !== socketId) deny();
        awarenessOwners.set(key,socketId);
      }
    },
    async onStateless() { deny(); },
    async beforeBroadcastStateless() { deny(); },
    // Snapshots were committed synchronously BEFORE Hocuspocus applies updates.
    // No deferred post-broadcast write is permitted here.
    async onStoreDocument({document}) {
      documentSnapshot(document);
    },
    async onDisconnect({socketId,documentName}) {
      sessions.delete(socketId + ":" + documentName);
      admission.release(socketId+":"+documentName);
      for (const [key,owner] of awarenessOwners) {
        if (owner === socketId && key.startsWith(documentName + ":"))
          awarenessOwners.delete(key);
      }
    }
  });
  const heartbeat = setInterval(async () => {
    for (const session of [...sessions.values()]) {
      try { await check(session.context,session.documentName); }
      catch {
        if (session.connection) session.connection.close({code:4003,reason:'collaboration-denied'});
        else server.hocuspocus.closeConnections(session.documentName);
      }
    }
  },recheckMs);
  heartbeat.unref?.();
  return {
    server,
    listen: () => server.listen(),
    // Only a direct local method, never a network health endpoint.
    localHealth: () => admission.inspect(),
    async inspectRecovery(workspaceId) {
      workspaceFromDocument(DOC_PREFIX+workspaceId);
      const status=precommit.recoveryState(DOC_PREFIX+workspaceId);
      const stored=await loadSnapshot({workspaceId});
      if(!stored||!Number.isSafeInteger(stored.revision)||stored.revision<0)deny();
      return Object.freeze({quarantined:status.quarantined,
        revision:status.revision,persistedRevision:stored.revision,
        restartRequired:status.quarantined||
          (status.revision!==null&&status.revision!==stored.revision)});
    },
    revokeWorkspace(workspaceId) {
      server.hocuspocus.closeConnections(DOC_PREFIX + workspaceId);
    },
    async destroy() {
      clearInterval(heartbeat);
      try {await server.destroy();} finally {admission.close();sessions.clear();awarenessOwners.clear();}
    }
  };
}
