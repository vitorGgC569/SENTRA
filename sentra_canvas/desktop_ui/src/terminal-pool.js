import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { api, route } from './api';
import { shouldPollTerminalOutput, terminalReconcileAction } from './shell-terminal-gate.js';
import { resetForOutput } from './terminal-history-state';
import {restoreCheckpoint,mayWriteTerminal,writeTerminalFrame,releaseDisposedWrites} from './terminal-checkpoint';
import {Unicode11Addon} from '@xterm/addon-unicode11';
import {activateOrcaTerminalUnicodeProvider} from '../../../integrations/orca-terminal/vendor/orca/src/shared/terminal-unicode-provider';
import {TerminalReadBudget} from '../../../integrations/orca-terminal/src/consumer-flow.mjs';

// Owns terminal VIEWs, never starts, closes or reconnects a backend PTY.
// A stable (workspace, terminal ID) has exactly one xterm and input writer.
// Output stays off until the Canvas surface is active. Suspension keeps entries.
export class TerminalPool {
  entries = new Map();
  activeWorkspace = null;
  outputEnabled = false;
  heldWorkspace = null;
  heldResources = null;
  listeners = new Set();
  revision = 0;
  subscribe = listener => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  snapshot = () => this.revision;
  constructor(report, changed) {
    this.readBudget = new TerminalReadBudget();
    this.onVisibility=()=>{for(const entry of this.entries.values()){
      if(!this.visible(entry))this.suspend(entry);
      else if(!entry.polling&&!entry.timer)this.poll(entry);
    }};
    document.addEventListener('visibilitychange',this.onVisibility);
    this.report = report;
    this.changed = () => { this.revision++; changed(); for (const listener of this.listeners) listener(); };
  }
  visible(entry) {
    return this.outputEnabled && entry.alive && entry.ws === this.activeWorkspace && !document.hidden &&
      entry.inViewport && entry.host.isConnected && entry.host.clientHeight > 0 && entry.host.clientWidth > 0;
  }
  suspend(entry) {
    if(entry.pendingWrites?.size){entry.renderUncertain=true;entry.snapshotRestored=false;entry.checkpointUnavailable=false;}
    entry.viewEpoch = (entry.viewEpoch || 0) + 1; entry.inputEpoch++;
    entry.inputSuspended = true; entry.term.options.disableStdin = true;
    entry.readAbort?.abort();clearTimeout(entry.timer);entry.timer = null;
  }
  setOutputEnabled(enabled) {
    const next = enabled === true;
    this.outputEnabled = next;
    if (!next) {
      for (const entry of this.entries.values()) {
        this.suspend(entry);
        clearTimeout(entry.timer);
        clearTimeout(entry.resizeTimer);
        entry.timer = null;
      }
      return;
    }
    if (this.heldResources && this.heldWorkspace) {
      const ws = this.heldWorkspace;
      const resources = this.heldResources;
      this.heldResources = null;
      this.reconcile(ws, resources);
    }
    for (const entry of this.entries.values()) {
      if (entry.alive && !entry.polling && !entry.timer) this.poll(entry);
    }
  }
  key(ws, id) { return ws + ':' + id; }
  ensure(ws, resource) {
    const key = this.key(ws, resource.id);
    let entry = this.entries.get(key);
    if (entry) {
      const running = resource.status === 'running' && entry.recoverable !== false;
      entry.term.options.disableStdin = !running || entry.transportUnavailable === true || entry.inputSuspended === true;
      entry.resource = resource;
      if (!this.visible(entry)) this.suspend(entry);
      return entry;
    }
    const host = document.createElement('div');
    host.className = 'pty-emulator';
    const term = new Terminal({
      fontFamily: '"Cascadia Mono", Consolas, monospace', fontSize: 13,
      scrollback: 6000, screenReaderMode: true, allowProposedApi: true,vtExtensions:{kittyKeyboard:true},
      disableStdin: resource.status !== 'running', cursorBlink: false,
      theme: { background: '#1b1b1e', foreground: '#d4d4d8', cursor: '#d4d4d8',
        selectionBackground: '#51515b99' },
    });
    const fit = new FitAddon(); term.loadAddon(fit);
    term.loadAddon(new Unicode11Addon());activateOrcaTerminalUnicodeProvider(term);
    entry = { key, ws, id: resource.id, resource, host, term, fit,
      cursor: 0, slots: new Map(), queue: Promise.resolve(), opened: false,
      polling: false, status: resource.status, alive: true, retry: 0,inputEpoch:0,viewEpoch:0,inputSuspended:true,
      inViewport:typeof IntersectionObserver!=='function' };
    this.entries.set(key, entry);
    term.onData(data => this.send(entry, data));
    entry.observer = new ResizeObserver(() => {
      if(!this.visible(entry)){this.suspend(entry);return;}
      this.scheduleFit(entry);if(!entry.polling&&!entry.timer)this.poll(entry);
    });
    entry.observer.observe(host);
    if(typeof IntersectionObserver==='function'){
      entry.intersection=new IntersectionObserver(rows=>{
        entry.inViewport=rows.some(row=>row.target===host&&row.isIntersecting);
        if(!this.visible(entry))this.suspend(entry);
        else{this.scheduleFit(entry);if(!entry.polling&&!entry.timer)this.poll(entry);}
      });entry.intersection.observe(host);
    }
    if (this.outputEnabled) this.poll(entry);
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
    if (!slot) { this.suspend(entry);entry.host.remove(); return; }
    if (entry.host.parentElement !== slot) slot.append(entry.host);
    if (!entry.opened) { entry.term.open(entry.host); entry.opened = true; }
    this.scheduleFit(entry);
    if(this.visible(entry)&&!entry.polling&&!entry.timer)this.poll(entry);
  }
  scheduleFit(entry) {
    clearTimeout(entry.resizeTimer);
    entry.resizeTimer = setTimeout(() => {
      if (!entry.opened || !this.visible(entry)) return;
      if(entry.replaying||entry.status==='history_restored')return;
      const dims = entry.fit.proposeDimensions(); if (!dims) return;
      const cols = Math.max(20, Math.min(500, dims.cols));
      const rows = Math.max(5, Math.min(200, dims.rows));
      const changed = entry.term.cols !== cols || entry.term.rows !== rows;
      if (!changed && !entry.needsServerResize) return;
      if (changed) { entry.term.resize(cols, rows); entry.needsServerResize = true; }
      if (!entry.term.options.disableStdin) {
        // Geometry only; no input is reissued and no PTY is relaunched.
        const epoch=entry.inputEpoch;
        entry.queue = entry.queue.catch(() => {}).then(() => {
          if(!this.visible(entry)||entry.inputEpoch!==epoch)return;
          return api('/api/terminal/resize',{ ws: entry.ws, id: entry.id, cols, rows });
        }).then(() => {
            if(!this.visible(entry)||entry.inputEpoch!==epoch)return;
            entry.needsServerResize = false;
          }).catch(e => { if(!entry.alive||entry.inputEpoch!==epoch)return;entry.needsServerResize = true; this.report(e.message, 'error'); });
      }
    }, 120);
  }
  send(entry, data) {
    if (!this.visible(entry) || !mayWriteTerminal(entry)) return;
    const epoch=entry.inputEpoch;
    entry.queue = entry.queue.catch(() => {}).then(async () => {
      const characters = Array.from(data);
      for (let offset = 0; offset < characters.length; offset += 1024) {
        if (!this.visible(entry)||!mayWriteTerminal(entry,epoch)) return;
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
      transportUnavailable: e.transportUnavailable, persistenceState: e.persistenceState,
      persistenceGap: e.persistenceGap, tailUncertain: e.tailUncertain,checkpointUnavailable:e.checkpointUnavailable,
      scrollbackOmitted:e.scrollbackOmitted } : null;
  }
  reconcile(ws, resources) {
    this.activeWorkspace = ws;
    for(const entry of this.entries.values())if(entry.ws!==ws)this.suspend(entry);
    if (terminalReconcileAction(this.outputEnabled) === 'hold') {
      this.heldWorkspace = ws;
      this.heldResources = resources;
      return;
    }
    this.heldResources = null;
    this.heldWorkspace = ws;
    const present = new Set(resources.map(r => r.id));
    for (const r of resources) this.ensure(ws, r);
    for (const [key, e] of this.entries) {
      if (e.ws === ws && !present.has(e.id)) { this.dispose(e); this.entries.delete(key); }
    }
  }
  async poll(entry) {
    if (!entry.alive || entry.polling) return;
    const allowed = this.visible(entry) && shouldPollTerminalOutput({
      outputEnabled: this.outputEnabled, alive: entry.alive, workspace: entry.ws,
      activeWorkspace: this.activeWorkspace, hidden: document.hidden,
    });
    if (!allowed) {
      if (!this.outputEnabled) return;
      this.suspend(entry);return;
    }
    entry.polling = true;
    clearTimeout(entry.timer);
    entry.timer = null;
    const generation=entry.viewEpoch,controller=new AbortController();entry.readAbort=controller;
    const current=()=>entry.alive&&entry.viewEpoch===generation&&this.visible(entry)&&!controller.signal.aborted;
    let release,catchingUp=false;
    try {
      release=await this.readBudget.acquire(entry.key,controller.signal);
      if(!current())return;
      const value = await api(route('/api/terminal/output', {
        ws: entry.ws, id: entry.id, cursor: String(entry.cursor),
      }),undefined,{signal:controller.signal});
      if (!current()) return;
      if(typeof value.text!=='string'||value.text.length>32000||new TextEncoder().encode(value.text).length>64000||
          !Number.isSafeInteger(value.cursor)||value.cursor<0||value.cursor>10**12)throw Error('Frame de terminal incompatível.');
      if(value.checkpoint_supported&&!entry.checkpointUnavailable&&(!entry.snapshotRestored||value.truncated||value.geometry_sequence!==entry.geometrySequence)){
        const checkpoint=await api(route('/api/terminal/checkpoint',{ws:entry.ws,id:entry.id}),undefined,{signal:controller.signal});
        if(!current())return;
        if(checkpoint.available){if(await restoreCheckpoint(entry,checkpoint,current))this.changed();return;}
        if(checkpoint.retryable){entry.term.options.disableStdin=true;return;}
        entry.checkpointUnavailable=true;
      }
      if(entry.renderUncertain){entry.term.reset();entry.renderUncertain=false;entry.checkpointUnavailable=true;}
      if (resetForOutput(value,entry.cursor)) entry.term.reset();
      if (value.text) {
        await writeTerminalFrame(entry,value.text,current);
      }
      if(!current())return;
      if (value.cursor !== undefined) entry.cursor = value.cursor;
      catchingUp=value.has_more===true&&value.text.length>0;
      const change = entry.transportUnavailable || entry.status !== value.status || entry.recoverable !== value.recoverable ||
        entry.persisted !== value.persisted || entry.persistenceState !== value.persistence_state ||
        entry.persistenceGap !== !!(value.persistence_gap||value.truncated);
      entry.status = value.status; entry.recoverable = value.recoverable;
      entry.persisted = value.persisted; entry.retry = 0; entry.transportUnavailable = false;
      entry.persistenceState = value.persistence_state;
      entry.persistenceGap = !!(value.persistence_gap||value.truncated);
      entry.tailUncertain = value.tail_uncertain === true;
      entry.inputSuspended = false;
      entry.term.options.disableStdin = value.status !== 'running' || value.recoverable === false;
      if (entry.needsServerResize && !entry.term.options.disableStdin) this.scheduleFit(entry);
      if (value.persisted === false && (!value.persistence_state || value.persistence_state === 'failed') && !entry.warned) {
        entry.warned = true; this.report('O histórico da sessão não está sendo salvo.', 'error');
      }
      if (entry.persistenceGap && !entry.warnedGap) {
        entry.warnedGap = true;
        this.report('Parte do histórico de '+entry.resource.name+' não está disponível. O processo não foi recriado.', 'error');
      }
      if (change) this.changed();
    } catch (e) {
      if (!current()) return;
      entry.retry++;
      if (entry.retry === 1) this.report(e.message, 'error');
      if (!entry.transportUnavailable) { entry.transportUnavailable = true; this.changed(); }
      entry.inputEpoch++;
      entry.checkpointUnavailable=false;entry.snapshotRestored=false;
      entry.term.options.disableStdin = true;
      // Loss of transport is not a successful or ready process state.
    } finally {
      release?.();if(entry.readAbort===controller)entry.readAbort=null;
      entry.polling = false;
      if (this.visible(entry)) entry.timer = setTimeout(() => this.poll(entry),
        entry.retry ? Math.min(8000, 700 * 2 ** Math.min(entry.retry, 4)) : catchingUp ? 0 : 220);
    }
  }
  dispose(entry) {
    this.suspend(entry);entry.alive = false; clearTimeout(entry.timer); clearTimeout(entry.resizeTimer);
    entry.observer.disconnect();entry.intersection?.disconnect();entry.term.dispose(); entry.host.remove();
    releaseDisposedWrites(entry);
  }
  destroy() { document.removeEventListener('visibilitychange',this.onVisibility);for (const e of this.entries.values()) this.dispose(e); this.entries.clear(); }
}
