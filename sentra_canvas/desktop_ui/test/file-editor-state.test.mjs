import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {FileDraftWriter,draftFor,editorConflict,textDigest,savedDraftMatches,fileSaveRequest} from '../src/workspace/file-editor-state.js';

test('draft retains exact original newline bytes and UTF-16 selection positions',async()=>{
 const content='ação\r\n漢字 🦊';const file={content,sha256:await textDigest(content)};
 const draft=draftFor(file);assert.equal(draft.base_content,content);assert.equal(draft.base_sha256,file.sha256);
 assert.equal(editorConflict(file,draft),false);assert.equal(editorConflict({...file,sha256:'other'},draft),true);
 assert.equal(editorConflict({...file,file_error:'removed'},draft),true);
});
test('writer serializes revisions and preserves edits arriving during a pending save',async()=>{
 const calls=[];let release;
 const writer=new FileDraftWriter(async(body,revision)=>{calls.push({body,revision});if(calls.length===1)await new Promise(resolve=>release=resolve);return {saved:true,revision:revision+1}},4);
 writer.schedule({content:'one'});const saving=writer.flush();writer.schedule({content:'two'});release();await saving;
 assert.deepEqual(calls,[{body:{content:'one'},revision:4},{body:{content:'two'},revision:5}]);assert.equal(writer.revision,6);writer.close();
});
test('draft conflict freezes future saves until an explicit reload',async()=>{
 let calls=0;const states=[];const writer=new FileDraftWriter(async()=>{calls++;return {saved:false,revision:9}},1,(state)=>states.push(state));
 writer.schedule({content:'kept in UI'});await assert.rejects(writer.flush(),/outra janela/);
 writer.schedule({content:'never sent'});await assert.rejects(writer.flush(),/outra janela/);
 assert.equal(calls,1);assert.ok(states.includes('error'));writer.close();
});
test('closing flushes only the scoped pending draft, never a physical save request',async()=>{
 const calls=[];const writer=new FileDraftWriter(async(body,revision)=>{calls.push({body,revision});return {saved:true,revision:2}},1);
 writer.schedule({content:'last draft'});writer.close();await writer.running;
 assert.deepEqual(calls,[{body:{content:'last draft'},revision:1}]);
 await assert.rejects(writer.commit(null),/fechado/);
});
test('transport loss is not retried, even with identical draft text',async()=>{
 let count=0;const writer=new FileDraftWriter(async()=>{count++;throw Error('lost acknowledgement')},0);
 writer.schedule({content:'private'});await assert.rejects(writer.flush(),/lost acknowledgement/);
 await assert.rejects(writer.flush(),/lost acknowledgement/);assert.equal(count,1);writer.close();
});
test('clearing a draft requires a successful receipt and exact current and draft hashes',async()=>{
 const content='saved UTF-8 🦊';const sha256=await textDigest(content);const file={sha256},draft={content};
 assert.equal(await savedDraftMatches({state:'SUCCEEDED',evidence:{sha256}},file,draft),true);
 for(const [operation,current,local] of [
  [{state:'UNCERTAIN',evidence:{sha256}},file,draft],
  [{state:'FAILED',evidence:{sha256}},file,draft],
  [{state:'SUCCEEDED',evidence:{}},file,draft],
  [{state:'SUCCEEDED',evidence:{sha256}},{sha256:'changed'},draft],
  [{state:'SUCCEEDED',evidence:{sha256}},{...file,file_error:'deleted'},draft],
  [{state:'SUCCEEDED',evidence:{sha256}},file,{content:'new unsaved text'}],
 ])assert.equal(await savedDraftMatches(operation,current,local),false);
});
test('save pins Dot, conversation, execution workspace and SHA, without accepting authority extras',()=>{
 const scope={project_id:'p',space_id:'s',dot_id:'d',conversation_id:'c',owner:'untrusted'};
 const file={execution_workspace_id:'tree-1',editor:{machine_id:'m',work_item_id:'w',action:'untrusted'}};
 const request=fileSaveRequest(scope,file,{content:'private',base_sha256:'a'.repeat(64)},'src/file.txt','original-key');
 assert.equal(request.request.action,'machine_execute');assert.equal(request.request.arguments.execution_workspace_id,'tree-1');
 assert.equal(request.request.arguments.expected_sha256,'a'.repeat(64));assert.equal(request.conversation_id,'c');assert.ok(!('owner' in request));
 assert.throws(()=>fileSaveRequest({...scope,conversation_id:null},file,{base_sha256:'a'},'file','key'),/Identidade/);
});
test('production bridge stores no editor content in session storage after transport loss',async()=>{
 const source=fs.readFileSync(new URL('../src/shell-bridge.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
 const writes=[],calls=[];class ApiError extends Error{}
 const context={ApiError,canvasMaintenanceActive:()=>false,confirmedConversation:()=>true,api:async(_path,body)=>{calls.push(body);throw Error('lost ACK')},
  sessionStorage:{getItem:()=>null,setItem:(...args)=>writes.push(args)},window:{dispatchEvent:()=>{}},CustomEvent:class{},crypto:{randomUUID:()=> 'durable-key'}};
 vm.createContext(context);vm.runInContext(source+'\nglobalThis.testBridge=shellBridge;',context);
 const request=fileSaveRequest({project_id:'p',space_id:'s',dot_id:'d',conversation_id:'c'},
  {execution_workspace_id:'project',editor:{machine_id:'m',work_item_id:'w'}},{content:'PRIVATE DRAFT',base_sha256:'a'.repeat(64)},'file.txt','durable-key');
 await assert.rejects(context.testBridge(request),/lost ACK/);assert.equal(calls.length,1);assert.deepEqual(writes,[]);
});
