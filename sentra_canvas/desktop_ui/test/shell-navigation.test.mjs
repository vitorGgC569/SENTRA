import {test} from 'node:test';
import assert from 'node:assert/strict';
import {rowsInSpace,canvasNavigation,confirmedConversation} from '../src/shell-navigation.js';

test('a Space change never displays old Dots or conversations',()=>{
  const rows=[{project_id:'project-a',space_id:'space-a',dot_id:'root-a'},
    {project_id:'project-a',space_id:'space-b',dot_id:'root-b'},
    {project_id:'project-b',space_id:'space-a',dot_id:'foreign'}];
  assert.deepEqual(rowsInSpace(rows,'project-a','space-b'),[rows[1]]);
  assert.deepEqual(rowsInSpace(rows,'project-a','loading-space'),[]);
});

test('opening a child Canvas selects its own root and canonical Space',()=>{
  assert.deepEqual(canvasNavigation({project_id:'p',space_id:'own-space',dot_id:'child',canvas_root_dot_id:'own-root'}),
    {view:'canvas',project_id:'p',space_id:'own-space',dot_id:'own-root',conversation_id:null});
});

test('uncertain or mismatched creation replies cannot open an empty/foreign chat',()=>{
  const request={project_id:'p',space_id:'s',dot_id:'d'};
  const value={...request,conversation_id:'confirmed-conversation'};
  assert.equal(confirmedConversation(value,request),true);
  for(const reply of [{status:'uncertain',operation_id:'op'}, {}, {...value,space_id:'foreign'}, {...value,dot_id:'foreign'}])
    assert.equal(confirmedConversation(reply,request),false);
});
