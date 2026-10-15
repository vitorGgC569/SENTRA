// Immutable preview reads only. No prompt, receipt, permission or resend API.
const MAX_BYTES = 8_000_000, PAGE_CHARS = 65536, PAGE_BYTES = 262144;
const identifier = value => typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,160}$/.test(value);
const digestPattern = /^[a-f0-9]{64}$/;
const encoder = new TextEncoder();

async function sha256(bytes) {
  const value = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(value)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}
function checkAbort(signal) {
  if (signal?.aborted) throw new DOMException('Preview read cancelled', 'AbortError');
}

export async function readStreamContent(readPage, scope, reference, { signal, onProgress = () => {} } = {}) {
  const fields = Object.fromEntries(['project_id', 'space_id', 'conversation_id'].map(key => [key, scope?.[key]]));
  if (!Object.values(fields).every(identifier) || !reference || reference.action !== 'stream_content' ||
      !/^stream-[a-f0-9]{64}$/.test(reference.reference_id || '') || !digestPattern.test(reference.sha256 || '') ||
      !Number.isSafeInteger(reference.total_chars) || reference.total_chars < 1 || reference.total_chars > MAX_BYTES ||
      !Number.isSafeInteger(reference.total_utf8_bytes) || reference.total_utf8_bytes < reference.total_chars || reference.total_utf8_bytes > MAX_BYTES ||
      reference.page_max_chars !== PAGE_CHARS || reference.page_max_utf8_bytes !== PAGE_BYTES) throw Error('Referência de prévia inválida.');
  let offset = 0, bytes = 0;
  const pages = [];
  do {
    checkAbort(signal);
    const page = await readPage({ ...fields, reference_id: reference.reference_id, offset, limit: PAGE_CHARS }, { signal });
    checkAbort(signal);
    if (!page || Object.keys(fields).some(key => page[key] !== fields[key]) || page.reference_id !== reference.reference_id ||
        page.offset !== offset || page.total_chars !== reference.total_chars || page.total_utf8_bytes !== reference.total_utf8_bytes ||
        page.sha256 !== reference.sha256 || page.persisted !== true || page.partial !== true || page.authoritative !== false ||
        page.closes_trio !== false || page.automatic_retry !== false || typeof page.content !== 'string') throw Error('A página não corresponde à prévia solicitada.');
    const raw = encoder.encode(page.content), chars = [...page.content].length;
    const end = offset + chars;
    if (raw.byteLength > PAGE_BYTES || chars !== Math.min(PAGE_CHARS, reference.total_chars - offset) ||
        page.next_offset !== (end < reference.total_chars ? end : null) ||
        await sha256(raw) !== page.page_sha256) throw Error('A página da prévia está incompleta ou foi alterada.');
    bytes += raw.byteLength;
    if (bytes > reference.total_utf8_bytes || bytes > MAX_BYTES) throw Error('A prévia excedeu o tamanho informado.');
    pages.push(page.content); offset = end;
    checkAbort(signal);
    onProgress({ loaded_chars: offset, total_chars: reference.total_chars });
  } while (offset < reference.total_chars);
  if (bytes !== reference.total_utf8_bytes || await sha256(encoder.encode(pages.join(''))) !== reference.sha256) throw Error('Não foi possível conferir a prévia completa.');
  checkAbort(signal);
  return { items: pages.map((content, index) => ({ message_id: reference.reference_id + ':' + index, content })),
    total_chars: reference.total_chars, total_utf8_bytes: bytes, reference_id: reference.reference_id,
    partial: true, authoritative: false, closes_trio: false };
}
