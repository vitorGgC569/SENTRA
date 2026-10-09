import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { api, route } from './api';

// Owns terminal VIEWs, never starts, closes or reconnects a backend PTY.
// A stable (workspace, terminal ID) has exactly one xterm and input writer.
export class TerminalPool {
  entries = new Map();
  activeWorkspace = null;
  constructor(report, changed) { this.report = report; this.changed = changed; }
  key(ws, id) { return ws + ':' + id; }
  ensure(ws, resource) {
    const key = this.key(ws, resource.id);
    let entry = this.entries.get(key);
    if (entry) {
      const running = resource.status === 'running' && entry.recoverable !== false;
      entry.term.options.disableStdin = !running || entry.transportUnavailable === true;
      entry.resource = resource;
      return entry;
    }
    const host = document.createElement('div');
    host.className = 'pty-emulator';
    const term = new Terminal({
      fontFamily: '"Cascadia Mono", Consolas, monospace', fontSize: 13,
      scrollback: 6000, screenReaderMode: true, allowProposedApi: false,
      disableStdin: resource.status !== 'running', cursorBlink: false,
      theme: { background: '#1b1b1e', foreground: '#d4d4d8', cursor: '#d4d4d8',
        selectionBackground: '#51515b99' },
    });
    const fit = new FitAddon(); term.loadAddon(fit);
    entry = { key, ws, id: resource.id, resource, host, term, fit,
      cursor: 0, slots: new Map(), queue: Promise.resolve(), opened: false,
      polling: false, status: resource.status, alive: true, retry: 0 };
    this.entries.set(key, entry);
    term.onData(data => this.send(entry, data));
    entry.observer = new ResizeObserver(() => this.scheduleFit(entry));
    entry.observer.observe(host);
    this.poll(entry);
    return entry;
  }
  attach(ws, resource, slot, priority = 1) {
    const entry = this.ensure(ws, resource);
    entry.slots.set(slot, priority); this.place(entry);
    return () => { entry.slots.delete(slot); this.place(entry); };
  }
  place(entry) {
    const slot = [...entry.slots.entries()].filter(([el]) => el.isConnected)
      .sort((a, b) => b[1] - a[1])[0]?.[0];
    if (!slot) { entry.host.remove(); return; }
    if (entry.host.parentElement !== slot) slot.append(entry.host);
    if (!entry.opened) { entry.term.open(entry.host); entry.opened = true; }
    this.scheduleFit(entry);
  }
  scheduleFit(entry) {
    clearTimeout(entry.resizeTimer);
    entry.resizeTimer = setTimeout(() => {
      if (!entry.opened || !entry.host.isConnected || !entry.host.clientHeight) return;
      const dims = entry.fit.proposeDimensions(); if (!dims) return;
      const cols = Math.max(20, Math.min(500, dims.cols));
      const rows = Math.max(5, Math.min(200, dims.rows));
      const changed = entry.term.cols !== cols || entry.term.rows !== rows;
      if (!changed && !entry.needsServerResize) return;
      if (changed) { entry.term.resize(cols, rows); entry.needsServerResize = true; }
      if (!entry.term.options.disableStdin) {
        // Geometry only; no input is reissued and no PTY is relaunched.
        entry.queue = entry.queue.catch(() => {}).then(() => api('/api/terminal/resize',
          { ws: entry.ws, id: entry.id, cols, rows })).then(() => {
            entry.needsServerResize = false;
          }).catch(e => { entry.needsServerResize = true; this.report(e.message, 'error'); });
      }
    }, 120);
  }
  send(entry, data) {
    if (!entry.alive || entry.term.options.disableStdin) return;
    entry.queue = entry.queue.catch(() => {}).then(async () => {
      const characters = Array.from(data);
      for (let offset = 0; offset < characters.length; offset += 1024) {
        if (!entry.alive) return;
        await api('/api/terminal/input', { ws: entry.ws, id: entry.id,
          data: characters.slice(offset, offset + 1024).join('') });
      }
    }).catch(e => this.report(e.message, 'error'));
  }
  focus(ws, id) { this.entries.get(this.key(ws, id))?.term.focus(); }
  command(ws, id, text) {
    const entry = this.entries.get(this.key(ws, id));
    if (entry) this.send(entry, text + '\r');
  }
  state(ws, id) {
    const e = this.entries.get(this.key(ws, id));
    return e ? { status: e.status, recoverable: e.recoverable, persisted: e.persisted,
      transportUnavailable: e.transportUnavailable } : null;
  }
  reconcile(ws, resources) {
    this.activeWorkspace = ws;
    const present = new Set(resources.map(r => r.id));
    for (const r of resources) this.ensure(ws, r);
    for (const [key, e] of this.entries) {
      if (e.ws === ws && !present.has(e.id)) { this.dispose(e); this.entries.delete(key); }
    }
  }
  async poll(entry) {
    if (!entry.alive) return;
    if (entry.ws !== this.activeWorkspace || document.hidden) {
      entry.timer = setTimeout(() => this.poll(entry), 900); return;
    }
    try {
      const value = await api(route('/api/terminal/output', {
        ws: entry.ws, id: entry.id, cursor: String(entry.cursor),
      }));
      if (!entry.alive) return;
      if (value.text) {
        if (value.truncated) entry.term.reset();
        await new Promise(resolve => entry.term.write(value.text, resolve));
      }
      if (value.cursor !== undefined) entry.cursor = value.cursor;
      const change = entry.transportUnavailable || entry.status !== value.status || entry.recoverable !== value.recoverable ||
        entry.persisted !== value.persisted;
      entry.status = value.status; entry.recoverable = value.recoverable;
      entry.persisted = value.persisted; entry.retry = 0; entry.transportUnavailable = false;
      entry.term.options.disableStdin = value.status !== 'running' || value.recoverable === false;
      if (entry.needsServerResize && !entry.term.options.disableStdin) this.scheduleFit(entry);
      if (value.persisted === false && !entry.warned) {
        entry.warned = true; this.report('O histórico da sessão não está sendo salvo.', 'error');
      }
      if (change) this.changed();
    } catch (e) {
      entry.retry++;
      if (entry.retry === 1) this.report(e.message, 'error');
      if (!entry.transportUnavailable) { entry.transportUnavailable = true; this.changed(); }
      entry.term.options.disableStdin = true;
      // Loss of transport is not a successful or ready process state.
    } finally {
      if (entry.alive) entry.timer = setTimeout(() => this.poll(entry),
        entry.retry ? Math.min(8000, 700 * 2 ** Math.min(entry.retry, 4)) : 220);
    }
  }
  dispose(entry) {
    entry.alive = false; clearTimeout(entry.timer); clearTimeout(entry.resizeTimer);
    entry.observer.disconnect(); entry.term.dispose(); entry.host.remove();
  }
  destroy() { for (const e of this.entries.values()) this.dispose(e); this.entries.clear(); }
}
