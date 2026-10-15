// Browser UI deadline is not cancellation of the native operation.
// A timed-out update becomes UNKNOWN; the same button must never resubmit it.
export function createUpdateDeadline({schedule = setTimeout, cancel = clearTimeout, timeoutMs = 45000, onTimeout}) {
  let timer = null;
  return {
    arm() {
      if (timer != null) cancel(timer);
      timer = schedule(() => {
        timer = null;
        onTimeout();
      }, timeoutMs);
    },
    disarm() {
      if (timer != null) cancel(timer);
      timer = null;
    },
    isArmed() { return timer != null; },
  };
}
