// Yjs 13 + Hocuspocus from the existing single-constructor browser bundle.
let runtimePromise;
export async function documentRuntime() {
  if (globalThis.SentraCollabRuntime) return globalThis.SentraCollabRuntime;
  if (!runtimePromise) runtimePromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/vendor/sentra-collab-runtime.js';
    script.onload = () => globalThis.SentraCollabRuntime ? resolve(globalThis.SentraCollabRuntime) : reject(Error('Runtime colaborativo indisponível.'));
    script.onerror = () => { runtimePromise = null; reject(Error('Runtime colaborativo indisponível.')); };
    document.head.append(script);
  });
  return runtimePromise;
}
const b64 = bytes => btoa(String.fromCharCode(...bytes));
const un64 = text => Uint8Array.from(atob(text), c => c.charCodeAt(0));
export async function connectDocument({bridge, projectId, spaceId, documentId, onChange, onConfirmed, onPresence, onStatus, onError}) {
  const {Y, HocuspocusProvider} = await documentRuntime();
  const doc = new Y.Doc(), text = doc.getText('content');
  doc.getMap('metadata');
  const origin = Object.freeze({documentEditor: true});
  const undo = new Y.UndoManager(text, {trackedOrigins: new Set([origin])});
  let provider, ticket, closed = false, authenticated = false, synced = false, writable = false, timer, pendingRead = false;
  const dispatch = payload => bridge({project_id: projectId, space_id: spaceId, document_id: documentId,
    request_key: crypto.randomUUID(), ...payload}).then(result => result?.value ?? result);
  const status = () => ({closed, authenticated, synced, writable});
  const active = () => { if (closed || !authenticated || !synced || !writable) throw Error('Sessão colaborativa não está pronta para edição.'); };
  const publish = (_event, transaction) => {
    if (!closed && authenticated && synced) onChange(text.toString(), transaction?.origin === origin);
  };
  const close = () => {
    if (closed) return;
    closed = true; writable = false; synced = false;
    clearInterval(timer);
    provider?.awareness?.setLocalState(null);
    provider?.destroy(); undo.destroy(); doc.destroy();
    if (ticket) dispatch({action: 'document_session_close', epoch: ticket.epoch}).catch(() => {});
    onStatus(status());
  };
  try {
    ticket = await dispatch({action: 'document_session'});
    if (!ticket?.url || !/^wss?:\/\/(127\.0\.0\.1|localhost|\[::1\]):\d+\/?$/.test(ticket.url) ||
        ticket.documentName !== `sentra-document:v1:${projectId}:${documentId}`) throw Error('Host colaborativo indisponível.');
    provider = new HocuspocusProvider({url: ticket.url, name: ticket.documentName, document: doc,
      token: async () => {
        // Each authentication/reconnection consumes a newly scoped ticket.
        if (ticket.used) ticket = await dispatch({action: 'document_session'});
        ticket.used = true;
        return ticket.token;
      },
      onAuthenticated: ({scope}) => { authenticated = ['readonly', 'read-write'].includes(scope); writable = scope === 'read-write'; onStatus(status()); },
      onSynced: ({state}) => { synced = state === true; publish(); onStatus(status()); },
      onDisconnect: () => { authenticated = false; synced = false; writable = false; onStatus(status()); },
      onAuthenticationFailed: () => { writable = false; authenticated = false; onStatus(status()); onError(Error('Sessão colaborativa recusada ou revogada.')); },
    });
    text.observe(publish);
    // Yjs updates observed locally are drafts until the host's immutable
    // revision/receipt confirms their content. Read reconciliation is safe to
    // repeat; mutating frames are never replayed after an ambiguous precommit.
    timer = setInterval(async () => {
      if (closed || !authenticated || !synced || pendingRead) return;
      pendingRead = true;
      try {
        const confirmed = await dispatch({action: 'document_get'});
        if (!closed && confirmed.content === text.toString() && confirmed.receipt_id) onConfirmed(confirmed);
      } catch (error) {if (!closed) {writable = false; onStatus(status()); onError(error);}}
      finally {pendingRead = false;}
    }, 1500);
    provider.awareness?.on('change', () => {
      if (!closed && authenticated) onPresence([...provider.awareness.getStates().entries()].map(([id, value]) => {
        const cursor = {};
        for (const key of ['anchor', 'head']) {
          try {
            const absolute = Y.createAbsolutePositionFromRelativePosition(Y.decodeRelativePosition(un64(value.cursor?.[key] || '')), doc);
            if (absolute?.type === text) cursor[key] = absolute.index;
          } catch { /* invalid remote cursor is never rendered */ }
        }
        return {clientId: id, user: value.user, cursor};
      }));
    });
    return {close, status,
      setContent(next) {
        active();
        if (typeof next !== 'string' || next.includes('\0') || new TextEncoder().encode(next).length > 524288) throw Error('Documento excede o limite.');
        const previous = text.toString(); let prefix = 0, suffix = 0;
        while (prefix < previous.length && prefix < next.length && previous[prefix] === next[prefix]) prefix++;
        while (suffix < previous.length - prefix && suffix < next.length - prefix && previous.at(-1 - suffix) === next.at(-1 - suffix)) suffix++;
        doc.transact(() => {
          if (previous.length - prefix - suffix) text.delete(prefix, previous.length - prefix - suffix);
          if (next.length - prefix - suffix) text.insert(prefix, next.slice(prefix, next.length - suffix));
        }, origin);
      },
      cursor(anchor, head) {
        if (closed || !authenticated || !synced) return;
        const encode = n => b64(Y.encodeRelativePosition(Y.createRelativePositionFromTypeIndex(text, Math.min(text.length, Math.max(0, n)))));
        provider.awareness?.setLocalState({cursor: {anchor: encode(anchor), head: encode(head)}});
      },
      undo() { active(); undo.undo(); }, redo() { active(); undo.redo(); },
    };
  } catch (error) { close(); throw error; }
}
