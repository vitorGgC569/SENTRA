"use strict";
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const worker = fs.readFileSync(__dirname + '/service-worker.js', 'utf8');

function section(start, end) {
  const offset = worker.indexOf(start);
  assert.ok(offset >= 0, start);
  const stop = worker.indexOf(end, offset + start.length);
  assert.ok(stop > offset, end);
  return worker.slice(offset, stop);
}
function harness(data = {}) {
  const state = structuredClone(data), errors = [], effects = [];
  const sandbox = { console, Date, Map, Set, Promise, JSON, Number, String,
    omaWorkers: new Map(), omaResumeBusy: new Set(), OMA_ACTIVE_PREFIX: 'oma_active_',
    omaNoteError: async (...args) => errors.push(args),
    omaReleaseControllerReferences: async () => effects.push('release'),
    omaRelay: async () => ({ok: true}),
    chrome: { storage: { local: {
      async get(keys) {
        await Promise.resolve();
        if (keys === null) return structuredClone(state);
        const defaults = typeof keys === 'object' && !Array.isArray(keys) ? keys : {};
        const names = typeof keys === 'string' ? [keys] : Array.isArray(keys) ? keys : Object.keys(keys);
        return structuredClone(Object.fromEntries(names.map(key => [key, state[key] ?? defaults[key]])));
      },
      async set(values) { await Promise.resolve(); Object.assign(state, structuredClone(values)); },
      async remove(keys) { await Promise.resolve(); for (const key of [keys].flat()) delete state[key]; },
    } } },
  };
  vm.createContext(sandbox);
  vm.runInContext(section('let omaOutboxFlushTask', 'async function omaCheckForUpdates'), sandbox);
  vm.runInContext(section('function omaActiveKey', 'async function omaFinishActive'), sandbox);
  vm.runInContext(section('async function omaRenewActive', '// Backstop'), sandbox);
  vm.runInContext(section('async function omaStartupCleanup', 'async function omaEnsureRecoveryGuardOnExistingTabs'), sandbox);
  return {state, errors, effects, sandbox};
}

test('concurrent active patches retain both receipt progress and heartbeat metadata', async () => {
  const {state, sandbox} = harness({oma_active_8: {job_id:'websend_one',lease_token:'original'}});
  await Promise.all([
    sandbox.omaSaveActive(8, {assistant_revision:19, assistant_frame_acked:true}),
    sandbox.omaSaveActive(8, {hb_sw:4}),
  ]);
  assert.equal(state.oma_active_8.assistant_revision, 19);
  assert.equal(state.oma_active_8.assistant_frame_acked, true);
  assert.equal(state.oma_active_8.hb_sw, 4);
  assert.equal(state.oma_active_8.lease_token, 'original');
});

test('late renewal does not resurrect a cleared job or overwrite the next job', async () => {
  let release;
  const {state, sandbox} = harness({oma_active_8: {job_id:'old',lease_token:'original',worker:'TAB-8'}});
  sandbox.omaRenewIdentity = () => new Promise(resolve => { release = resolve; });
  const renewing = sandbox.omaRenewActive(8);
  while (!release) await new Promise(resolve => setImmediate(resolve));
  await sandbox.omaClearActive(8);
  await sandbox.omaSaveActive(8, {job_id:'new',lease_token:'new-lease',assistant_revision:7});
  release(); await renewing;
  assert.equal(state.oma_active_8.job_id, 'new');
  assert.equal(state.oma_active_8.assistant_revision, 7);
  assert.equal(state.oma_active_8.hb_sw, undefined);
});

