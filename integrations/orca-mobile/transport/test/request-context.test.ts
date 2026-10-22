import {test} from 'node:test';
import assert from 'node:assert/strict';
import {bindRequestContext,requireRequestContext} from '../src/request-context';
const device={device_id:'phone',scope:{project_id:'p',space_id:'s',dot_id:'d'}};
test('an admitted input stays bound to its original transport and exact paired scope',()=>{
 const transport={},bound=bindRequestContext(transport,device);
 requireRequestContext(bound,transport,device);
 assert.throws(()=>requireRequestContext(bound,{},device));
 assert.throws(()=>requireRequestContext(bound,transport,null));
 assert.throws(()=>requireRequestContext(bound,transport,{...device,device_id:'other'}));
 for(const key of ['project_id','space_id','dot_id'])assert.throws(()=>requireRequestContext(bound,transport,{...device,scope:{...device.scope,[key]:'changed'}}));
 assert.throws(()=>bindRequestContext(null,device));
});
test('scope mutation during asynchronous admission cannot rebind the pending command',async()=>{
 const mutable={...device,scope:{...device.scope}},transport={},bound=bindRequestContext(transport,mutable);
 await Promise.resolve();mutable.scope.dot_id='new-dot';let transmitted=false;
 assert.throws(()=>{requireRequestContext(bound,transport,mutable);transmitted=true});assert.equal(transmitted,false);
});
