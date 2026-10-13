// Bounded, presentation-only schema for model-authored interfaces.
// Never accepts HTML, JS, expressions, network URLs or host actions.
const MAX_BYTES = 32768;
const MAX_ELEMENTS = 36;
const MAX_TEXT = 1200;
const MAX_STRING = 160;
const ID = /^[a-z][a-z0-9_-]{0,39}$/;
const TYPES = new Set(['text','metric','progress','table','choice','checklist']);
const isObject = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const fields = (value, required, optional=[]) =>
  isObject(value) && required.every(k => Object.hasOwn(value,k))
  && Object.keys(value).every(k => required.includes(k) || optional.includes(k));
const str = (x,max=MAX_STRING) => typeof x === 'string' && x.length > 0 && x.length <= max
  && !/[\u0000-\u0008\u000b\u000e-\u001f]/.test(x);
const listStrings = (items,max,size=MAX_STRING) =>
  Array.isArray(items) && items.length > 0 && items.length <= max && items.every(x=>str(x,size));
function validElement(x) {
  if (!isObject(x) || !TYPES.has(x.type)) return false;
  switch(x.type) {
    case 'text': return fields(x,['type','text']) && str(x.text,MAX_TEXT);
    case 'metric': return fields(x,['type','label','value'],['detail'])
      && str(x.label) && str(x.value) && (x.detail===undefined || str(x.detail,MAX_TEXT));
    case 'progress': return fields(x,['type','label','value']) && str(x.label)
      && Number.isFinite(x.value) && x.value >= 0 && x.value <= 100;
    case 'table': return fields(x,['type','columns','rows']) && listStrings(x.columns,6)
      && Array.isArray(x.rows) && x.rows.length <= 25
      && x.rows.every(row => Array.isArray(row) && row.length === x.columns.length
        && row.every(cell=>str(cell,MAX_TEXT)));
    case 'choice': return fields(x,['type','id','label','options'],['default'])
      && ID.test(x.id) && str(x.label) && listStrings(x.options,8)
      && new Set(x.options).size === x.options.length
      && (x.default === undefined || x.options.includes(x.default));
    case 'checklist': return fields(x,['type','id','label','items']) && ID.test(x.id)
      && str(x.label) && listStrings(x.items,12)
      && new Set(x.items).size === x.items.length;
    default: return false;
  }
}
// GPT Web may present a complete JSON payload as a single inline-code span
// after a standalone `sentra-ui` label. Accept only this entire-message shape;
// never interpret arbitrary prose or inline code as an instruction or tool.
export function parseSentraUiInlineMessage(message) {
  if (typeof message !== 'string') return null;
  const match = message.trim().match(/^sentra-ui\s*\n\s*`([^`\r\n]+)`\s*$/);
  return match ? parseSentraUi(match[1]) : null;
}
export function parseSentraUi(raw) {
  try {
    if (typeof raw !== 'string' || new TextEncoder().encode(raw).length > MAX_BYTES) return null;
    const value = JSON.parse(raw);
    if (!fields(value,['version','title','elements']) || value.version !== 1
        || !str(value.title) || !Array.isArray(value.elements)
        || value.elements.length > MAX_ELEMENTS
        || !value.elements.every(validElement)) return null;
    const ids = value.elements.filter(x=>x.id).map(x=>x.id);
    if (new Set(ids).size !== ids.length) return null;
    return value;
  } catch { return null; }
}
