import { api, apiStream, route } from './api.js';
import { ProjectFeed } from './shell-stream-transport.js';

const projects = new Map();

// Sharing occurs at window/project scope, never across account/project scopes.
export function subscribeShellStream(scope, observer) {
  try { if (localStorage.getItem('sentra_shell_stream') === 'off') { observer.onState?.('unavailable'); return () => {}; } }
  catch { /* The server remains authoritative if preference storage is unavailable. */ }
  let record = projects.get(scope.project_id);
  if (!record) {
    record = { users: 0, timer: null, feed: new ProjectFeed({
      open: (after, signal, epoch) => apiStream(scope.project_id, { after, signal, epoch }),
      readHead: (fields, options) => api(route('/api/shell/stream/head', fields), undefined, options),
    }) };
    record.resume = () => record.feed.resume();
    record.visible = () => { if (document.visibilityState === 'visible') record.resume(); };
    window.addEventListener('online', record.resume);
    window.addEventListener('pageshow', record.resume);
    document.addEventListener('visibilitychange', record.visible);
    projects.set(scope.project_id, record);
  }
  clearTimeout(record.timer); record.users++;
  const unsubscribe = record.feed.subscribe(scope, observer);
  return () => {
    unsubscribe(); record.users--;
    if (!record.users) record.timer = setTimeout(() => {
      window.removeEventListener('online', record.resume);
      window.removeEventListener('pageshow', record.resume);
      document.removeEventListener('visibilitychange', record.visible);
      record.feed.close(); projects.delete(scope.project_id);
    }, 1000);
  };
}
