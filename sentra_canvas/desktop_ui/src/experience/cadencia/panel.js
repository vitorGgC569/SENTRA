import { transitionValue } from './motion.js';

export function panelStyle({ open = false, reduced = false, edge = 'right' } = {}) {
  const side = edge === 'left' ? 'left' : 'right';
  const travel = !open && !reduced;
  const offset = side === 'left' ? '-12px' : '12px';
  return {
    open: Boolean(open),
    edge: side,
    reduced: Boolean(reduced),
    transform: travel ? `translateX(${offset})` : 'none',
    opacity: open ? '1' : '0',
    transition: transitionValue(reduced, 200),
    pointerEvents: open ? 'auto' : 'none',
    ariaHidden: !open,
  };
}
