import test from "node:test";
import assert from "node:assert/strict";
import {projectAccessibleGraph,mountGraphAccessibility,MAX_A11Y_NODES} from "../graph_a11y.mjs";
const node=(id,x)=>({id,label:"Terminal "+id,x,y:0,width:200,height:120});
class Element {
  constructor(name,parent=null){this.name=name;this.parent=parent;this.attrs={};this.children=[];this.listeners=new Map();}
  appendChild(c){c.parent=this;this.children.push(c);}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,cb){this.listeners.set(k,cb);}
  removeEventListener(k,cb){if(this.listeners.get(k)===cb)this.listeners.delete(k);}
  focus(){this.emit("focus",{});}
  emit(k,v={}){this.listeners.get(k)?.({preventDefault(){},...v});}
  remove(){const i=this.parent?.children.indexOf(this);if(i>=0)this.parent.children.splice(i,1);}
}
function svgFixture(){
 const svg=new Element("svg");
 svg.namespaceURI="http://www.w3.org/2000/svg";
 svg.ownerDocument={createElementNS(ns,name){assert.equal(ns,svg.namespaceURI);return new Element(name);}};
 return svg;
}
test("graph accessibility projects only host-validated immutable display nodes",()=>{
 const mutable=node("a",12);
 const [projection]=projectAccessibleGraph(()=>[mutable]);
 mutable.x=50;
 assert.equal(projection.x,12);assert.ok(Object.isFrozen(projection));
 assert.throws(()=>projectAccessibleGraph(()=>[{...node("a",0),run:"execute"}]),/denied/);
 assert.throws(()=>projectAccessibleGraph(()=>[node("a",0),node("a",10)]),/denied/);
 assert.throws(()=>projectAccessibleGraph(()=>Array(MAX_A11Y_NODES+1).fill(node("x",0))),/denied/);
 assert.throws(()=>projectAccessibleGraph(()=>[{...node("x",0),label:"a".repeat(121)}]),/denied/);
 assert.throws(()=>projectAccessibleGraph(()=>[{...node("x",0),x:Infinity}]),/denied/);
});
test("native SVG fixture: keyboard focus selection and bounded visual zoom callback",()=>{
 const svg=svgFixture(),selected=[],zoom=[];
 const backing=[node("a",0),node("b",300),node("c",600)];
 const controls=mountGraphAccessibility({svg,readGraph:()=>backing,
   readViewport:()=>({x:1,y:2,zoom:4.9}),
   onSelect:v=>selected.push(v),onZoom:v=>zoom.push(v)});
 assert.equal(svg.children.length,0,"no native Canvas auto-mount");
 controls.refresh();
 assert.equal(controls.count(),3);
 const [a,b,c]=svg.children;
 assert.equal(a.attrs.role,"button");
 assert.equal(a.attrs["aria-label"],"Terminal a");
 a.focus();assert.equal(controls.selected(),"a");
 a.emit("keydown",{key:"ArrowRight"});
 assert.equal(controls.selected(),"b");
 b.emit("keydown",{key:"Enter"});
 assert.deepEqual(selected,[{id:"b",visualOnly:true}]);
 c.emit("keydown",{key:"+"});
 assert.equal(zoom.at(-1).zoom,5);
 c.emit("keydown",{key:"-"});
 assert.ok(zoom.at(-1).zoom<4.9);
 c.emit("keydown",{key:"Home"});
 assert.equal(controls.selected(),"a");
 assert.equal(a.attrs["aria-pressed"],"true");
 assert.equal(b.attrs["aria-pressed"],"false");
 controls.dispose();
 assert.equal(svg.children.length,0);
 assert.equal(a.listeners.size,0);
 assert.throws(()=>controls.refresh(),/denied/);
});
test("viewport read-only and reduced-motion disable CSS transitions; removal frees focus",()=>{
 const svg=svgFixture();let nodes=[node("n1",10),node("n2",20)];
 const original=JSON.stringify(nodes);
 const controls=mountGraphAccessibility({svg,readGraph:()=>nodes,
   readViewport:()=>({x:0,y:0,zoom:1}),reducedMotion:true});
 controls.refresh();
 assert.match(svg.children[0].attrs.style,/transition:none/);
 svg.children[1].focus();assert.equal(controls.selected(),"n2");
 nodes=[node("n1",10)];controls.refresh();
 assert.equal(controls.selected(),null);
 assert.equal(controls.count(),1);
 assert.equal(JSON.stringify([node("n1",10),node("n2",20)]),original);
 controls.dispose();
 assert.equal(svg.children.length,0);
});
