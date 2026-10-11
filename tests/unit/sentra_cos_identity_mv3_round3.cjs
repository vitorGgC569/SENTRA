/* Hermetic MV3 lifecycle execution of the PRODUCTION service-worker block.
 * Node vm is a TEST HARNESS only, not a SENTRA Code Mode/runtime fallback. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.resolve(__dirname,
  "../../edge_extension/service-worker.js"), "utf8");
const start = source.indexOf("// SENTRA_IDENTITY_REVOCATION_BEGIN");
const end = source.indexOf("// SENTRA_IDENTITY_REVOCATION_END");
assert.ok(start > 0 && end > start);
const block = source.slice(start, end);
const data = {};
const sent = [];
let online = true;
let ackState = "invalidated";
let serial = 0;
let tabs = [{id: 77, url: "https://chatgpt.com/c/conversation12345"}];
const store = {
  async get(keys) {
    if (keys === null) return {...data};
    const names = typeof keys === "string" ? [keys] : keys;
    return Object.fromEntries(names.filter(k => Object.hasOwn(data,k)).map(k => [k,data[k]]));
  },
  async set(value) { Object.assign(data,value); },
  async remove(keys) { for (const key of typeof keys === "string" ? [keys] : keys) delete data[key]; }
};
function load() {
  const context = {
    crypto: {randomUUID: () => "epoch-" + String(++serial).padStart(12,"0")},
    chrome: {storage:{local:store},tabs:{query:async()=>tabs}},
    OMA_SOURCE_HASH: "f".repeat(64),
    URL,
    omaRelay: async (url, options) => {
      const payload = JSON.parse(options.body);
      sent.push({url,payload});
      if (!online) throw Error("relay unavailable");
      return {state:ackState,grants_created:false};
    }
  };
  vm.createContext(context);
  vm.runInContext(block,context,{timeout:2000});
  return context;
}
(async () => {
  let mv3 = load();
  const first = await mv3.omaIdPrepare(77,"document-abc123456","conversation12345");
  assert.ok(first.identity_epoch && first.profile_epoch);
  assert.equal(first.worker,"TAB-77");
  assert.equal(first.source_sha256,"f".repeat(64));
  assert.ok(!JSON.stringify(data).match(/cookie|bearer|access_token|session_key/i));
  online = false;
  await mv3.omaIdOnTabUpdated(77,{url:"https://chatgpt.com/auth/login"},{id:77});
  const pending = data.sentra_id_revoke_77;
  assert.equal(pending.reason,"signed_out");
  assert.equal(pending.identity_epoch,first.identity_epoch);
  assert.equal(pending.document_id,"document-abc123456");
  assert.equal(pending.worker,"TAB-77");
  assert.equal(await mv3.omaIdPrepare(77,"document-new123456","conversation12345"),null);
  assert.equal(data.sentra_id_doc_77,undefined);
  // Suspension/restart restores queue. 404/network error cannot ack deny notice.
  mv3 = load();
  await mv3.omaIdFlushInvalidations();
  assert.ok(data.sentra_id_revoke_77);
  online = true;
  assert.equal(await mv3.omaIdFlushInvalidations(),true);
  assert.equal(data.sentra_id_revoke_77,undefined);
  // An ACK of the previous logout invalidation does not authenticate a
  // new account. Every tab in this MV3 profile remains fail-closed.
  assert.equal(await mv3.omaIdPrepare(77,"document-new123456","conversation12345"),null);
  assert.equal(await mv3.omaIdPrepare(99,"document-other1234","conversation12345"),null);
  assert.equal(await mv3.omaIdPrepare(88,"document-absent123","conversation12345"),null);
  assert.equal(data.sentra_id_profile_poison.reason,"signed_out");
  // Re-running profile invalidation is idempotent and never publishes proof.
  await mv3.omaIdInvalidateAll("profile_changed");
  assert.ok(data.sentra_id_profile_poison);
  assert.ok(sent.every(i => i.url === "/browser-evidence/invalidate"));
  for (const item of sent) {
    assert.deepEqual(Object.keys(item.payload).sort(),
      ["document_id","identity_epoch","reason","source_sha256","worker"].sort());
  }
  // One trace for Python <-> BrowserEvidenceService contract verification.
  console.log("SENTRA_MV3_TRACE=" + JSON.stringify({
    doc:first.document_id, epoch:first.identity_epoch, notice:pending,
    profile_epoch:first.profile_epoch, events:sent.map(x=>x.payload.reason)}));
})().catch(error => { console.error(error.stack); process.exitCode=1; });
