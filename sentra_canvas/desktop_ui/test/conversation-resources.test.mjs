import {test} from 'node:test';
import assert from 'node:assert/strict';
import {conversationResources,newlyObservedTerminal} from '../src/workspace/conversation-resources.js';
test('conversation tools only present resources owned by the selected Dot',()=>{
 const view=conversationResources({machines:[{agent_id:'other',kind:'browser'}],terminals:[{id:'one',dot_id:'dot'},{id:'other',dot_id:'child'},{id:'unbound'}]},{dot_id:'dot',agent_id:'agent'});
 assert.deepEqual(view,{terminals:[{id:'one',dot_id:'dot'}],browser:false});
 assert.equal(conversationResources({machines:[{agent_id:'agent',kind:'browser'}]},{dot_id:'dot',agent_id:'agent'}).browser,true);
});
test('observation does not reopen old sessions or restore a closed process',()=>{
 const rows=[{id:'old',status:'running'},{id:'closed',status:'closed'},{id:'new',status:'running'}];
 assert.equal(newlyObservedTerminal(null,rows),null);
 assert.equal(newlyObservedTerminal(new Set(['old']),rows).id,'new');
 assert.equal(newlyObservedTerminal(new Set(['old','new']),rows),null);
});
