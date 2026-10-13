'use strict';
// Staged product-update display policy (Vitra-owned, descriptive only).
// The display never applies updates itself. The verified package is applied
// by the host on app exit, never by interrupting live ConPTY sessions; on
// any failure the installed version keeps running and rollback is explicit.
function stagedUpdatePolicy() {
  return {
    schema: 1,
    applyOn: 'app_exit',
    conptyPolicy: 'never_interrupt_live_sessions',
    failurePolicy: 'remain_on_functional_version_and_allow_rollback',
    authority: 'existing_canvas_broker',
  };
}
function shouldDeferUpdate(aliveConptyHandles) {
  if (!Array.isArray(aliveConptyHandles)) throw Error('ConPTY handle list required');
  return aliveConptyHandles.length > 0;
}
module.exports = { stagedUpdatePolicy, shouldDeferUpdate };
