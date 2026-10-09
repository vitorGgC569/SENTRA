const test=require('node:test');
const assert=require('node:assert/strict');
require('../../sentra_canvas/static/graph-view.js');
const graph=globalThis.SentraGraphView;
test('viewport excludes offscreen graph nodes without changing input sessions',()=>{
 const nodes=Array.from({length:500},(_,i)=>({id:'n'+i,x:i*400,y:0,width:300,height:200,process_session:'session'+i}));
 const before=JSON.stringify(nodes);
 assert.deepEqual([...graph.visibleIDs(nodes,{x:0,y:0,scale:1,width:1000,height:600,padding:0})],['n0','n1','n2']);
 assert.deepEqual([...graph.visibleIDs(nodes,{x:-4000,y:0,scale:1,width:1000,height:600,padding:0})],['n10','n11','n12']);
 assert.equal(JSON.stringify(nodes),before);
});
test('selection adjacency comes from host topology and graph bounds cover all nodes',()=>{
 const nodes=[{id:'a',x:-100,y:50,width:300,height:200},{id:'b',x:500,y:-40,width:350,height:260}];
 assert.deepEqual(graph.neighbors(nodes,[{source:'a',target:'b'},{source:'a',target:'unknown'}],'a'),['b']);
 assert.deepEqual(graph.bounds(nodes),{left:-100,top:-40,right:850,bottom:250});
 assert.throws(()=>graph.visibleIDs(nodes,{x:0,y:0,scale:0,width:100,height:100}));
});
