// Request identity, never matching prose, reconciles an optimistic message.
export function mergeMessages(previous, incoming) {
  const values = new Map(previous.map(message => [message.message_id, message]));
  for (const message of incoming) {
    if (!message.message_id) continue;
    let alreadyConfirmed = false;
    if (message.request_key) for (const [id, old] of values) {
      if (old.request_key !== message.request_key) continue;
      if (old.optimistic && !message.optimistic) values.delete(id);
      if (!old.optimistic && message.optimistic) alreadyConfirmed = true;
    }
    if (!alreadyConfirmed) values.set(message.message_id, { ...values.get(message.message_id), ...message });
  }
  return [...values.values()].sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')) || a.message_id.localeCompare(b.message_id));
}
