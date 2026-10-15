import { test } from 'node:test';
import assert from 'node:assert/strict';

const storage = new Map();
globalThis.location = { hash:'#token=local-valid', pathname:'/shell-home.html', search:'' };
globalThis.history = { replaceState(){} };
globalThis.sessionStorage = {
  getItem:key=>storage.get(key)??null,
  setItem:(key,value)=>storage.set(key,value),
};
globalThis.window = {dispatchEvent() {}, pywebview:{api:{reauthorize:async()=>({authenticated_owner:true})}}};
globalThis.CustomEvent = class CustomEvent extends Event {constructor(type, init){super(type);this.detail=init?.detail;}};
const { shellBridge, pendingShellMutations } = await import('../src/shell-bridge.js');
const { beginCanvasMaintenance, endCanvasMaintenance } = await import('../src/shell-maintenance.js');

test('read-only shell POST failure is a query outage, never an uncertain message send', async () => {
  let calls=0;
  globalThis.fetch = async()=>{calls++;throw Error('owner rotating');};
  await assert.rejects(() => shellBridge({action:'home',project_id:'p'}), err => {
    assert.match(err.message, /consultar o runtime local/);
    assert.doesNotMatch(err.message, /Envio não confirmado/);
    assert.equal(err.uncertain,false);
    assert.equal(err.maintenance,false);
    return true;
  });
  assert.equal(calls,1);
  assert.deepEqual(pendingShellMutations('p'),[]);
});

test('maintenance cancels observations without reporting a failed mutation or replaying', async () => {
  let calls=0;
  globalThis.fetch=async()=>{calls++;throw Error('never called');};
  beginCanvasMaintenance();
  try {
    for (const action of ['home','coordinator_approval_list','message_send']) {
      await assert.rejects(() => shellBridge({action,project_id:'p'}), err => {
        assert.equal(err.maintenance,true);
        assert.equal(err.uncertain,false);
        return true;
      });
    }
    assert.equal(calls,0);
    assert.deepEqual(pendingShellMutations('p'),[]);
  } finally {endCanvasMaintenance();}
});

test('in-flight read failure during native update is suppressible without losing receipts', async () => {
  let fail;
  globalThis.fetch=()=>new Promise((_,reject)=>{fail=reject;});
  const pending = shellBridge({action:'home',project_id:'p'});
  beginCanvasMaintenance();
  fail(new Error('broker stopped'));
  try {
    await assert.rejects(pending, err=>{
      assert.equal(err.maintenance,true);
      assert.equal(err.uncertain,false);
      return true;
    });
  } finally {endCanvasMaintenance();}
});

test('genuine mutation failure remains UNCERTAIN and is retained for reconciliation', async () => {
  globalThis.fetch=async()=>{throw Error('connection broke');};
  await assert.rejects(() => shellBridge({action:'dot_create',project_id:'p',space_id:'s',name:'test'}), err=>{
    assert.match(err.message,/Envio não confirmado/);
    assert.equal(err.uncertain,true);
    assert.equal(err.maintenance,false);
    assert.ok(typeof err.requestKey==='string');
    return true;
  });
  assert.equal(pendingShellMutations('p').length,1);
  storage.clear();
});
