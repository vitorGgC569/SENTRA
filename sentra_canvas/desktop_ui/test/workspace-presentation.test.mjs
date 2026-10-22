import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readMode,writeMode,simpleLayout,restoreModeLayout,layoutStorageKey,sessionTools} from '../src/workspace/presentation.js';
import {initialLayout,saveLayout,validateLayout} from '../src/workspace/layout.js';
const store=()=>{const rows=new Map();return {getItem:key=>rows.get(key),setItem:(key,value)=>rows.set(key,value)}};
test('simple is the default, including inaccessible or invalid preference storage',()=>{
 assert.equal(readMode(store()),'simple');assert.equal(readMode({getItem(){throw Error('private')}}),'simple');
 const data=store();writeMode(data,'advanced');assert.equal(readMode(data),'advanced');writeMode(data,'simple');assert.equal(readMode(data),'simple');
 assert.throws(()=>writeMode(data,'full'));assert.ok(validateLayout(simpleLayout()));assert.equal(simpleLayout().panes.main.tabs.length,0);
});
test('simple restores only its own contextual tabs, preserving the full advanced layout',()=>{
 const data=store(),advanced=initialLayout();saveLayout(data,'alice/dot',advanced);
 assert.equal(restoreModeLayout(data,'alice/dot','simple').panes.main.tabs.length,0);
 const simple=simpleLayout();simple.panes.main={tabs:[{id:'files:a',kind:'files',resourceId:'a'}],active:'files:a'};
 saveLayout(data,layoutStorageKey('alice/dot','simple'),simple);
 assert.deepEqual(restoreModeLayout(data,'alice/dot','advanced'),advanced);
 assert.deepEqual(restoreModeLayout(data,'alice/dot','simple'),simple);
 assert.equal(restoreModeLayout(data,'bob/dot','simple').panes.main.tabs.length,0);
 data.setItem('sentra-workspace-v1:'+layoutStorageKey('alice/dot','simple'),'{broken');
 assert.equal(restoreModeLayout(data,'alice/dot','simple').panes.main.tabs.length,0);
});
test('tool menu excludes unimplemented graphical adapters and unrelated shells',()=>{
 assert.deepEqual(sessionTools([{id:'powershell'},{id:'antigravity-app',mode:'external-app'},{id:'codex',installed:true},{id:'opencode',installed:false}]).map(t=>t.id),['codex','opencode']);
});
