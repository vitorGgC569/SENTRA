/** Motion tokens for Cadencia. Only transform and opacity may animate. */

export const MOTION = { ms: 200, ease: 'cubic-bezier(0.22, 1, 0.36, 1)' };
const ALLOWED = new Set(['transform', 'opacity']);

export function watchReducedMotion(onChange, source = globalThis) {
  if (typeof onChange !== 'function') return () => {};
  let query = null;
  try {
    if (typeof source === 'function') query = source('(prefers-reduced-motion: reduce)');
    else if (typeof source?.matchMedia === 'function') query = source.matchMedia('(prefers-reduced-motion: reduce)');
  } catch {
    query = null;
  }
  if (!query) {
    onChange(false);
    return () => {};
  }
  const emit = () => onChange(Boolean(query.matches));
  emit();
  if (typeof query.addEventListener === 'function') query.addEventListener('change', emit);
  else if (typeof query.addListener === 'function') query.addListener(emit);
  let closed = false;
  return () => {
    if (closed) return;
    closed = true;
    if (typeof query.removeEventListener === 'function') query.removeEventListener('change', emit);
    else if (typeof query.removeListener === 'function') query.removeListener(emit);
  };
}

export function readReducedMotion(source = globalThis) {
  const match = typeof source === 'function' ? source : source?.matchMedia;
  if (typeof match !== 'function') return false;
  try {
    const query = typeof source === 'function'
      ? match('(prefers-reduced-motion: reduce)')
      : source.matchMedia('(prefers-reduced-motion: reduce)');
    return Boolean(query?.matches);
  } catch {
    return false;
  }
}

export function transitionValue(reduced, durationMs = MOTION.ms) {
  if (reduced) return 'none';
  return `transform ${durationMs}ms ${MOTION.ease}, opacity ${durationMs}ms ${MOTION.ease}`;
}

export function motionStyle({ reduced = false, opacity = '1', transform = 'none', durationMs = MOTION.ms } = {}) {
  return {
    transform: reduced ? 'none' : transform,
    opacity: String(opacity),
    transition: transitionValue(reduced, durationMs),
  };
}

export function transitionUsesOnlyTransformAndOpacity(transition) {
  const value = String(transition || 'none');
  if (value === 'none') return true;
  const parts = value.split(/,(?![^()]*\))/);
  return parts.every(part => ALLOWED.has(part.trim().split(/\s+/)[0]));
}
