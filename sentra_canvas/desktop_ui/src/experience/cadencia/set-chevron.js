import { MOTION } from './motion.js';

/** Collapsed-set chevron. It rotates in place. It never travels on Y. */

export function setChevron({ open = false, reduced = false } = {}) {
  return {
    open: Boolean(open),
    reduced: Boolean(reduced),
    size: 16,
    offset: 16,
    transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
    transition: reduced ? 'none' : `transform ${MOTION.ms}ms ${MOTION.ease}`,
  };
}
