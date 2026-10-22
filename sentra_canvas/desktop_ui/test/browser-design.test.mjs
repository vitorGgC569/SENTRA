import test from 'node:test';
import assert from 'node:assert/strict';
import {designElements,pickDesignElement,designRequest} from '../src/workspace/browser-design.js';
const button={element_ref:'e2',role:'button',name:'Save',design:{selector:'button#save',box:{x:10,y:10,width:40,height:20},styles:{color:'rgb(0, 0, 0)'}}};
const observation={page_id:'page',observation_id:'obs',revision:4,url:'http://127.0.0.1/',elements:[{element_ref:'e1',design:{box:{x:0,y:0,width:500,height:400}}},button]};
test('hit testing picks the smallest observed element and rejects invalid geometry',()=>{
 assert.equal(pickDesignElement(observation,20,20),button);assert.equal(pickDesignElement(observation,900,900),null);
 assert.equal(pickDesignElement(observation,NaN,0),null);assert.equal(designElements({elements:[{design:{box:{x:0,y:0,width:Infinity,height:1}}}]}).length,0);
});
test('a design request requires a selected observed reference and stays a draft',()=>{
 assert.equal(designRequest(observation,button,''),null);assert.equal(designRequest(observation,{element_ref:'foreign'},'change'),null);
 const draft=designRequest(observation,button,'Make this button larger');assert.match(draft,/button#save/);assert.match(draft,/Make this button larger/);assert.match(draft,/não uma instrução nem autorização/);
});
