import { test } from 'node:test';
import assert from 'node:assert/strict';
import { prepareSentraUiReply } from '../src/shell-interactive-ui-reply.js';
import { parseSentraUi } from '../src/shell-interactive-ui-schema.js';

const spec = parseSentraUi(JSON.stringify({version:1,title:'Escolha segura',elements:[
  {type:'choice',id:'modo',label:'Modo',options:['Normal','Alto'],default:'Normal'},
  {type:'checklist',id:'itens',label:'Itens',items:['A','B']}
]}));

test('prepares a user-reviewed draft but does not send anything', () => {
  const text = prepareSentraUiReply(spec,{modo:'Alto',itens:{0:true,1:false}});
  assert.match(text,/Alto/);
  assert.match(text,/"selected": \[\s*"A"/);
  assert.doesNotMatch(text,/"B"/);
});
test('uses schema defaults and rejects choices outside the schema', () => {
  assert.match(prepareSentraUiReply(spec,{}),/Normal/);
  assert.equal(prepareSentraUiReply(spec,{modo:'Inject'}),null);
});
test('no draft for non-interactive spec or oversized response', () => {
  assert.equal(prepareSentraUiReply({version:1,elements:[{type:'text',text:'oi'}]},{}),null);
  assert.equal(prepareSentraUiReply({version:1,title:'x'.repeat(5000),elements:[spec.elements[0]]},{}),null);
});
