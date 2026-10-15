import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function bridgeHarness(api){
  const source=fs.readFileSync(new URL('../src/shell-bridge.js',import.meta.url),'utf8')
    .replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
  class ApiError extends Error{constructor(message,status=0){super(message);this.status=status;}}
  const writes=[];
  const sandbox={ApiError,api,canvasMaintenanceActive:()=>false,confirmedConversation:()=>true,
    sessionStorage:{getItem:()=>null,setItem:(...args)=>writes.push(args)},
    window:{dispatchEvent:()=>assert.fail('A lookup must not mutate pending intents')},CustomEvent:class{},
    crypto:{randomUUID:()=>assert.fail('A lookup must not create a mutation request key')},
  };
  vm.createContext(sandbox);vm.runInContext(source+'\nglobalThis.testBridge=shellBridge;',sandbox);
  return {bridge:sandbox.testBridge,writes};
}

test('direct conversation lookup uses the production read-only bridge without a mutation key',async()=>{
  const calls=[],scope={project_id:'project',space_id:'space',conversation_id:'conversation'};
  const canonical={...scope,dot_id:'dot',title:'Persisted conversation',revision:3};
  const {bridge,writes}=bridgeHarness(async(path,body,options)=>{
    calls.push({path,body,options});return {ok:true,value:canonical};
  });
  assert.equal(await bridge({action:'conversation_get',...scope}),canonical);
  assert.equal(calls.length,1);
  assert.equal(calls[0].options.readOnly,true);
  assert.equal(calls[0].body.action,'conversation_get');
  assert.equal(calls[0].body.request_key,undefined);
  assert.deepEqual(writes,[]);
});

test('lookup denial cannot become an uncertain mutation or create retained pending operations',async()=>{
  const {bridge,writes}=bridgeHarness(async()=>{throw Object.assign(new Error('access revoked'),{status:403});});
  await assert.rejects(()=>bridge({action:'conversation_get',project_id:'p',space_id:'s',conversation_id:'c'}),error=>{
    assert.equal(error.status,403);assert.equal(error.uncertain,false);return true;
  });
  assert.deepEqual(writes,[]);
});
