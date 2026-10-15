/** Roving tabindex. Tab stays with the browser. Arrows do not wrap. */

export function orientationForWidth(width) {
  return Number(width) >= 900 ? 'horizontal' : 'vertical';
}

export function tabIndexFor(count, index) {
  const current = Math.max(0, Math.min(Number(index) || 0, Math.max(0, count - 1)));
  return Array.from({ length: Math.max(0, count) }, (_, item) => (item === current ? 0 : -1));
}

export function moveRoving({ index = 0, count = 0, key, orientation = 'horizontal' } = {}) {
  if (!count || count < 1) return null;
  const current = Math.max(0, Math.min(index, count - 1));
  if (key === 'Escape') return { index: current, close: true };
  if (key === 'Home') return { index: 0, close: false };
  if (key === 'End') return { index: count - 1, close: false };
  const map = orientation === 'vertical'
    ? { ArrowDown: 1, ArrowUp: -1 }
    : { ArrowRight: 1, ArrowLeft: -1 };
  const delta = map[key];
  if (!delta) return null;
  const next = current + delta;
  if (next < 0 || next >= count) return { index: current, close: false };
  return { index: next, close: false };
}
