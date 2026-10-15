// The control plane uses Unix seconds; browser Date expects milliseconds.
// Accept ISO timestamps and millisecond epochs from other providers as well.
export function conversationInstant(value) {
  if (value === null || value === undefined || value === '') return NaN;
  const numeric = typeof value === 'number' || (typeof value === 'string' && /^\d+(?:\.\d+)?$/.test(value.trim()));
  const timestamp = numeric ? Number(value) : value;
  if (numeric && !Number.isFinite(timestamp)) return NaN;
  const date = new Date(numeric && Math.abs(timestamp) < 1e11 ? timestamp * 1000 : timestamp);
  return date.getTime();
}

export function formatConversationDate(value, locale = 'pt-BR') {
  const time = conversationInstant(value);
  return Number.isFinite(time) ? new Date(time).toLocaleDateString(locale, { timeZone: 'UTC' }) : '';
}

export function formatConversationDateTime(value, locale = 'pt-BR') {
  const time = conversationInstant(value);
  if (!Number.isFinite(time)) return '';
  return new Date(time).toLocaleString(locale, {
    timeZone: 'UTC', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}
