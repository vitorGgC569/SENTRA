import test from "node:test";
import assert from "node:assert/strict";
import {mkdtempSync,rmSync,readFileSync} from "node:fs";
import {join} from "node:path";
import {tmpdir} from "node:os";
import {runInThisContext} from "node:vm";
import * as Y from "yjs";
import {HocuspocusProvider} from "@hocuspocus/provider";
import {SQLiteHost} from "../sqlite_host.mjs";
import {createCollabServer} from "../server.mjs";
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(predicate,why){
  for(let n=0;n<100;n++){if(predicate())return;await delay(25);}
  assert.fail(why);
}
test("workspace lifecycle: two WS clients switch, revoke, logout, fresh tokens, clear state/presence",async()=>{
  const folder=mkdtempSync(join(tmpdir(),"sentra-ws-lifecycle-"));
  const host=new SQLiteHost({filename:join(folder,"workspace.sqlite")});
  for(const workspace of ["first","second"]){
    host.setAccess(workspace,"alice","write");
    host.setAccess(workspace,"bob","read");
  }
  const app=createCollabServer({...host.callbacks,recheckMs:500});
  await app.listen();
  const source=readFileSync(new URL("../../sentra_canvas/static/sentra-collab.js",
    import.meta.url),"utf8");
  const prior=globalThis.SentraCollab;
  runInThisContext(source,{filename:"sentra-collab.js"});
  const url="ws://127.0.0.1:"+app.server.httpServer.address().port;
  const changesA=[],changesB=[],presenceA=[],presenceB=[],tokens=[];
  const makeSession=(principal,updates,presence)=>globalThis.SentraCollab.createWorkspaceSession({
    url,Y,HocuspocusProvider,
    getToken:({workspaceId})=>{
      tokens.push({principal,workspaceId});
      return host.issueCredential(workspaceId,principal);
    },
    onChange:v=>updates.push(v),
    onPresence:v=>presence.push(v)
  });
  const alice=makeSession("alice",changesA,presenceA);
  const bob=makeSession("bob",changesB,presenceB);
  try{
    assert.equal(app.server.httpServer.address().address,"127.0.0.1");
    alice.switchWorkspace("first");
    bob.switchWorkspace("first");
    await until(()=>alice.status().synced&&bob.status().synced,"first WS handshake failed");
    assert.equal(alice.status().writable,true);
    assert.equal(bob.status().writable,false);
    alice.setViewport({x:8,y:9,zoom:1});
    alice.setNode("n1",{x:2,y:3,width:250,height:160});
    alice.setNote("memo","first-only");
    await until(()=>bob.snapshot()?.notes?.memo==="first-only","first display sync missing");
    assert.throws(()=>bob.setNote("no","viewer cannot write"),/denied/);
    alice.setPresence({cursor:{x:12,y:13},selection:"n1"});
    await until(()=>presenceB.some(e=>e?.peers?.some(s=>s?.user?.id==="alice")),
      "server-stamped first workspace presence missing");
    assert.equal(JSON.stringify(presenceB).includes("superuser"),false);
    bob.switchWorkspace("second");
    await until(()=>bob.status().synced,"second workspace reconnect failed");
    assert.equal(bob.snapshot()?.notes?.memo,undefined,
      "first workspace data must not enter second workspace");
    assert.equal(changesB.at(-2)===null || changesB.includes(null),true);
    assert.equal(presenceB.some(e=>Array.isArray(e)&&e.length===0),true);
    alice.switchWorkspace("second");
    await until(()=>alice.status().synced,"alice failed to join second workspace");
    alice.setNote("secondMemo","isolated");
    await until(()=>bob.snapshot()?.notes?.secondMemo==="isolated","second sync missing");
    assert.equal(alice.snapshot()?.notes?.memo,undefined);
    assert.equal(tokens.some(x=>x.principal==="alice"&&x.workspaceId==="first"),true);
    assert.equal(tokens.some(x=>x.principal==="alice"&&x.workspaceId==="second"),true);
    // Directly attempted executable state is not provided by the display API.
    assert.equal(typeof alice.run,"undefined");
    assert.equal(typeof alice.grant,"undefined");
    assert.equal(typeof alice.lease,"undefined");
    host.revoke("second","bob");
    bob.revoke();
    assert.equal(bob.status().active,false);
    assert.equal(bob.snapshot(),null);
    assert.equal(presenceB.at(-1).length,0);
    assert.throws(()=>bob.setPresence({cursor:{x:1,y:1}}),/denied/);
    await until(()=>app.server.hocuspocus.getConnectionsCount()===1,
      "revoked peer socket not disposed");
    alice.logout();
    assert.equal(alice.status().closed,true);
    assert.equal(alice.status().active,false);
    assert.throws(()=>alice.switchWorkspace("first"),/denied/);
    await until(()=>app.server.hocuspocus.getConnectionsCount()===0,
      "logout should release every live provider/socket");
    assert.equal(JSON.stringify(changesA).includes("grant"),false);
    assert.equal(JSON.stringify(changesB).includes("lease"),false);
  }finally{
    alice.disconnect();bob.disconnect();
    await app.destroy();host.close();
    rmSync(folder,{recursive:true,force:true});
    if(prior===undefined)delete globalThis.SentraCollab;
    else globalThis.SentraCollab=prior;
  }
});
