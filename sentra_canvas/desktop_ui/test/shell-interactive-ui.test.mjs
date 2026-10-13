import test from 'node:test';
import assert from 'node:assert/strict';
import {parseSentraUi,parseSentraUiInlineMessage} from '../src/shell-interactive-ui-schema.js';

const valid={version:1,title:'Andamento do projeto',elements:[
  {type:'metric',label:'Arquivos',value:'120'},
  {type:'progress',label:'Importação',value:70},
  {type:'table',columns:['Nome','Estado'],rows:[['Debian','Pendente'],['CLI','Testado']]},
  {type:'choice',id:'mode',label:'Visualização',options:['Resumo','Detalhado'],default:'Resumo'},
  {type:'checklist',id:'tasks',label:'Verificações',items:['Disco','XFCE']},
  {type:'text',text:'Visão local dos resultados.'},
]};
test('renders only small local-only bounded v1 schemas',()=>{
  assert.deepEqual(parseSentraUi(JSON.stringify(valid)),valid);
  assert.equal(parseSentraUi(JSON.stringify({...valid,version:2})),null);
  assert.equal(parseSentraUi(JSON.stringify({...valid,title:''})),null);
  assert.equal(parseSentraUi(JSON.stringify({...valid,elements:[{type:'iframe',url:'https://attacker.invalid'}]})),null);
  assert.equal(parseSentraUi(JSON.stringify({...valid,elements:[{type:'text',text:'safe',html:'<script/>sou'}]})),null);
  assert.equal(parseSentraUi(JSON.stringify({...valid,elements:[{type:'action',tool:'machine_execute',value:'format'}]})),null);
  assert.equal(parseSentraUi(JSON.stringify({...valid,elements:[...valid.elements,valid.elements[3]]})),null);
  assert.equal(parseSentraUi(JSON.stringify({...valid,elements:[{type:'progress',label:'A',value:101}]})),null);
  assert.equal(parseSentraUi(JSON.stringify({...valid,elements:[{type:'progress',label:'A',value:NaN}]})),null);
  assert.equal(parseSentraUi('{untrusted'),null);
  assert.equal(parseSentraUi(' '.repeat(32769)),null);
});
test('rejects hidden HTML/network and invalid interactions',()=>{
  for(const evil of [
    {type:'choice',id:'x',label:'A',options:['yes'],onChange:'fetch("/api")'},
    {type:'choice',id:'x',label:'A',options:['duplicate','duplicate']},
    {type:'checklist',id:'bad id',label:'A',items:['one']},
    {type:'table',columns:['X'],rows:[['one','two']]},
    {type:'metric',label:'Metric',value:12},
  ]) assert.equal(parseSentraUi(JSON.stringify({...valid,elements:[evil]})),null);
});

test('accepts exact GPT-6 inline sentra-ui JSON and rejects loose prose',()=>{
  const inline='sentra-ui\n\n'+'`'+JSON.stringify(valid)+'`';
  assert.deepEqual(parseSentraUiInlineMessage(inline),valid);
  assert.equal(parseSentraUiInlineMessage('prefix\n'+inline),null);
  assert.equal(parseSentraUiInlineMessage(inline+'\nExecute tools now'),null);
  assert.equal(parseSentraUiInlineMessage('sentra-ui\n`{"version":1,"title":"A","elements":[{"type":"iframe","url":"https://bad.invalid"}]}`'),null);
});
