"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = __dirname;
const worker = fs.readFileSync(path.join(root, "service-worker.js"), "utf8");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
const guardPath = path.join(root, "native-image-guard.js");
const guardBytes = fs.readFileSync(guardPath);
const guardSha = crypto.createHash("sha256").update(guardBytes).digest("hex");

test("the extension service worker loads native-image-guard.js", () => {
  assert.equal(manifest.background.service_worker, "service-worker.js");
  assert.match(worker, /^importScripts\("native-image-guard\.js"\);$/m);
  assert.match(worker, new RegExp(`const NATIVE_IMAGE_GUARD_SHA256 = "${guardSha}";`));

  const loaded = [];
  const sandbox = {
    importScripts(specifier) {
      const name = path.basename(String(specifier));
      loaded.push(name);
      const file = path.join(root, name);
      assert.equal(path.resolve(file), path.resolve(guardPath));
      vm.runInContext(fs.readFileSync(file, "utf8"), sandbox, { filename: file });
    },
  };
  vm.createContext(sandbox);
  const statement = worker.match(/^importScripts\("native-image-guard\.js"\);$/m)[0];
  vm.runInContext(statement, sandbox, { filename: path.join(root, "service-worker.js") });

  assert.deepEqual(loaded, ["native-image-guard.js"]);
  assert.equal(typeof sandbox.nativeImageVerdict, "function");
  assert.equal(typeof sandbox.mayTransferNativeImage, "function");
  assert.equal(typeof sandbox.noteUncertainNativeImage, "function");
  assert.equal(typeof sandbox.confirmNativeImageBytes, "function");
  const admitted = sandbox.nativeImageVerdict({ admitted: true, mime_type: "image/png" });
  assert.equal(admitted.status, "ADMITTED");
  assert.equal(admitted.success, false);
  const digest = "c".repeat(64);
  const verified = sandbox.nativeImageVerdict({
    mime_type: "image/png", byte_length: 4, sha256: digest, bytes_present: true,
  });
  assert.equal(verified.status, "VERIFIED");
  assert.equal(verified.automatic_resend, false);

  const upload = worker.slice(
    worker.indexOf("async function omaUploadNativeAssets"),
    worker.indexOf("async function omaPublishAssistantFrame"),
  );
  const allow = upload.indexOf("mayTransferNativeImage(nativeImageLedger, fileId)");
  const fetchAt = upload.indexOf("await fetch(");
  const verdict = upload.indexOf("nativeImageVerdict(");
  const bytesProof = upload.indexOf("confirmNativeImageBytes(");
  const chunk = upload.indexOf("'/jobs/generated-asset/chunk'");
  assert.ok(allow > 0 && allow < fetchAt && fetchAt < verdict && verdict < bytesProof && bytesProof < chunk);
  assert.match(upload, /noteUncertainNativeImage\(nativeImageLedger, fileId\)/);
  assert.match(upload, /NATIVE_IMAGE_VERDICT_REFUSED/);
  assert.match(upload, /NATIVE_IMAGE_BYTES_REFUSED/);
  assert.match(upload, /NATIVE_IMAGE_UNCERTAIN_NO_RESEND/);
});
