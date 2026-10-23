import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {EmulatorBudget} from '../../../integrations/orca-terminal/src/emulator-budget.mjs';
import {writeTerminalFrame,restoreCheckpoint} from '../src/terminal-checkpoint.js';

test('a stalled mobile write disposes the view, releases allocation and cannot ACK its late cursor',async()=>{
 const timers=[],messages=[];
 class Terminal{
  constructor(options){this.options=options;this.cols=options.cols;this.rows=options.rows;this.textarea={setAttribute(){}}}
  loadAddon(){}open(){}reset(){}resize(cols,rows){this.cols=cols;this.rows=rows}
  write(text,ack){this.ack=ack}dispose(){this.disposed=true}
 }
 const source=fs.readFileSync(new URL('../../../integrations/orca-mobile/app/terminal/renderer.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
 const sandbox={Terminal,Unicode11Addon:class{},activateOrcaTerminalUnicodeProvider(){},EmulatorBudget,writeTerminalFrame,restoreCheckpoint,TextEncoder,
  document:{documentElement:{dataset:{sentraView:'test-view'}},getElementById(){return {}}},window:{ReactNativeWebView:{postMessage:value=>messages.push(JSON.parse(value))}},
  setTimeout:(fn,ms)=>{const row={fn,ms};timers.push(row);return row},clearTimeout:row=>{if(row)row.cleared=true}};
 // writeTerminalFrame is evaluated inside this realm so its deadline is controlled.
 const checkpointSource=fs.readFileSync(new URL('../src/terminal-checkpoint.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
 vm.createContext(sandbox);vm.runInContext(checkpointSource+'\n'+source+'\nglobalThis.inspect=()=>({entry,budget});',sandbox);
 const frame={terminal_id:'t',start:0,cursor:3,text:'out',cols:100,rows:28};
 const pending=sandbox.window.sentraTerminalFrame({view:'test-view',terminal_id:'t',id:1,kind:'output',frame});
 const {entry,budget}=sandbox.inspect(),late=entry.term.ack;
 assert.equal(budget.status().renderers,1);timers.find(row=>row.ms===10000).fn();await pending;
 assert.equal(entry.term.disposed,true);assert.equal(entry.alive,false);assert.equal(budget.status().renderers,0);
 assert.equal(entry.cursor,0);late();await Promise.resolve();assert.equal(entry.cursor,0);
 assert.ok(messages.some(row=>row.type==='renderer-stalled'));
 assert.ok(messages.some(row=>row.type==='ack'&&row.error));
 assert.ok(messages.every(row=>['ready','ack','renderer-stalled'].includes(row.type)));
});
