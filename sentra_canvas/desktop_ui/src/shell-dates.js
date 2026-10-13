// The control plane uses Unix seconds; browser Date expects milliseconds.
// Accept ISO timestamps and millisecond epochs from other providers as well.
export function formatConversationDate(value, locale = 'pt-BR') {
  if (value === null || value === undefined || value === '') return '';
  const numeric = typeof value === 'number' || (typeof value === 'string' && /^\d+(?:\.\d+)?$/.test(value.trim()));
  const timestamp = numeric ? Number(value) : value;
  if (numeric && !Number.isFinite(timestamp)) return '';
  const date = new Date(numeric && Math.abs(timestamp) < 1e11 ? timestamp * 1000 : timestamp);
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString(locale, {timeZone: 'UTC'}) : '';
}
