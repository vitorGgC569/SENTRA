import test from "node:test";
import assert from "node:assert/strict";
import {authoritativeCables,bezierPath,createCablePhysics,stepCable,
  ropePath,mountCableLayer,MAX_CABLES} from "../physical_cables.mjs";
const edge={id:"wire1",source:{x:0,y:0},target:{x:300,y:120}};
const svgNS="http://www.w3.org/2000/svg";
function fakeSvg(){
  const elements=[];
  const doc={createElementNS(ns,tag){
    assert.equal(ns,svgNS);assert.equal(tag,"path");
    const attrs={};
    return {attrs,setAttribute(k,v){attrs[k]=v;},
      remove(){const i=elements.indexOf(this);if(i>=0)elements.splice(i,1);}};
  }};
  return {elements,namespaceURI:svgNS,ownerDocument:doc,appendChild(x){elements.push(x);}};
}
test("xyflow-style cables: safe immutable authoritative endpoints and Bezier bounds",()=>{
  const source=JSON.parse(JSON.stringify(edge));
  const [e]=authoritativeCables(()=>[source]);
  source.source.x=400;
  assert.equal(e.source.x,0);
  assert.equal(Object.isFrozen(e)&&Object.isFrozen(e.source),true);
  const d=bezierPath(e.source,e.target,{sag:15});
  assert.match(d,/^M 0 0 C /);
  assert.ok(!d.includes("NaN")&&!d.includes("Infinity"));
  assert.throws(()=>authoritativeCables(()=>[{...edge,run:{kind:"execute"}}]),/denied/);
  assert.throws(()=>authoritativeCables(()=>[edge,edge]),/denied/);
  assert.throws(()=>authoritativeCables(()=>Array(MAX_CABLES+1).fill(edge)),/denied/);
  assert.throws(()=>bezierPath(edge.source,{x:Infinity,y:0}),/denied/);
  assert.throws(()=>bezierPath(edge.source,edge.target,{sag:99999}),/denied/);
});
test("spring relaxation pins immutable endpoints, bounds overshoot and settles",()=>{
  const state=createCablePhysics(edge);
  assert.equal(state.points.length,10);
  const moved={...edge,source:{x:100,y:70},target:{x:360,y:130}};
  let moving=false;
  for(let n=0;n<500;n++)moving=stepCable(state,moved,1/60);
  assert.equal(state.points[0].x,100);
  assert.equal(state.points.at(-1).x,360);
  assert.equal(moving,false,"damping should converge");
  assert.match(ropePath(state),/^M 100 70 Q /);
  for(const p of state.points)assert.ok(Number.isFinite(p.x)&&Number.isFinite(p.y));
  assert.throws(()=>createCablePhysics(edge,{samples:100}),/denied/);
  assert.throws(()=>stepCable(state,moved,NaN),/denied/);
});
test("opt-in SVG mounting uses only readGraph and local RAF; disposal removes paths",()=>{
  const svg=fakeSvg();
  const callbacks=new Map();let count=0,reads=0;
  let authoritative=[edge];
  const layer=mountCableLayer({
    svg,readGraph:()=>{reads++;return authoritative;},
    requestFrame:fn=>{callbacks.set(++count,fn);return count;},
    cancelFrame:id=>callbacks.delete(id)
  });
  assert.equal(svg.elements.length,0,"must never mount automatically");
  layer.refresh();
  assert.equal(svg.elements.length,1);
  assert.equal(svg.elements[0].attrs["pointer-events"],"none");
  assert.equal(svg.elements[0].attrs["aria-hidden"],"true");
  assert.ok(reads>0);
  authoritative=[{...edge,target:{x:700,y:220}}];
  layer.refresh();
  assert.ok(svg.elements[0].attrs.d.includes("700"));
  authoritative=[];
  layer.refresh();
  assert.equal(svg.elements.length,0);
  layer.dispose();
  assert.equal(callbacks.size,0);
  assert.throws(()=>layer.refresh(),/denied/);
});
test("reduced-motion draws static path without requestAnimationFrame and rejects invalid graph",()=>{
  const svg=fakeSvg();let scheduled=0;
  const layer=mountCableLayer({svg,readGraph:()=>[edge],
    requestFrame:()=>{scheduled++;return scheduled;},cancelFrame:()=>{},
    reducedMotion:true});
  layer.refresh();
  assert.equal(scheduled,0);
  assert.equal(svg.elements[0].attrs.d,bezierPath(edge.source,edge.target));
  layer.dispose();assert.equal(svg.elements.length,0);
  const denied=mountCableLayer({svg,readGraph:()=>[{...edge,grant:"admin"}],
    requestFrame:()=>1,cancelFrame:()=>{},reducedMotion:true});
  assert.throws(()=>denied.refresh(),/denied/);
  denied.dispose();
});
