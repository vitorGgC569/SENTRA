import { useEffect, useRef, useState } from 'react';

// Presentation delay only. Requests remain in the durable/session reconciliation
// path immediately; a fast ordinary acknowledgement need not flash a warning.
export function usePendingPresentation(pending, delayMs = 700) {
  const [visible, setVisible] = useState(pending);
  const initial = useRef(true);
  useEffect(() => {
    if (initial.current) { initial.current = false; return; }
    const keys = new Set(pending.map(value => value.project_id + ':' + value.request_key));
    setVisible(old => old.filter(value => keys.has(value.project_id + ':' + value.request_key)));
    const timer = setTimeout(() => setVisible(pending), delayMs);
    return () => clearTimeout(timer);
  }, [pending, delayMs]);
  return visible;
}