test('ACK for an old result cannot erase a newer result and overlapping flushes share delivery', async () => {
  let release;
  const {state, sandbox} = harness({oma_result_one:{job_id:'one',status:'FAILED',error:'old'}});
  const sent=[];
  sandbox.omaRelay = async (_path, options) => {
    sent.push(JSON.parse(options.body));
    await new Promise(resolve => { release = resolve; });
  };
  const first=sandbox.omaFlushOutbox(), second=sandbox.omaFlushOutbox();
  while (!release) await new Promise(resolve => setImmediate(resolve));
  await sandbox.omaMutateResults(() => sandbox.chrome.storage.local.set({oma_result_one:{job_id:'one',status:'COMPLETED',result:'new'}}));
  release(); await Promise.all([first,second]);
  assert.equal(sent.length, 1);
  assert.equal(state.oma_result_one.result, 'new');
  sandbox.omaRelay = async (_path, options) => sent.push(JSON.parse(options.body));
  await sandbox.omaFlushOutbox();
  assert.equal(sent.at(-1).result, 'new');
  assert.equal(state.oma_result_one, undefined);
});

test('worker recreation retains pending outbox across transient transport failure', async () => {
  const before=harness({oma_result_one:{job_id:'one',status:'COMPLETED',result:'retained'}});
  before.sandbox.omaRelay = async () => { throw new Error('network reset'); };
  await before.sandbox.omaFlushOutbox();
  const restarted=harness(before.state), sent=[];
  restarted.sandbox.omaRelay = async (_path, options) => sent.push(JSON.parse(options.body));
  await restarted.sandbox.omaFlushOutbox();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].result, 'retained');
  assert.equal(restarted.state.oma_result_one, undefined);
});

test('browser startup retains original job identity and makes web recovery observation only', async () => {
  const {state,effects,sandbox} = harness({oma_active_8:{job_id:'websend_one',lease_token:'original',
    send_reserved:true,assistant_revision:12,assistant_signature:'digest'},
    oma_pool_instance_id:'POOL-original',oma_result_done:{job_id:'done',result:'already ready'}});
  await sandbox.omaStartupCleanup();
  assert.equal(state.oma_active_8.lease_token, 'original');
  assert.equal(state.oma_active_8.assistant_revision, 12);
  assert.equal(state.oma_active_8.observe_only, true);
  assert.equal(state.oma_pool_instance_id, 'POOL-original');
  assert.equal(state.oma_result_done.result, 'already ready');
  assert.deepEqual(effects, []); // no navigation or release destroys pending evidence
});

test('unreadable browser storage cannot authorize startup tab restoration', async () => {
  const {effects,errors,sandbox}=harness();
  sandbox.chrome.storage.local.get=async()=>{throw new Error('storage temporarily unavailable');};
  await sandbox.omaStartupCleanup();
  assert.deepEqual(effects,[]);
  assert.equal(errors[0][0],'startup_active_load');
});

for (const event of ['onInstalled','onStartup']) test(`${event} invalidates identity and fences retained Web work before tab injection`, async () => {
  const {state,effects,sandbox}=harness({oma_active_8:{job_id:'websend_one',lease_token:'original',
    send_reserved:true,assistant_revision:12,assistant_signature:'digest'},
    oma_result_done:{job_id:'done',result:'already ready'}});
  let callback;
  sandbox.chrome.runtime = {[event]: {addListener(fn){callback=fn;}}};
  sandbox.chrome.alarms = {create(){}};
  sandbox.omaIdInvalidateAll = async reason => {
    assert.equal(reason,'identity_unknown');
    assert.equal(state.oma_active_8.observe_only,undefined);
    effects.push('invalidate_identity');
  };
  sandbox.omaEnsureRecoveryGuardOnExistingTabs = async () => {
    assert.equal(state.oma_active_8.observe_only,true);
    effects.push('guard_existing_tabs');
  };
  const end = event === 'onInstalled' ? 'chrome.runtime.onStartup' : 'chrome.alarms.onAlarm';
  vm.runInContext(section(`chrome.runtime.${event}.addListener`,end),sandbox);
  await callback({reason:'update'});
  assert.equal(state.oma_active_8.lease_token,'original');
  assert.equal(state.oma_active_8.assistant_revision,12);
  assert.equal(state.oma_result_done.result,'already ready');
  assert.deepEqual(effects,['invalidate_identity','guard_existing_tabs']);
});
