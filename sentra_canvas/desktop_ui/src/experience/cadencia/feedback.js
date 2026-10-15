import { explainFailure } from '../../shell-failure.js';
import { motionStyle } from './motion.js';

export function feedbackMotion(input, { reduced = false } = {}) {
  const copy = explainFailure(input);
  const rest = motionStyle({ reduced, opacity: '1', transform: 'none' });
  return {
    headline: copy.headline,
    happened: copy.happened,
    safeNext: copy.safeNext,
    resend: false,
    role: 'alert',
    reduced: Boolean(reduced),
    style: rest,
    enterFrom: reduced ? rest : motionStyle({ reduced: false, opacity: '0', transform: 'translateY(-6px)' }),
  };
}
