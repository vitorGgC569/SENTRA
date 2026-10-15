import { canvasPhase } from './shell-canvas-state.js';

/** One period of stroke-dasharray "4 6" advances every 700ms while a Dot is working. */
export const WORKING_DASH_PERIOD_SECONDS = 0.7;

export function workingDashOffset(seconds) {
  const value = Number.isFinite(seconds) ? seconds : 0;
  return String(Math.round(value * (10 / WORKING_DASH_PERIOD_SECONDS) * 1000) / 1000);
}

const WORK_EXECUTING = new Set(['RUNNING', 'DISPATCHED']);
const OPERATION_EXECUTING = new Set(['RUNNING', 'PENDING', 'RESERVED']);

/** Working motion requires host proof. Lifecycle `active` and a bare status are not proof. */
export function validatedExecutionIsWorking(execution) {
  if (!execution || execution.validated !== true) return false;
  const work = String(execution.workItemState || execution.work_item_state || '').toUpperCase();
  const operation = String(execution.operationState || execution.operation_state || '').toUpperCase();
  if (!WORK_EXECUTING.has(work) && !OPERATION_EXECUTING.has(operation)) return false;
  return canvasPhase({ workItemState: work, operationState: operation }) === 'executing';
}

export function mascotMotionState(status, execution) {
  if (validatedExecutionIsWorking(execution)) return 'working';
  const value = String(status || 'idle').toLowerCase();
  if (['waiting_approval', 'waiting_chatgpt_user_approval', 'needs_input', 'uncertain'].includes(value)) return 'needs-input';
  if (['paused', 'stopped', 'interrupted', 'cancelled'].includes(value)) return 'paused';
  if (['completed', 'succeeded'].includes(value)) return 'complete';
  return 'idle';
}

/** Presentation of a Dot SVG copy. The source markup string is never rewritten. */

export function presentDot(markup, { time = 0, interaction = 'idle' } = {}) {
  if (typeof markup !== 'string' || !markup.includes('id="dot-original"')) {
    throw new Error('a Dot SVG copy is required');
  }
  const seconds = Number.isFinite(time) ? time : 0;
  const mode = interaction === 'press' || interaction === 'hover' ? interaction : 'idle';
  const bob = mode === 'press' ? 2 : Math.sin(seconds) * 3;
  const opacity = mode === 'hover' ? 0.86 : 1;
  const dash = mode === 'press' ? 6 : Math.round(seconds * 8000) / 1000;
  return {
    markup,
    presentation: {
      transform: `translate(0 ${bob.toFixed(3)})`,
      opacity: String(opacity),
      strokeDashoffset: String(dash),
    },
  };
}

/** Paint a display string. Only the dot-motion group changes; the caller's markup stays intact. */
export function paintCopy(markup, presentation) {
  const source = String(markup);
  return source.replace(/<g\b[^>]*\bid="dot-motion"[^>]*>/, (tag) => tag
    .replace(/stroke-dashoffset="[^"]*"/, `stroke-dashoffset="${presentation.strokeDashoffset}"`)
    .replace(/opacity="[^"]*"/, `opacity="${presentation.opacity}"`)
    .replace(/transform="[^"]*"/, `transform="${presentation.transform}"`));
}
