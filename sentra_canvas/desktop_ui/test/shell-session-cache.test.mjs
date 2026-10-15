import {test} from 'node:test';
import assert from 'node:assert/strict';
import {saveVisualHome, loadVisualHome, WARM_CACHE_TTL_MS} from '../src/shell-session-cache.js';

const storage=()=>{const values=new Map();return {
 getItem:key=>values.get(key)||null,
 setItem:(key,v)=>values.set(key,v),
 values,
}};
const confirmed={project_id:'project-1',space:{project_id:'project-1',space_id:'sp',name:'Dev'},
 spaces:[{project_id:'project-1',space_id:'sp',name:'Dev'}],
 dots:[{project_id:'project-1',space_id:'sp',dot_id:'dot',name:'Agent',
   agent_id:'agent',mascot:'blue',status:'RUNNING',token:'secret-token'}],
 conversations:[{project_id:'project-1',space_id:'sp',dot_id:'dot',conversation_id:'c',title:'Conversa',
   messages:[{content:'PRIVATE-MESSAGE'}]}],
 activity:{items:[{text:'PRIVATE-RECEIPT'}]},run:{state:'RUNNING'},
 owner:'sensitive-owner',capabilities:[{grant:'sensitive-grant'}],
};
test('stores temporary project-scoped navigation metadata, not messages, tokens, status or grants',()=>{
 const s=storage();
 assert.equal(saveVisualHome('project-1',confirmed,s,1000),true);
 assert.equal(s.values.size,1);
 const raw=[...s.values.values()][0];
 for(const forbidden of ['PRIVATE-MESSAGE','PRIVATE-RECEIPT','secret-token','sensitive-grant','sensitive-owner','RUNNING']) assert.equal(raw.includes(forbidden),false);
 const warm=loadVisualHome('project-1',s,2000);
 assert.equal(warm.dots[0].name,'Agent');
 assert.equal(warm.conversations[0].title,'Conversa');
 assert.deepEqual(warm.teams,[]);
 assert.equal('run' in warm,false);
 assert.equal(loadVisualHome('project-2',s,2000),null);
});
test('expires and rejects mismatched projects or invalid cache structures',()=>{
 const s=storage();
 assert.equal(saveVisualHome('project-1',confirmed,s,1000),true);
 assert.equal(loadVisualHome('project-1',s,1000+WARM_CACHE_TTL_MS+1),null);
 assert.equal(loadVisualHome('project-1',s,900),null);
 assert.equal(saveVisualHome('different',confirmed,s,2000),false);
 s.setItem('sentra_visual_home_v1:project-1','{"version":1,"at":1200,"home":{"project_id":"other"}}');
 assert.equal(loadVisualHome('project-1',s,2000),null);
});
test('unavailable or blocked sessionStorage never breaks startup',()=>{
 const blocked={getItem(){throw Error('denied');},setItem(){throw Error('denied')}};
 assert.equal(saveVisualHome('project-1',confirmed,blocked,2000),false);
 assert.equal(loadVisualHome('project-1',blocked,2000),null);
});
