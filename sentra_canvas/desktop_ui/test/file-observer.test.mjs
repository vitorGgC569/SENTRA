import test from 'node:test';
import assert from 'node:assert/strict';
import {watchWorkspaceFile} from '../src/workspace/file-observer.js';

test('file observers group exact scopes, suppress overlapping reads and release the last listener',async()=>{
 const timers=new Map(),events=new Map(),before={setInterval,clearInterval,window:globalThis.window,document:globalThis.document};
 let next=0,reads=0,release;
 globalThis.setInterval=callback=>{timers.set(++next,callback);return next};globalThis.clearInterval=id=>timers.delete(id);
 globalThis.document={hidden:false};globalThis.window={addEventListener:(name,callback)=>events.set(callback,name),removeEventListener:(_name,callback)=>events.delete(callback)};
 try{
  const bridge=async request=>{reads++;assert.equal(request.action,'workspace_file_get');return await new Promise(resolve=>release=resolve)},seen=[];
  const stopOne=watchWorkspaceFile(bridge,{project_id:'p',path:'a.txt'},v=>seen.push(['one',v]));
  const stopTwo=watchWorkspaceFile(bridge,{path:'a.txt',project_id:'p'},v=>seen.push(['two',v]));
  assert.equal(timers.size,1);assert.equal(events.size,1);const tick=[...timers.values()][0];tick();tick();assert.equal(reads,1);
  release({revision:2});await new Promise(resolve=>setImmediate(resolve));assert.equal(seen.length,2);
  const stopOther=watchWorkspaceFile(bridge,{project_id:'q',path:'a.txt'},()=>{});assert.equal(timers.size,2);
  stopOne();assert.equal(timers.size,2);stopTwo();assert.equal(timers.size,1);stopOther();assert.equal(timers.size,0);assert.equal(events.size,0);
 }finally{Object.assign(globalThis,before)}
});
