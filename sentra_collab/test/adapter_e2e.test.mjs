import test from "node:test";
import assert from "node:assert/strict";
import {mkdtempSync,rmSync,readFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {runInThisContext} from "node:vm";
import * as Y from "yjs";
import {HocuspocusProvider} from "@hocuspocus/provider";
import {SQLiteHost} from "../sqlite_host.mjs";
import {createCollabServer} from "../server.mjs";
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(predicate,message){
  for(let i=0;i<100;i++){if(predicate())return;await pause(25);}
  assert.fail(message);
}
test("actual opt-in sentra-collab.js adapter: two real WS clients and scope enforcement",async()=>{
  const folder=mkdtempSync(join(tmpdir(),"sentra-optin-adapter-"));
  const host=new SQLiteHost({filename:join(folder,"adapter.sqlite")});
  host.setAccess("adapterWS","alice","write");
  host.setAccess("adapterWS","bob","read");
  const server=createCollabServer({...host.callbacks,recheckMs:500});
  await server.listen();
  assert.equal(server.server.httpServer.address().address,"127.0.0.1");
  const source=readFileSync(new URL("../../sentra_canvas/static/sentra-collab.js",import.meta.url),"utf8");
  // Same JS realm as Yjs: Yjs plain-value detection rejects cross-realm objects.
  // This mirrors the script being loaded into the host page after opt-in.
  const prior=globalThis.SentraCollab;
  runInThisContext(source,{filename:"sentra-collab.js"});
  assert.equal(typeof globalThis.SentraCollab.connect,"function");
  const url="ws://127.0.0.1:"+server.server.httpServer.address().port;
  const aliceChanges=[],bobChanges=[],alicePresence=[],bobPresence=[];
  const alice=globalThis.SentraCollab.connect({
    workspaceId:"adapterWS",url,Y,HocuspocusProvider,
    getToken:()=>host.issueCredential("adapterWS","alice"),
    onChange:state=>aliceChanges.push(state),
    onPresence:states=>alicePresence.push(states)
  });
  const bob=globalThis.SentraCollab.connect({
    workspaceId:"adapterWS",url,Y,HocuspocusProvider,
    getToken:()=>host.issueCredential("adapterWS","bob"),
    onChange:state=>bobChanges.push(state),
    onPresence:states=>bobPresence.push(states)
  });
  try {
    await until(()=>alice.status().synced&&bob.status().synced,
      "both adapters must finish live handshake and authenticate");
    assert.equal(alice.status().writable,true);
    assert.equal(bob.status().writable,false);
    alice.setViewport({x:15,y:-20,zoom:1.1});
    alice.setNode("nodeA",{x:5,y:6,width:300,height:180});
    alice.setNote("memo","real adapter visual only");
    await until(()=>bob.snapshot().notes.memo==="real adapter visual only"&&
      bob.snapshot().nodes.nodeA?.width===300&&
      bob.snapshot().layout.viewport?.x===15,"adapter did not render remote Yjs state");
    assert.ok(bobChanges.length>0);
    assert.throws(()=>bob.setNote("illegal","no-write"),/collaboration-denied/);
    bob.setPresence({cursor:{x:90,y:11},selection:"nodeA"});
    await until(()=>alicePresence.some(states=>states.some(v=>v?.user?.id==="bob")),
      "sanitized read-only presence not forwarded to adapter");
    assert.ok(alicePresence.some(states=>states.some(v=>
      v?.user?.id==="bob"&&v.cursor?.x===90&&v.selection==="nodeA")));
    assert.equal((await host.callbacks.loadSnapshot({workspaceId:"adapterWS"})).revision>=3,true);
  }finally{
    alice.disconnect();bob.disconnect();
    await server.destroy();host.close();
    rmSync(folder,{recursive:true,force:true});
    if(prior===undefined)delete globalThis.SentraCollab;
    else globalThis.SentraCollab=prior;
  }
});
