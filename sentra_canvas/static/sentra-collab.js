/* SENTRA opt-in collaboration adapter, enabled by the owner in native Canvas.
 * Inject matching Yjs and HocuspocusProvider constructors from the host bundle.
 * No Run/Operation/Grant/Lease data enters the collaborative document.
 */
(function(root) {
  "use strict";
  const pattern = /^[A-Za-z0-9_-]{1,80}$/;
  const finite = (x,a,b) => typeof x === "number" && Number.isFinite(x) && x >= a && x <= b;
  const denied = () => { throw Error("collaboration-denied"); };
  const validID = id => { if (typeof id !== "string" || !pattern.test(id)) denied(); return id; };
  function connect({workspaceId,url,getToken,Y,HocuspocusProvider,onChange=()=>{},onPresence=()=>{},onError=()=>{},onDisconnected=()=>{}}={}) {
    validID(workspaceId);
    if (typeof url !== "string" || !/^wss?:\/\//.test(url) ||
        typeof getToken !== "function" || !Y?.Doc || typeof HocuspocusProvider !== "function" ||
        typeof onChange !== "function" || typeof onPresence !== "function" ||
        typeof onError !== "function" || typeof onDisconnected !== "function") denied();
    const doc = new Y.Doc();
    const layout = doc.getMap("layout"), nodes = doc.getMap("nodes"), notes = doc.getMap("notes");
    const editOrigin=Object.freeze({canvas:true});
    const undo=Y.UndoManager ? new Y.UndoManager([layout,nodes,notes],{trackedOrigins:new Set([editOrigin])}) : null;
    let authorized = false, synced = false, closed = false, canWrite = false;
    const active = () => { if (!authorized || !synced || closed) denied(); };
    const writable = () => { active(); if (!canWrite) denied(); };
    const snapshot = () => ({
      layout: layout.toJSON(), nodes: nodes.toJSON(), notes: notes.toJSON()
    });
    doc.on("update", () => {
      if (!closed && authorized) {
        try { onChange(snapshot()); } catch (e) { onError(e); }
      }
    });
    const provider = new HocuspocusProvider({
      url, name: "sentra-collab:v1:" + workspaceId, document:doc,
      token: async () => {
        const token = await getToken({workspaceId});
        if (typeof token !== "string" || token.length < 24) denied();
        return token;
      },
      onAuthenticated: ({scope}={}) => {
        authorized = scope === "readonly" || scope === "read-write";
        canWrite = scope === "read-write";
      },
      onSynced: ({state}={}) => {
        if (authorized && state === true) { synced = true; onChange(snapshot()); }
      },
      onDisconnect: () => {
        authorized = false; canWrite = false; synced = false;
        if (!closed) onDisconnected();
      },
      onAuthenticationFailed: () => {
        authorized = false; canWrite = false; synced = false;
        onError(Error("collaboration-denied"));
      },
    });
    if (provider.awareness) provider.awareness.on("change", () => {
      if (authorized && !closed) onPresence(Array.from(provider.awareness.getStates().values()));
    });
    const api = {
      snapshot,
      setViewport(v) {
        writable();
        if (!v || !finite(v.x,-1e6,1e6) || !finite(v.y,-1e6,1e6) ||
            !finite(v.zoom,.1,5) || Object.keys(v).sort().join() !== "x,y,zoom") denied();
        doc.transact(()=>layout.set("viewport",{x:v.x,y:v.y,zoom:v.zoom}),editOrigin);
      },
      setNode(id,v) {
        writable(); validID(id);
        if (!v || !finite(v.x,-1e6,1e6) || !finite(v.y,-1e6,1e6) ||
            !finite(v.width,100,2000) || !finite(v.height,80,1600) ||
            Object.keys(v).sort().join() !== "height,width,x,y") denied();
        if (!nodes.has(id) && nodes.size >= 512) denied();
        doc.transact(()=>nodes.set(id,{x:v.x,y:v.y,width:v.width,height:v.height}),editOrigin);
      },
      setNote(id,text) {
        writable(); validID(id);
        if (typeof text !== "string" || text.length > 12000) denied();
        if (!notes.has(id) && notes.size >= 128) denied();
        doc.transact(()=>{
          let value=notes.get(id);
          if(!Y.Text){notes.set(id,text);return;} // Injected adapters may lack rich text.
          if(!(value instanceof Y.Text)){
            const previous=typeof value==='string'?value:'';
            value=new Y.Text();value.insert(0,previous);notes.set(id,value);
          }
          const previous=value.toString();let prefix=0,suffix=0;
          while(prefix<previous.length&&prefix<text.length&&previous[prefix]===text[prefix])prefix++;
          while(suffix<previous.length-prefix&&suffix<text.length-prefix&&
                previous[previous.length-1-suffix]===text[text.length-1-suffix])suffix++;
          const deleted=previous.length-prefix-suffix;
          if(deleted)value.delete(prefix,deleted);
          const inserted=text.slice(prefix,text.length-suffix);
          if(inserted)value.insert(prefix,inserted);
        },editOrigin);
      },
      notePosition(id,index){
        active();validID(id);const value=notes.get(id);
        if(!Y.Text||!(value instanceof Y.Text)||!Number.isInteger(index)||index<0||index>value.length)return null;
        return Y.encodeRelativePosition(Y.createRelativePositionFromTypeIndex(value,index));
      },
      resolveNotePosition(id,bytes){
        active();validID(id);
        if(!(bytes instanceof Uint8Array)||bytes.length>1024)return null;
        const value=Y.createAbsolutePositionFromRelativePosition(Y.decodeRelativePosition(bytes),doc);
        return value?.type===notes.get(id)?value.index:null;
      },
      removeNode(id) { writable(); nodes.delete(validID(id)); },
      removeNote(id) { writable(); notes.delete(validID(id)); },
      undo(){writable();undo?.undo();},
      redo(){writable();undo?.redo();},
      clearHistory(){writable();undo?.clear();undo?.stopCapturing();},
      setPresence({cursor,selection}={}) {
        active();
        const value = {};
        if (cursor !== undefined) {
          if (!cursor || !finite(cursor.x,-1e6,1e6) || !finite(cursor.y,-1e6,1e6)) denied();
          value.cursor = {x:cursor.x,y:cursor.y};
        }
        if (selection !== undefined) value.selection = validID(selection);
        provider.awareness?.setLocalState(value);
      },
      disconnect() {
        if (closed) return;
        closed = true; authorized = false; canWrite = false; synced = false;
        provider.destroy(); undo?.destroy(); doc.destroy();
      },
      status() { return {authenticated:authorized, writable:canWrite, synced, closed}; }
    };
    return Object.freeze(api);
  }
  /**
   * Opt-in workspace lifecycle. Never stores grants or execution data.
   * The host's getToken({workspaceId}) MUST issue a fresh, server-consumed
   * one-time token on EVERY provider authentication/reconnect.
   */
  function createWorkspaceSession({url,getToken,Y,HocuspocusProvider,
    onChange=()=>{},onPresence=()=>{},onError=()=>{}}={}) {
    if(typeof getToken!=="function"||typeof onChange!=="function"||
       typeof onPresence!=="function"||typeof onError!=="function")denied();
    let generation=0,current=null,workspaceId=null,closed=false;
    const publishClear=()=>{onChange(null);onPresence([]);};
    function clear() {
      generation++;
      const previous=current;current=null;workspaceId=null;
      if(previous)previous.disconnect();
      publishClear();
    }
    function switchWorkspace(nextWorkspace) {
      if(closed)denied();
      validID(nextWorkspace);
      clear(); // dispose old provider BEFORE fetching any new token
      const myGeneration=generation;
      workspaceId=nextWorkspace;
      try {
        current=connect({
          url,workspaceId:nextWorkspace,Y,HocuspocusProvider,
          getToken:async()=> {
            if(closed||generation!==myGeneration)denied();
            // The host must mint one-use grants for each authentication attempt.
            const token=await getToken({workspaceId:nextWorkspace});
            // A slow issuer cannot deliver a former workspace token to a new one.
            if(closed||generation!==myGeneration)denied();
            return token;
          },
          onChange:value=>{
            if(!closed&&generation===myGeneration)onChange({
              workspaceId:nextWorkspace,display:value
            });
          },
          onPresence:value=>{
            if(!closed&&generation===myGeneration)onPresence({
              workspaceId:nextWorkspace,peers:value
            });
          },
          onDisconnected:()=>{
            if(!closed&&generation===myGeneration)publishClear();
          },
          onError:error=>{
            if(!closed&&generation===myGeneration){
              clear(); // fail closed on auth error; don't retry an old identity
              onError(Error("collaboration-denied"));
            }
          }
        });
      }catch{clear();denied();}
      return Object.freeze({workspaceId:nextWorkspace});
    }
    return Object.freeze({
      switchWorkspace,
      revoke(){if(!closed)clear();},
      logout(){if(!closed){clear();closed=true;}},
      disconnect(){if(!closed){clear();closed=true;}},
      status(){return Object.freeze({workspaceId,closed,
        active:!!current,authenticated:current?.status().authenticated??false,
        synced:current?.status().synced??false,
        writable:current?.status().writable??false});},
      snapshot(){return current?.status().synced ? current.snapshot() : null;},
      setViewport:v=>{if(!current)denied();current.setViewport(v);},
      setNode:(id,v)=>{if(!current)denied();current.setNode(id,v);},
      setNote:(id,v)=>{if(!current)denied();current.setNote(id,v);},
      setPresence:v=>{if(!current)denied();current.setPresence(v);}
    });
  }
  root.SentraCollab = Object.freeze({connect,createWorkspaceSession});
})(globalThis);
