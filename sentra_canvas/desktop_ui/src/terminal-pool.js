import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { api, route } from './api';
import { shouldPollTerminalOutput, terminalReconcileAction } from './shell-terminal-gate.js';
import { resetForOutput } from './terminal-history-state';
import {restoreCheckpoint,mayWriteTerminal,writeTerminalFrame,releaseDisposedWrites} from './terminal-checkpoint';
import {Unicode11Addon} from '@xterm/addon-unicode11';
import {activateOrcaTerminalUnicodeProvider} from '../../../integrations/orca-terminal/vendor/orca/src/shared/terminal-unicode-provider';
import {TerminalReadBudget} from '../../../integrations/orca-terminal/src/consumer-flow.mjs';
import {EmulatorBudget} from '../../../integrations/orca-terminal/src/emulator-budget.mjs';
import {TerminalInputQueue} from '../../../integrations/orca-terminal/src/input-queue.mjs';
import {TerminalInputJournal,deliveredInput} from './terminal-input-journal';

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
    this.emulatorBudget = new EmulatorBudget();
    this.rendererClock=0;
    this.inputQueue = new TerminalInputQueue();
    this.onInputStorage=()=>{for(const entry of this.entries.values())if(entry.inputJournal)void this.syncInput(entry)};
    window.addEventListener('storage',this.onInputStorage);
    this.onVisibility=()=>{for(const entry of this.entries.values()){
      if(!this.visible(entry))this.suspend(entry);
      else {this.place(entry);if(entry.term&&!entry.polling&&!entry.timer)this.poll(entry);}
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
    if(entry.sendingPacket)entry.inputBlocked=entry.inputBlocked||'view_changed';
    this.inputQueue.cancel(entry.key);entry.pendingResize=null;
    entry.inputSuspended = true; if(entry.term)entry.term.options.disableStdin = true;
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
      if(entry.alive){this.place(entry);if(entry.term&&!entry.polling&&!entry.timer)this.poll(entry);}
    }
  }
  key(ws, id) { return ws + ':' + id; }
  reserveRenderer(entry,cols,rows) {
    const reserve=()=>this.emulatorBudget.reserve(entry.key,cols,rows,2000);
    if(reserve())return true;
    const idle=[...this.entries.values()].filter(other=>other!==entry&&other.term&&!this.visible(other))
      .sort((a,b)=>(a.rendererUsed||0)-(b.rendererUsed||0));
    for(const other of idle){this.parkRenderer(other);if(reserve())return true;}
    return false;
  }
  parkRenderer(entry) {
    if(!entry.term)return;
    this.suspend(entry);entry.rendererCols=entry.term.cols;entry.rendererRows=entry.term.rows;
    entry.rendererScroll=entry.term.buffer?.active?.viewportY;entry.rendererWasAtBottom=entry.term.buffer?.active?.viewportY===entry.term.buffer?.active?.baseY;
    entry.term.dispose();releaseDisposedWrites(entry);entry.term=null;entry.fit=null;
    this.emulatorBudget.release(entry.key);entry.host.replaceChildren();entry.opened=false;
    entry.snapshotRestored=false;entry.checkpointUnavailable=false;entry.cursor=0;entry.renderUncertain=true;
  }
  createRenderer(entry) {
    const cols=entry.rendererCols||100,rows=entry.rendererRows||28;
    if(!this.reserveRenderer(entry,cols,rows)){
      const first=!entry.memoryPaused;
      entry.memoryPaused=true;entry.host.textContent='Limite de visualizações atingido. Feche um painel para abrir este terminal. O processo continua.';
      if(first)this.changed();
      return null;
    }
    entry.memoryPaused=false;entry.host.replaceChildren();entry.rendererUsed=++this.rendererClock;
    let term;
    try{term = new Terminal({
      fontFamily: '"Cascadia Mono", Consolas, monospace', fontSize: 13,
      cols,rows,scrollback: 2000, screenReaderMode: true, allowProposedApi: true,vtExtensions:{kittyKeyboard:true},
      disableStdin: true, cursorBlink: false,
      theme: { background: '#1b1b1e', foreground: '#d4d4d8', cursor: '#d4d4d8', selectionBackground: '#51515b99',...entry.viewTheme },
    });
    const fit = new FitAddon(); term.loadAddon(fit);
    term.loadAddon(new Unicode11Addon());activateOrcaTerminalUnicodeProvider(term);
    entry.term=term;entry.fit=fit;
    term.onData(data => this.send(entry, data));
    return term;
    }catch(error){term?.dispose();entry.term=null;entry.fit=null;this.emulatorBudget.release(entry.key);throw error;}
  }
  recoverRenderer(entry) {
    if(!entry.alive)return;
    this.suspend(entry);
    this.parkRenderer(entry);
    entry.snapshotRestored=false;entry.checkpointUnavailable=false;entry.cursor=0;
    entry.transportUnavailable=true;entry.rendererRecoveries=(entry.rendererRecoveries||0)+1;
    this.place(entry);this.changed();
    this.report('A visualização foi reiniciada. O processo e os comandos não foram reiniciados.','error');
  }
  ensure(ws, resource) {
    const key = this.key(ws, resource.id);
    let entry = this.entries.get(key);
    if (entry) {
      const running = resource.status === 'running' && entry.recoverable !== false;
      if(entry.term)entry.term.options.disableStdin = !running || entry.transportUnavailable === true || entry.inputSuspended === true || !!entry.inputBlocked || !entry.inputProtocol;
      entry.resource = resource;
      if (!this.visible(entry)) this.suspend(entry);
      return entry;
    }
    const host = document.createElement('div');
    host.className = 'pty-emulator';
    entry = { key, ws, id: resource.id, resource, host,
      cursor: 0, slots: new Map(), opened: false,
      polling: false, status: resource.status, alive: true, retry: 0,inputEpoch:0,viewEpoch:0,inputSuspended:true,
      inViewport:typeof IntersectionObserver!=='function' };
    this.entries.set(key, entry);
    entry.term=null;entry.onRendererStall=()=>this.recoverRenderer(entry);
    entry.resizeRenderer=(cols,rows)=>{
      if(!this.reserveRenderer(entry,cols,rows)){entry.memoryPaused=true;throw Error('Limite de memória das visualizações atingido. Feche outro painel.');}
      entry.term.resize(cols,rows);entry.rendererCols=cols;entry.rendererRows=rows;entry.memoryPaused=false;
    };
    entry.observer = new ResizeObserver(() => {
      if(!this.visible(entry)){this.suspend(entry);return;}
      if(!entry.term){this.place(entry);return;}
      this.scheduleFit(entry);if(!entry.polling&&!entry.timer)this.poll(entry);
    });
    entry.observer.observe(host);
    if(typeof IntersectionObserver==='function'){
      entry.intersection=new IntersectionObserver(rows=>{
        entry.inViewport=rows.some(row=>row.target===host&&row.isIntersecting);
        if(!this.visible(entry))this.suspend(entry);
        else{this.place(entry);if(entry.term&&!entry.polling&&!entry.timer)this.poll(entry);}
      });entry.intersection.observe(host);
    }
    if (this.outputEnabled) this.poll(entry);
    return entry;
  }
  attach(ws, resource, slot, priority = 1) {
    const entry = this.ensure(ws, resource);
    entry.slots.set(slot, priority); this.place(entry);
    return () => { entry.slots.delete(slot); this.place(entry);this.retryRenderers(); };
  }
  retryRenderers(){for(const candidate of this.entries.values())if(candidate.memoryPaused&&this.visible(candidate))this.place(candidate);}
  place(entry) {
    const slot = [...entry.slots.entries()].filter(([el]) => el.isConnected)
      .sort((a, b) => b[1] - a[1])[0]?.[0];
    if (!slot) { this.suspend(entry);entry.host.remove(); return; }
    if (entry.host.parentElement !== slot) slot.append(entry.host);
    if(!entry.term){if(!this.visible(entry)||!this.createRenderer(entry))return;}
    entry.rendererUsed=++this.rendererClock;
    if (!entry.opened) { entry.term.open(entry.host); entry.opened = true; }
    this.scheduleFit(entry);
    if(this.visible(entry)&&!entry.polling&&!entry.timer)this.poll(entry);
  }
  scheduleFit(entry) {
    clearTimeout(entry.resizeTimer);
    entry.resizeTimer = setTimeout(() => {
      if (!entry.term || !entry.opened || !this.visible(entry)) return;
      if(entry.replaying||entry.status==='history_restored')return;
      const dims = entry.fit.proposeDimensions(); if (!dims) return;
      const cols = Math.max(20, Math.min(500, dims.cols));
      const rows = Math.max(5, Math.min(200, dims.rows));
      const changed = entry.term.cols !== cols || entry.term.rows !== rows;
      if (!changed && !entry.needsServerResize) return;
      if (changed) {
        try{entry.resizeRenderer(cols,rows);entry.memoryPaused=false;}
        catch(error){entry.memoryPaused=true;this.report(error.message,'error');this.changed();return;}
        entry.needsServerResize = true;
      }
      if (!entry.term.options.disableStdin) {
        entry.pendingResize={cols,rows};this.queueResize(entry);
      }
    }, 120);
  }
  queueResize(entry){
    if(entry.resizeQueued||!entry.pendingResize||!this.visible(entry)||!mayWriteTerminal(entry))return;
    entry.resizeQueued=true;const epoch=entry.inputEpoch;
    try{
      this.inputQueue.enqueue(entry.key,'resize',async()=>{
        if(!this.visible(entry)||!mayWriteTerminal(entry,epoch))return;
        const size=entry.pendingResize;entry.pendingResize=null;if(!size)return;
        await this.inputRequest('/api/terminal/resize',{ws:entry.ws,id:entry.id,...size});
        if(this.visible(entry)&&entry.inputEpoch===epoch)entry.needsServerResize=false;
      }).catch(error=>{if(entry.alive&&entry.inputEpoch===epoch){this.blockInput(entry,'geometry_unconfirmed');this.report(error.message,'error')}})
        .finally(()=>{entry.resizeQueued=false;if(entry.pendingResize)this.queueResize(entry)});
    }catch(error){entry.resizeQueued=false;this.blockInput(entry,'queue_limit');}
  }
  blockInput(entry,reason){
    entry.inputBlocked=reason;entry.inputEpoch++;if(entry.term)entry.term.options.disableStdin=true;
    this.inputQueue.cancel(entry.key);entry.pendingResize=null;this.changed();
  }
  async syncInput(entry,value){
    try{
      if(value){
        if(entry.inputScope&&value.input_scope&&entry.inputScope!==value.input_scope){this.blockInput(entry,'scope_changed');return;}
        if(entry.inputTarget&&entry.inputTarget!==value.input_target){
          if(this.inputQueue.status(entry.key).sessionCount)this.blockInput(entry,'target_changed');
          else entry.inputEpoch++;
        }
        entry.inputProtocol=value.input_protocol_version===1&&/^[0-9a-f]{64}$/.test(value.input_scope||'')&&/^[0-9a-f]{32}$/.test(value.input_target||'');
        entry.inputTarget=value.input_target;
        if(!entry.inputProtocol){if(entry.term)entry.term.options.disableStdin=true;entry.inputEpoch++;this.inputQueue.cancel(entry.key)}
        if(/^[0-9a-f]{64}$/.test(value.input_scope||'')&&entry.inputScope!==value.input_scope){entry.inputScope=value.input_scope;entry.inputJournal=new TerminalInputJournal(value.input_scope,entry.id)}
        if(entry.inputProtocol&&!entry.inputJournal?.locks?.request)throw Error('Este ambiente não permite coordenar a entrada entre janelas.');
        if(value.input_pending!==undefined){
          const accepted=await entry.inputJournal.adoptMany(value.input_pending,{revision:value.input_pending_revision,epoch:value.input_pending_epoch});
          if(accepted){entry.inputPendingOverflow=value.input_pending_overflow===true;if(entry.inputPendingOverflow)this.blockInput(entry,'confirmation_overflow');}
        }
      }
      this.projectInputRows(entry);entry.inputJournalError=null;
    }catch(error){entry.inputJournalError=error.message;this.blockInput(entry,'journal_unavailable')}
  }
  projectInputRows(entry){
    const rows=entry.inputJournal?.list()||[],previous=JSON.stringify(entry.inputPendings||[]);
    entry.inputPendings=rows;entry.inputPending=rows[0]||null;
    if(rows.some(row=>row.request_key!==entry.activeRequestKey)&&!entry.inputBlocked)this.blockInput(entry,'confirmation_pending');
    if(previous!==JSON.stringify(rows))this.changed();
  }
  send(entry, data) {
    if (!this.visible(entry) || !entry.inputProtocol || !mayWriteTerminal(entry)) return;
    const epoch=entry.inputEpoch;
    try{
      return this.inputQueue.enqueue(entry.key,data,packet=>entry.inputJournal.writer(async()=>{
        if(!this.visible(entry)||!mayWriteTerminal(entry,epoch))return {cancelled:true};
        entry.sendingPacket=true;
        try{
        const characters=Array.from(packet);
        for(let offset=0;offset<characters.length;offset+=1024){
          if(!this.visible(entry)||!mayWriteTerminal(entry,epoch))return {cancelled:true};
          const part=characters.slice(offset,offset+1024).join(''),key=crypto.randomUUID();
          entry.activeRequestKey=key;
          try{
            const row=await entry.inputJournal.begin(key,entry.inputTarget,part);this.projectInputRows(entry);
            if(!this.visible(entry)||!mayWriteTerminal(entry,epoch)){
              // This branch proves the HTTP call was never made. After dispatch
              // only a host receipt can clear the selector.
              await entry.inputJournal.cancelBeforeDispatch(row);this.projectInputRows(entry);return {cancelled:true};
            }
            const value=await this.inputRequest('/api/terminal/input',{ws:entry.ws,id:entry.id,data:part,request_key:key,input_target:row.input_target});
            if(!deliveredInput(value,row,entry.id))throw Error('Entrega ao terminal não confirmada.');
            const ack=await this.acknowledgeInput(entry,row);
            await entry.inputJournal.resolve(row,{resolved:true,automatic_retry:false,request_key:key,input_target:row.input_target,input_pending_revision:ack.input_pending_revision,input_pending_epoch:ack.input_pending_epoch});
            this.projectInputRows(entry);
          }finally{entry.activeRequestKey=null}
        }
        }finally{entry.sendingPacket=false;this.changed()}
      })).catch(async error=>{
        if(!entry.alive)return;
        await this.syncInput(entry);this.blockInput(entry,'confirmation_pending');this.report('Entrada interrompida. Consulte a confirmação antes de continuar.','error');
      });
    }catch(error){
      this.blockInput(entry,'queue_limit');this.report('Fila de entrada cheia ou texto acima do limite. Confira a sessão antes de continuar.','error');
    }
  }
  async inputRequest(path,body){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
    try{return await api(path,body,{signal:controller.signal})}finally{clearTimeout(timer)}
  }
  async acknowledgeInput(entry,row){
    const value=await this.inputRequest('/api/terminal/input-ack',{ws:entry.ws,id:entry.id,request_key:row.request_key,fingerprint:row.fingerprint});
    if(value.acknowledged!==true||value.request_key!==row.request_key||value.terminal_id!==entry.id||value.input_target!==row.input_target)throw Error('Leitura do recibo não confirmada.');
    return value;
  }
  async inspectInput(ws,id,requestKey){
    const entry=this.entries.get(this.key(ws,id));if(!entry?.inputJournal||entry.activeRequestKey)return;
    await this.syncInput(entry);const journal=entry.inputJournal;
    const row=requestKey?entry.inputPendings.find(item=>item.request_key===requestKey):entry.inputPending;
    if(!row)return;
    const value=await api(route('/api/terminal/input-status',{ws,id,request_key:row.request_key,fingerprint:row.fingerprint}));
    if(value.terminal_id!==id&&value.found)throw Error('Recibo de outra sessão.');
    if(value.resolved){
      const ack=await this.acknowledgeInput(entry,row);
      await journal.resolve(row,{...value,input_pending_revision:ack.input_pending_revision,input_pending_epoch:ack.input_pending_epoch});
      if(entry.alive&&entry.inputJournal===journal){this.projectInputRows(entry);entry.inputBlocked=entry.inputPending?'confirmation_pending':'review_required';this.changed();}
    }
    return value;
  }
  async resumeInput(ws,id){
    const entry=this.entries.get(this.key(ws,id));if(!entry||!this.visible(entry)||entry.activeRequestKey||this.inputQueue.status(entry.key).active)return false;
    const epoch=entry.inputEpoch;
    await this.syncInput(entry);
    if(entry.inputEpoch!==epoch||!this.visible(entry)||entry.inputPending||entry.inputPendingOverflow||!entry.inputProtocol||entry.inputJournalError||entry.inputSuspended||entry.transportUnavailable||entry.status!=='running'||entry.recoverable===false)return false;
    entry.inputEpoch++;entry.inputBlocked=null;entry.term.options.disableStdin=false;this.changed();return true;
  }
  focus(ws, id) { this.entries.get(this.key(ws, id))?.term?.focus(); }
  command(ws, id, text) {
    const entry = this.entries.get(this.key(ws, id));
    if (entry) this.send(entry, text + '\r');
  }
  state(ws, id) {
    const e = this.entries.get(this.key(ws, id));
    return e ? { status: e.status, recoverable: e.recoverable, persisted: e.persisted,
      transportUnavailable: e.transportUnavailable, persistenceState: e.persistenceState,
      persistenceGap: e.persistenceGap, tailUncertain: e.tailUncertain,checkpointUnavailable:e.checkpointUnavailable,
      scrollbackOmitted:e.scrollbackOmitted,inputBlocked:e.inputBlocked,inputPending:e.inputPending,
      inputPendings:e.inputPendings||[],inputPendingOverflow:!!e.inputPendingOverflow,inputTarget:e.inputTarget,
      inputProtocol:e.inputProtocol,inputJournalError:e.inputJournalError,inputBusy:!!e.activeRequestKey,
      memoryPaused:!!e.memoryPaused,emulatorBudget:this.emulatorBudget.status(),rendererRecoveries:e.rendererRecoveries||0 } : null;
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
    this.retryRenderers();
  }
  async poll(entry) {
    if (!entry.alive || !entry.term || entry.polling) return;
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
    let release,deadline,expired=false,catchingUp=false;
    try {
      release=await this.readBudget.acquire(entry.key,controller.signal);
      if(!current())return;
      deadline=setTimeout(()=>{expired=true;controller.abort()},entry.readTimeoutMs??15000);
      const value = await api(route('/api/terminal/output', {
        ws: entry.ws, id: entry.id, cursor: String(entry.cursor),
      }),undefined,{signal:controller.signal});
      if (!current()) return;
      if(typeof value.text!=='string'||value.text.length>32000||new TextEncoder().encode(value.text).length>64000||
          !Number.isSafeInteger(value.cursor)||value.cursor<0||value.cursor>10**12)throw Error('Frame de terminal incompatível.');
      if(value.checkpoint_supported&&!entry.checkpointUnavailable&&(!entry.snapshotRestored||value.truncated||value.geometry_sequence!==entry.geometrySequence)){
        const checkpoint=await api(route('/api/terminal/checkpoint',{ws:entry.ws,id:entry.id}),undefined,{signal:controller.signal});
        if(!current())return;
        if(checkpoint.available){if(await restoreCheckpoint(entry,checkpoint,current)){
          if(entry.rendererScroll!==undefined&&!entry.rendererWasAtBottom)entry.term.scrollToLine?.(Math.min(entry.rendererScroll,entry.term.buffer?.active?.baseY||0));
          delete entry.rendererScroll;this.changed();
        }return;}
        if(checkpoint.retryable){if(entry.term)entry.term.options.disableStdin=true;return;}
        entry.checkpointUnavailable=true;
      }
      if(entry.renderUncertain){entry.term.reset();entry.renderUncertain=false;entry.checkpointUnavailable=true;}
      if (resetForOutput(value,entry.cursor)) entry.term.reset();
      if (value.text) {
        await writeTerminalFrame(entry,value.text,current);
      }
      if(!current())return;
      await this.syncInput(entry,value);
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
      entry.term.options.disableStdin = value.status !== 'running' || value.recoverable === false || !!entry.inputBlocked || !entry.inputProtocol;
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
      if (!current()&&!(expired&&entry.alive&&entry.viewEpoch===generation&&this.visible(entry))) return;
      entry.retry++;
      if (entry.retry === 1) this.report(e.message, 'error');
      if (!entry.transportUnavailable) { entry.transportUnavailable = true; this.changed(); }
      entry.inputEpoch++;
      entry.checkpointUnavailable=false;entry.snapshotRestored=false;
      entry.term.options.disableStdin = true;
      // Loss of transport is not a successful or ready process state.
    } finally {
      clearTimeout(deadline);
      release?.();if(entry.readAbort===controller)entry.readAbort=null;
      entry.polling = false;
      if (this.visible(entry)) entry.timer = setTimeout(() => this.poll(entry),
        entry.retry ? Math.min(8000, 700 * 2 ** Math.min(entry.retry, 4)) : catchingUp ? 0 : 220);
    }
  }
  dispose(entry) {
    this.suspend(entry);entry.alive = false; clearTimeout(entry.timer); clearTimeout(entry.resizeTimer);
    entry.observer.disconnect();entry.intersection?.disconnect();entry.term?.dispose(); entry.host.remove();
    releaseDisposedWrites(entry);this.emulatorBudget.release(entry.key);
  }
  destroy() { window.removeEventListener('storage',this.onInputStorage);document.removeEventListener('visibilitychange',this.onVisibility);for (const e of this.entries.values()) this.dispose(e); this.entries.clear(); }
}
