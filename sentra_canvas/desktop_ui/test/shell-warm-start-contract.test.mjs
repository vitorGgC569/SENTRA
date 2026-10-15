import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../src/shell-app.jsx',import.meta.url),'utf8');

test('pending creation inspection sends only read-only status, never creates again',()=>{
  const segment=source.slice(source.indexOf('async function inspectConversationCreation('),source.indexOf('async function newConversation('));
  assert.match(segment,/action: 'conversation_request_status'/);
  assert.match(segment,/request_key: payload.request_key/);
  assert.doesNotMatch(segment,/action: 'conversation_create'/);
  assert.match(segment,/confirmedConversation\(inspected.conversation, payload\)/);
  assert.match(segment,/acknowledgeVerifiedPending/);
  assert.match(source,/onClick=\{\(\) => void inspectConversationCreation\(\)\}>Consultar criação/);
  assert.match(source,/if \(payload.action === 'conversation_create'\) \{/);
});
test('cached snapshot is explicitly non-authoritative and action buttons inert',()=>{
  assert.match(source,/const cached = loadVisualHome\(projectId\)/);
  assert.match(source,/saveVisualHome\(project, value\)/);
  assert.match(source,/inert=\{warmVisual\}/);
  assert.doesNotMatch(source,/inert=\{warmVisual \? ''/);
  assert.match(source,/setWarmVisual\(false\)/);
});
test('nonessential startup polls wait for authoritative Home, not cached data',()=>{
 const gates=source.match(/!homeSettled \|\| warmVisual \|\| home\.project_id !== projectId/g)||[];
 assert.ok(gates.length>=2);
});
