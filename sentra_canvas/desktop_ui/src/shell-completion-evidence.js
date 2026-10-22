// A delivery receipt identifies an effect; it does not verify task completion.
const VERIFIED = new Set(['verified', 'receipt_verified', 'verified_success']);
const NONFINAL = new Set(['failed', 'error', 'cancelled', 'canceled', 'expired', 'uncertain',
  'unconfirmed', 'unverified', 'blocked', 'waiting_approval', 'waiting_chatgpt_user_approval',
  'needs_input', 'running', 'dispatched', 'starting', 'pending', 'reserved', 'queued',
  'working', 'executing', 'thinking', 'generating', 'interrupted', 'paused', 'stop', 'stopped', 'idle',
  'accepted', 'delivered', 'delivered_to_process', 'sent', 'observed', 'in_progress',
  'confirming', 'sending', 'reasoning', 'preparing', 'requested', 'delivered_to_dot', 'waiting_external']);
export function completionEvidence(value) {
  if (!value || typeof value !== 'object') return false;
  const execution = value.execution || {};
  const states = [value.status, value.state, value.task_lifecycle?.stage, value.lifecycle?.stage,
    execution.stage, execution.state, execution.workItemState, execution.work_item_state,
    execution.operationState, execution.operation_state].filter(Boolean).map(state => String(state).trim().toLowerCase());
  if (states.some(state => NONFINAL.has(state))) return false;
  if (value.task_completion_verified === false || value.verified === false || execution.verified === false) return false;
  return value.task_completion_verified === true || value.verified === true || execution.verified === true ||
    value.verification?.verified === true || value.task_verification?.verified === true ||
    states.some(state => VERIFIED.has(state));
}
