"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const script=fs.readFileSync(path.resolve(__dirname,"../../sentra_canvas/static/rope-physics.js"),"utf8");
let frames=[],reduced=false;
function element(){
  const names=new Set();
  return {dataset:{},attrs:{},removed:false,
    classList:{toggle(k,v){if(v)names.add(k);else names.delete(k);},contains(k){return names.has(k);}},
    setAttribute(k,v){this.attrs[k]=v;},remove(){this.removed=true;}};
}
const layer={isConnected:true,children:[],appendChild(x){this.children.push(x);}};
const window={document:{hidden:false,createElementNS(_ns,tag){assert.equal(tag,"path");return element();}},
requestAnimationFrame(cb){frames.push(cb);},matchMedia(){return {matches:reduced};}};
vm.runInNewContext(script,{window});
const physics=window.SentraCablePhysics;
assert.ok(physics);
const origin={id:"origin",x:20,y:40,width:380,height:200,title:"Origin"};
const worker={id:"worker",x:650,y:200,width:380,height:250,title:"Worker"};
const link={id:"cable-1",source:"origin",target:"worker"};
physics.sync(layer,[link],[origin,worker]);
assert.equal(layer.children.length,1);
const cable=layer.children[0];
assert.equal(cable.dataset.edge,"cable-1");
assert.equal(cable.attrs.role,"button");
for(let i=0;i<50&&frames.length;i++)frames.shift()();
const first=cable.attrs.d;
assert.match(first,/^M /);
worker.y=450;
physics.sync(layer,[link],[origin,worker]);
assert.equal(layer.children.length,1);
for(let i=0;i<150&&frames.length;i++)frames.shift()();
assert.notEqual(cable.attrs.d,first);
assert.ok(!cable.attrs.d.includes("NaN"));
physics.sync(layer,[],[origin,worker]);
assert.equal(cable.removed,true);
reduced=true;
physics.sync(layer,[link],[origin,worker]);
assert.equal(layer.children.length,2);
assert.match(layer.children[1].attrs.d,/^M /);
physics.clear();
assert.equal(layer.children[1].removed,true);
console.log("SENTRA physics: create/move/retain/reduce-motion/remove OK");
