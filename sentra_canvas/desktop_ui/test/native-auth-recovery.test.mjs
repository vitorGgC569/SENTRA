import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createNativeAuthRecovery} from '../src/native-auth-recovery.js';

test('concurrent 401 recovery invokes one trusted navigation, not every caller', async () => {
  let now = 1000, calls = 0;
  const recover = createNativeAuthRecovery({now: () => now, cooldownMs: 7000});
  const native = {reauthorize: async () => { calls++; return {authenticated_owner:true}; }};
  assert.equal(recover(native), true);
  for (let i = 0; i < 30; i++) assert.equal(recover(native), false);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1);
  now += 5000;
  assert.equal(recover(native), false);
  now += 2500;
  assert.equal(recover(native), true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 2);
});

test('bridge failure is held for cooldown and cannot create an unhandled rejection', async () => {
  let now = 1000, calls = 0;
  const recover = createNativeAuthRecovery({now: () => now, cooldownMs: 7000});
  const native = {reauthorize: async () => { calls++; throw Error('native refused'); }};
  assert.equal(recover(native), true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1);
  assert.equal(recover(native), false);
  now += 7001;
  assert.equal(recover(native), true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 2);
  assert.equal(recover({}), false);
});

test('failed native renewal reports a single actionable failure per cooldown', async () => {
  let now = 1000, failures = 0;
  const recover = createNativeAuthRecovery({now: () => now, cooldownMs: 7000,
    onFailure: () => { failures++; }});
  const native = {reauthorize: async () => { throw Error('old broker port'); }};
  for (let i = 0; i < 15; i++) recover(native);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(failures, 1);
  recover(native);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(failures, 1);
});

test('SSE and binary 401 share one trusted renewal; no stream or media replay', async () => {
  const storage = new Map();
  globalThis.location = {hash:'#token=stale',pathname:'/shell-home.html',search:''};
  globalThis.history = {replaceState(){}};
  globalThis.sessionStorage = {
    getItem:key=>storage.get(key)??null,setItem:(key,v)=>storage.set(key,v)
  };
  let requests = 0, nativeCalls = 0;
  globalThis.window = {pywebview:{api:{reauthorize:async()=>{
    nativeCalls++; return {authenticated_owner:true};
  }}},dispatchEvent(){}};
  globalThis.fetch = async ()=>{requests++;return {
    ok:false,status:401,headers:{get:()=>null},
    json:async()=>({error:'local bearer token required'})
  };};
  const {apiStream,apiBinary,isLocalAuthRecovery} = await import('../src/api.js?auth-sse-test');
  const results = await Promise.allSettled([
    apiStream('project-1'),
    apiBinary('/api/shell/generated-media?project_id=project-1')
  ]);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests,2);
  assert.equal(nativeCalls,1);
  assert.ok(results.every(item=>item.status==='rejected' && isLocalAuthRecovery(item.reason)));
});

test('401 on read and mutation does not automatically replay either operation', async () => {
  const storage = new Map();
  globalThis.location = {hash:'#token=old-local-owner', pathname:'/shell-home.html', search:''};
  globalThis.history = {replaceState(){}};
  globalThis.sessionStorage = {getItem:key=>storage.get(key) ?? null,setItem:(key,val)=>storage.set(key,val)};
  let calls = 0, reauthorizationCalls = 0;
  globalThis.window = {pywebview:{api:{reauthorize:async()=>{reauthorizationCalls++;return {authenticated_owner:true};}}},dispatchEvent(){}};
  globalThis.fetch = async () => { calls++; return {ok:false,status:401,json:async()=>({error:'local bearer token required'})}; };
  const {api,isLocalAuthRecovery} = await import('../src/api.js?auth-test');
  const values = await Promise.allSettled([
    ...Array.from({length:12},()=>api('/api/health')),
    api('/api/shell/bridge',{action:'message_send',input:'never-repeat'}),
  ]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls,13);
  assert.equal(reauthorizationCalls,1);
  assert.ok(values.every(v=>v.status==='rejected' && isLocalAuthRecovery(v.reason)));
  assert.equal(storage.get('sentra_native_token'),'old-local-owner');
});
