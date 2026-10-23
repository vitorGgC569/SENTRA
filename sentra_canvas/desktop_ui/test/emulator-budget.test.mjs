import test from 'node:test';
import assert from 'node:assert/strict';
import {EmulatorBudget} from '../../../integrations/orca-terminal/src/emulator-budget.mjs';

test('buffer allocation budget counts both screen buffers, scrollback and instance overhead',()=>{
 const budget=new EmulatorBudget();assert.equal(budget.cost(100,28,2000),1024*1024+100*2056*32);
 for(let i=0;i<8;i++)assert.equal(budget.reserve('t'+i,100,28,2000),true);
 assert.equal(budget.reserve('t8',100,28,2000),false);assert.equal(budget.status().renderers,8);
 assert.ok(budget.status().reservedBytes<=budget.status().maxBytes);
});
test('rejected resize leaves the previous reservation intact and release permits replacement',()=>{
 const budget=new EmulatorBudget({maxBytes:16*1024*1024,maxRenderers:2});
 assert.equal(budget.reserve('a',100,28,2000),true);assert.equal(budget.reserve('b',100,28,2000),true);
 const previous=budget.status().reservedBytes;
 assert.equal(budget.reserve('a',500,200,2000),false);assert.equal(budget.status().reservedBytes,previous);
 budget.release('b');assert.equal(budget.reserve('c',100,28,2000),true);
});
test('mobile single-view budget admits the full protocol geometry but no second emulator',()=>{
 const budget=new EmulatorBudget({maxBytes:16*1024*1024,maxRenderers:1});
 assert.equal(budget.reserve('mobile',500,200,500),true);
 assert.equal(budget.reserve('second',20,5,0),false);
 assert.throws(()=>budget.reserve('bad',501,200,500),/geometry/);
 assert.equal(budget.status().measurement,'buffer-allocation-model');
});
