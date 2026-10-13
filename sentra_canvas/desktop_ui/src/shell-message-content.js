// Full message bodies are scoped server reads, never a second message store.
export function messageContentKey(message) {
  const ref = message.content_ref;
  return ref ? `${message.message_id}:${ref.revision}:${ref.sha256}` : message.message_id;
}
export async function completeMessage(message, bridge, scope, isActive = () => true) {
  if (!message.content_truncated) return message;
  const ref = message.content_ref;
  if (!ref || ref.action !== 'message_content' || ref.message_id !== message.message_id || !ref.sha256)
    throw Error('Referência do original indisponível; o preview não será exportado como mensagem completa.');
  let offset = 0, bytes = 0;
  const parts = [];
  do {
    if (!isActive()) throw Error('Leitura interrompida ao sair da conversa.');
    const value = await bridge({ ...scope, action: 'message_content', message_id: message.message_id,
      revision: ref.revision, offset, limit: 65536 });
    if (value.revision !== ref.revision || value.sha256 !== ref.sha256 || value.total_chars !== ref.total_chars ||
        value.offset !== offset || typeof value.content !== 'string') throw Error('O original mudou durante a leitura. Consulte novamente a mensagem.');
    bytes += new TextEncoder().encode(value.content).length;
    if (bytes > 20 * 1024 * 1024) throw Error('Original excede o limite de leitura anunciado.');
    parts.push(value.content);
    const next = value.next_offset;
    if (next !== null && (!Number.isInteger(next) || next <= offset || next > ref.total_chars))
      throw Error('Paginação do original não confirmada.');
    offset = next;
  } while (offset !== null);
  const content = parts.join('');
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content));
  const sha = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  if (sha !== ref.sha256) throw Error('SHA do original não confirmado.');
  return { ...message, content, content_truncated: false };
}
