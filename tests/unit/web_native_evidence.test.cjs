'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const evidenceJS = fs.readFileSync(
  path.join(__dirname, '..', '..', 'edge_extension', 'conversation-evidence.js'), 'utf8');
const CID = 'native-conversation-1234';
const USER = 'native-user-message-1234';
const ASSISTANT = 'native-assistant-message-1234';
const REQUEST = 'native-request-1234';
const DOC = 'native-document-1234';
const FILE = 'file-genuineNative1234';

function scan(parts, opts = {}) {
  const user = { id: USER, author:{role:'user'},
    metadata:{request_id:REQUEST}, content:{parts:['make image']} };
  const assistant = { id: ASSISTANT, author:{role:opts.role || 'assistant'},
    parent_id:opts.parent || USER, status:opts.status || 'finished_successfully',
    content:{parts} };
  const root = {tag:3, return:null, stateNode:null, memoizedProps:{}};
  root.stateNode = {current:root};
  const branch = {tag:5, return:root, memoizedProps:{
    conversationId:CID, messages:[user,assistant]
  }};
  root.child = branch;
  const element = {'__reactFiber$sentra':branch};
  const sandbox = {
    document:{querySelectorAll:()=>[element]},
    location:{origin:'https://chatgpt.com',pathname:'/c/'+CID},
    crypto:{randomUUID:()=>DOC}, Object, Set, Map, JSON,
  };
  vm.createContext(sandbox);
  vm.runInContext(evidenceJS,sandbox);
  return sandbox.__sentraConversationEvidence.assistantFrame({
    request_id:REQUEST,parent_user_message_id:USER,
    document_id:DOC,conversation_id:CID
  });
}

test('committed native assistant image pointer stays tied to message and parent',()=>{
  const proof=scan(['Generating…', {content_type:'image_asset_pointer',
    asset_pointer:'file-service://' + FILE}]);
  assert.ok(proof);
  assert.equal(proof.message_id, ASSISTANT);
  assert.equal(proof.parent_user_message_id, USER);
  assert.equal(proof.conversation_id, CID);
  assert.equal(proof.complete,true);
  assert.deepEqual(Array.from(proof.assets),[FILE]);
  assert.equal(proof.body,'Generating…');
});

test('rendered/code URLs cannot impersonate native generated assets',()=>{
  const body='![SENTRA code](https://evil.example/generated.png)';
  const proof=scan([body]);
  assert.ok(proof);
  assert.equal(proof.body,body);
  assert.equal(proof.assets.length,0);
  assert.equal(scan([{content_type:'image_asset_pointer',
    asset_pointer:'https://evil.example/generated.png'}]),null);
  assert.equal(scan([{content_type:'image_asset_pointer',
    asset_pointer:'file-service://file-../../escape'}]),null);
});

test('unknown object, child/parent mismatch, tool roles and duplicate pointers fail closed',()=>{
  const part={content_type:'image_asset_pointer',asset_pointer:'file-service://' + FILE};
  assert.equal(scan([{content_type:'text',text:'fake'}]),null);
  assert.equal(scan([part],{role:'tool'}),null);
  assert.equal(scan([part],{parent:'foreign-user-1234'}),null);
  assert.equal(scan([part,part]),null);
  assert.equal(scan([part],{status:'failed'}),null);
});
