import { MOTION, transitionValue } from './motion.js';

/** Visible shell order. Home is a real view even though workSurface() does not store it. */
export const SURFACE_ORDER = ['home', 'conversations', 'dots', 'spaces', 'space', 'chat', 'documents', 'canvas'];

export function surfaceShift(fromView, toView, { reduced = false } = {}) {
  if (!SURFACE_ORDER.includes(toView)) return null;
  const from = SURFACE_ORDER.indexOf(fromView);
  const to = SURFACE_ORDER.indexOf(toView);
  const dir = from < 0 || from === to ? 'none' : (to > from ? 'forward' : 'back');
  return {
    view: toView,
    dir,
    reduced: Boolean(reduced),
    style: {
      transform: 'none',
      opacity: '1',
      transition: transitionValue(reduced, MOTION.ms),
      animation: reduced || dir === 'none' ? 'none' : `cadence-enter-${dir} ${MOTION.ms}ms ${MOTION.ease}`,
    },
  };
}

/** Public surface contract: 200ms, no bounce, compact home rows at max-content. */
export function SurfaceMotion({ reduced = false, from = 'home', to = 'home' } = {}) {
  const shift = surfaceShift(from, to, { reduced }) || {
    view: null, dir: 'none', reduced: Boolean(reduced),
    style: { transform: 'none', opacity: '1', transition: 'none', animation: 'none' },
  };
  return {
    ms: MOTION.ms,
    ease: MOTION.ease,
    reduced: Boolean(reduced),
    view: shift.view,
    dir: shift.dir,
    transition: shift.style.transition,
    animation: shift.style.animation,
    transform: 'none',
    opacity: '1',
    list: {
      height: 'max-content',
      gridAutoRows: 'max-content',
      alignContent: 'start',
      alignItems: 'start',
    },
    row: {
      height: 'max-content',
      maxHeight: 'max-content',
      alignSelf: 'start',
      flexGrow: 0,
    },
  };
}
