"use strict";

// Host fence is authoritative. service-worker.js loads this file with
// importScripts and consults it before a native image download and before
// chunk upload. nativeImageVerdict reads declared fields only.
// confirmNativeImageBytes hashes the actual buffer and refuses paint when
// MIME, size or SHA-256 disagree. A pass here is not a ChatGPT file on Canvas.

function nativeImageVerdict(input) {
  const refused = (status, reason) => ({
    status,
    generated_asset_verified: false,
    automatic_resend: false,
    success: false,
    reason: reason || null,
    assets: [],
  });
  if (!input || typeof input !== "object" || input.uncertain === true) {
    return refused(input && input.uncertain === true ? "UNCERTAIN_NO_RESEND" : "ADMITTED",
      input && input.uncertain === true ? "uncertain" : "no_binary");
  }
  const mime = input.mime_type || input.mime;
  const count = input.byte_length;
  const digest = input.sha256;
  const mimeOk = mime === "image/png" || mime === "image/jpeg";
  const sizeOk = Number.isInteger(count) && count >= 1 && count <= 8 * 1024 * 1024;
  const hashOk = typeof digest === "string" && /^[a-f0-9]{64}$/.test(digest);
  if (!mimeOk || !sizeOk || !hashOk || input.bytes_present !== true) {
    return refused("ADMITTED", "admitted_without_binary");
  }
  return {
    status: "VERIFIED",
    generated_asset_verified: true,
    automatic_resend: false,
    success: true,
    mime_type: mime,
    byte_length: count,
    sha256: digest,
  };
}

function mayTransferNativeImage(ledger, key) {
  if (!ledger || typeof key !== "string" || !key) return false;
  return ledger[key] !== "UNCERTAIN_NO_RESEND";
}

function noteUncertainNativeImage(ledger, key) {
  if (!ledger || typeof key !== "string" || !key) throw Error("native_image_fence_required");
  if (ledger[key] && ledger[key] !== "UNCERTAIN_NO_RESEND") throw Error("native_image_fence_conflict");
  ledger[key] = "UNCERTAIN_NO_RESEND";
  return { status: "UNCERTAIN_NO_RESEND", automatic_resend: false };
}

async function confirmNativeImageBytes(source, claimed) {
  const refused = (reason, extra) => Object.assign({
    paint: false, generated_asset_verified: false, reason: reason || null,
  }, extra || {});
  if (!claimed || typeof claimed !== "object") return refused("no_claim");
  const mime = claimed.mime_type || claimed.mime;
  const expected = claimed.byte_length;
  const digestClaim = claimed.sha256;
  if ((mime !== "image/png" && mime !== "image/jpeg") ||
      !Number.isInteger(expected) || expected < 1 || expected > 8 * 1024 * 1024 ||
      typeof digestClaim !== "string" || !/^[a-f0-9]{64}$/.test(digestClaim)) {
    return refused("admitted_without_binary");
  }
  let raw, blobType = null, blobSize = null;
  if (source && typeof source.arrayBuffer === "function" && Number.isInteger(source.size)) {
    blobType = String(source.type || "");
    blobSize = source.size;
    raw = new Uint8Array(await source.arrayBuffer());
  } else if (source instanceof Uint8Array) {
    raw = source;
  } else if (source instanceof ArrayBuffer) {
    raw = new Uint8Array(source);
  } else {
    return refused("no_binary");
  }
  if (blobSize !== null && (blobSize !== expected || blobSize !== raw.length || blobType !== mime)) {
    return refused("blob_mismatch", { byte_length: raw.length, mime_type: blobType });
  }
  if (raw.length !== expected) return refused("size_mismatch", { byte_length: raw.length });
  const magicOk = mime === "image/png"
    ? raw[0] === 137 && raw[1] === 80 && raw[2] === 78 && raw[3] === 71
    : raw[0] === 255 && raw[1] === 216 && raw[2] === 255;
  if (!magicOk) return refused("signature_mismatch", { mime_type: mime, byte_length: raw.length });
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", raw))]
    .map(x => x.toString(16).padStart(2, "0")).join("");
  if (digest !== digestClaim) {
    return refused("hash_mismatch", { sha256: digest, byte_length: raw.length, mime_type: mime });
  }
  return {
    paint: true, generated_asset_verified: true,
    mime_type: mime, byte_length: raw.length, sha256: digest,
  };
}

const api = { nativeImageVerdict, mayTransferNativeImage, noteUncertainNativeImage,
  confirmNativeImageBytes };
if (typeof module !== "undefined") module.exports = api;
