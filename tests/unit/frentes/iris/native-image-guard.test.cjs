const test = require("node:test");
const assert = require("node:assert/strict");
const guard = require("../../../../edge_extension/native-image-guard.js");

test("admitted without bytes is not a delivered image", () => {
  const verdict = guard.nativeImageVerdict({ admitted: true, mime_type: "image/png" });
  assert.equal(verdict.status, "ADMITTED");
  assert.equal(verdict.success, false);
  assert.equal(verdict.generated_asset_verified, false);
  assert.equal(verdict.automatic_resend, false);
});

test("uncertain transfer stays uncertain and blocks another fetch", () => {
  const ledger = {};
  const noted = guard.noteUncertainNativeImage(ledger, "job-file");
  assert.equal(noted.status, "UNCERTAIN_NO_RESEND");
  assert.equal(noted.automatic_resend, false);
  assert.equal(guard.mayTransferNativeImage(ledger, "job-file"), false);
  const verdict = guard.nativeImageVerdict({
    uncertain: true, mime_type: "image/png", byte_length: 12,
    sha256: "a".repeat(64), bytes_present: true,
  });
  assert.equal(verdict.status, "UNCERTAIN_NO_RESEND");
  assert.equal(verdict.success, false);
  assert.equal(guard.noteUncertainNativeImage(ledger, "job-file").status, "UNCERTAIN_NO_RESEND");
});

test("verified verdict requires mime, size, sha256 and present bytes", () => {
  const digest = "b".repeat(64);
  const missing = guard.nativeImageVerdict({
    mime_type: "image/png", byte_length: 8, sha256: digest, bytes_present: false,
  });
  assert.equal(missing.status, "ADMITTED");
  assert.equal(missing.success, false);
  const verified = guard.nativeImageVerdict({
    mime_type: "image/jpeg", byte_length: 8, sha256: digest, bytes_present: true,
  });
  assert.equal(verified.status, "VERIFIED");
  assert.equal(verified.success, true);
  assert.equal(verified.mime_type, "image/jpeg");
  assert.equal(verified.byte_length, 8);
  assert.equal(verified.sha256, digest);
  assert.equal(verified.automatic_resend, false);
});
