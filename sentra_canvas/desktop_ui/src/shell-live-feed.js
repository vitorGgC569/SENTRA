const LABELS = new Set([
  'Coordenando',
  'Recebendo resposta',
  'Aguardando ChatGPT',
  'Confirmando entrega',
  'Entrega incerta. Não reenvie.',
  'ferramenta',
]);

function activityOf(value) {
  if (LABELS.has(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return '';
  if (/unit_gate|ready_for_promotion|process_exit|grant|\\|\/|:\/\//i.test(value)) return 'ferramenta';
  if (value.length > 32) return 'ferramenta';
  return value;
}

const VISIBLE = new Set(['generating', 'confirming', 'interrupted', 'preview_unavailable']);

export function presentLive(preview) {
  if (!preview || typeof preview !== 'object') return null;
  const activity = activityOf(preview.activity);
  const status = VISIBLE.has(preview.status) ? preview.status : 'idle';
  return {
    authoritative: false,
    partial: true,
    closes_trio: false,
    promotes: false,
    resend: false,
    success: false,
    activity,
    content: typeof preview.content === 'string' ? preview.content : '',
    status,
    uncertain: activity === 'Entrega incerta. Não reenvie.' || preview.status === 'interrupted',
  };
}

export function keepLivePreview(preview) {
  if (!preview || typeof preview !== 'object' || !VISIBLE.has(preview.status)) return null;
  return preview;
}

// Reconnect and phase changes are observations, never permission to resend a turn.
// Keep only a matching operation's text; switching turns must not leak stale prose.
export function reconcileLivePreview(incoming, previous, { readFailed = false } = {}) {
  const kept = keepLivePreview(previous);
  if (readFailed) {
    if (!kept || kept.status === 'interrupted') return kept;
    return { ...kept, activity: 'Reconectando conexão', reconnecting: true };
  }
  const next = keepLivePreview(incoming);
  if (!next) {
    // A durable assistant message can lag the producer's idle notification.
    // Only keep operation-identified text until that message arrives.
    if (kept?.operation_id && kept.content) return {
      ...kept,
      status: kept.status === 'interrupted' ? 'interrupted' : 'confirming',
      activity: kept.status === 'interrupted' ? kept.activity : 'Confirmando entrega',
      reconnecting: false,
    };
    return null;
  }
  const sameOperation = Boolean(kept) && (
    (Boolean(kept.operation_id) && kept.operation_id === next.operation_id) ||
    (!kept.operation_id && !next.operation_id)
  );
  const revisionsKnown = kept?.content_revision != null && next.content_revision != null;
  const sameRevision = revisionsKnown && kept.content_revision === next.content_revision;
  const waitingWithoutRevision = !revisionsKnown &&
    (next.activity !== 'Recebendo resposta' || !next.content);
  const contentKeys = ['content', 'content_revision', 'content_offset', 'content_ref', 'truncated', 'content_error'];
  const statusOnly = !next.content && contentKeys.slice(2).every(key => next[key] == null);
  const sameWindow = (kept?.content_offset ?? 0) === (next.content_offset ?? 0) &&
    (kept?.content_ref?.reference_id ?? null) === (next.content_ref?.reference_id ?? null);
  if (sameOperation && (sameRevision || waitingWithoutRevision) && (sameWindow || statusOnly) &&
      typeof kept.content === 'string' && kept.content.length > String(next.content ?? '').length) {
    // A status-only frame retains one coherent window and its immutable reference.
    // A shifted window can be shorter in UTF-16 while containing newer Unicode text.
    const content = statusOnly ? Object.fromEntries(contentKeys.filter(key => key in kept).map(key => [key, kept[key]])) : { content: kept.content };
    return { ...next, ...content, reconnecting: false };
  }
  return { ...next, reconnecting: false };
}

export function previewStillVisible(preview, messages) {
  if (!presentLive(preview)) return false;
  const operation = typeof preview.operation_id === 'string' ? preview.operation_id : '';
  if (!operation) return true;
  return !(Array.isArray(messages) && messages.some(message =>
    message?.role === 'assistant' && message.operation_id === operation));
}
