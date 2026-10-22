import {test} from 'node:test';
import assert from 'node:assert/strict';
import {terminalHistoryLabel,resetForOutput} from '../src/terminal-history-state.js';
test('pending flush is not a persistence failure and archived output is explicit',()=>{
 assert.equal(terminalHistoryLabel({persisted:false,persistenceState:'pending'}),'Gravando histórico…');
 assert.equal(terminalHistoryLabel({persisted:false,persistenceState:'failed'}),'Histórico não salvo');
 assert.equal(terminalHistoryLabel({status:'history_restored',tailUncertain:true}),'Histórico recuperado · final não confirmado');
 assert.equal(terminalHistoryLabel({persistenceGap:true}),'Histórico parcial');
 assert.equal(terminalHistoryLabel({persisted:true},'cmd'),'cmd');
});
test('an empty gap or rewound cursor still resets the stale terminal view',()=>{
 assert.equal(resetForOutput({text:'',truncated:true,cursor:10},10),true);
 assert.equal(resetForOutput({text:'',cursor:5},10),true);
 assert.equal(resetForOutput({text:'next',cursor:14},10),false);
});
