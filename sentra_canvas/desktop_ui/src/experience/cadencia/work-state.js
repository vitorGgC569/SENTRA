import { PHASES, canvasPhase, phaseCopy, taskPresentation } from '../../shell-canvas-state.js';
import { transitionValue } from './motion.js';

export { PHASES };

export function workMotion(input = {}, { reduced = false } = {}) {
  const phase = canvasPhase(input);
  const copy = phaseCopy(phase);
  return {
    phase,
    label: copy.label,
    meaning: copy.meaning,
    safeNext: copy.safeNext,
    resend: false,
    reduced: Boolean(reduced),
    style: {
      transform: 'none',
      opacity: '1',
      animation: 'none',
      transition: transitionValue(reduced),
    },
  };
}

export function presentedTask(task = {}, extra = {}, options = {}) {
  const view = taskPresentation(task, extra);
  return {
    ...view,
    resend: false,
    motion: workMotion({
      taskStatus: task.status,
      workItemState: task.work_item_state,
      operationState: task.operation_state,
    }, options),
  };
}
