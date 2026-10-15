"use strict";

// Hermetic byte proof for Frente 6. Fictional PNG/JPEG magic + payload only.
// Does not fetch chatgpt.com, estuary, or any network image.

const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const { confirmNativeImageBytes } = require("./native-image-guard.js");

const png = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10, 0, 1, 2, 3]);
const jpeg = Uint8Array.from([255, 216, 255, 224, 9, 8, 7, 6]);
const pngSha = crypto.createHash("sha256").update(png).digest("hex");
const jpegSha = crypto.createHash("sha256").update(jpeg).digest("hex");

function fakeBlob(bytes, type, size) {
  return {
    size: size === undefined ? bytes.length : size,
    type,
    async arrayBuffer() {
      return bytes.slice().buffer;
    },
  };
}

function paintIfConfirmed(proof, createObjectURL) {
  if (proof.paint !== true) return null;
  return createObjectURL();
}

test("matching fictional bytes may paint; mismatched size MIME or hash refuse", async () => {
  const okPng = await confirmNativeImageBytes(png, {
    mime_type: "image/png", byte_length: png.length, sha256: pngSha,
  });
  assert.equal(okPng.paint, true);
  assert.equal(okPng.generated_asset_verified, true);
  assert.equal(okPng.mime_type, "image/png");
  assert.equal(okPng.byte_length, png.length);
  assert.equal(okPng.sha256, pngSha);
  assert.equal(paintIfConfirmed(okPng, () => "blob:fictional-png"), "blob:fictional-png");

  const okJpeg = await confirmNativeImageBytes(fakeBlob(jpeg, "image/jpeg"), {
    mime_type: "image/jpeg", byte_length: jpeg.length, sha256: jpegSha,
  });
  assert.equal(okJpeg.paint, true);
  assert.equal(okJpeg.sha256, jpegSha);

  const wrongSize = await confirmNativeImageBytes(png, {
    mime_type: "image/png", byte_length: png.length + 1, sha256: pngSha,
  });
  assert.equal(wrongSize.paint, false);
  assert.equal(wrongSize.reason, "size_mismatch");
  assert.equal(paintIfConfirmed(wrongSize, () => { throw Error("must not paint"); }), null);

  const wrongMime = await confirmNativeImageBytes(png, {
    mime_type: "image/jpeg", byte_length: png.length, sha256: pngSha,
  });
  assert.equal(wrongMime.paint, false);
  assert.equal(wrongMime.reason, "signature_mismatch");
  assert.equal(paintIfConfirmed(wrongMime, () => { throw Error("must not paint"); }), null);

  const wrongHash = await confirmNativeImageBytes(png, {
    mime_type: "image/png", byte_length: png.length, sha256: "0".repeat(64),
  });
  assert.equal(wrongHash.paint, false);
  assert.equal(wrongHash.reason, "hash_mismatch");
  assert.equal(wrongHash.sha256, pngSha);
  assert.equal(paintIfConfirmed(wrongHash, () => { throw Error("must not paint"); }), null);

  const wrongBlobType = await confirmNativeImageBytes(fakeBlob(png, "image/jpeg"), {
    mime_type: "image/png", byte_length: png.length, sha256: pngSha,
  });
  assert.equal(wrongBlobType.paint, false);
  assert.equal(wrongBlobType.reason, "blob_mismatch");
  assert.equal(paintIfConfirmed(wrongBlobType, () => { throw Error("must not paint"); }), null);
});

test("canvas still refuses to paint before createObjectURL when size MIME or hash disagree", () => {
  const canvas = fs.readFileSync(path.join(
    __dirname, "..", "sentra_canvas", "desktop_ui", "src", "shell-generated-assets.jsx"), "utf8");
  const check = canvas.indexOf("blob.size !== asset.byte_length || blob.type !== asset.mime_type || hash !== asset.sha256");
  const paint = canvas.indexOf("URL.createObjectURL(blob)");
  assert.ok(check > 0 && paint > check);
  assert.match(canvas, /crypto\.subtle\.digest\('SHA-256', bytes\)/);
  assert.doesNotMatch(canvas, /chatgpt\.com|estuary\/content/);
});
