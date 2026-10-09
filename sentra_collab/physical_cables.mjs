/** SENTRA CRIT-003: isolated, opt-in, display-only SVG cables; no side effects on import.
 * Visual endpoints come ONLY from readGraph(), an injected authoritative graph.
 * All velocity/control points are local ephemeral view state, never Yjs data.
 */
const deny=()=>{throw Error("collaboration-denied");};
const ID=/^[A-Za-z0-9_-]{1,80}$/;
const finite=(n,lo=-1e6,hi=1e6)=>typeof n==="number"&&Number.isFinite(n)&&n>=lo&&n<=hi;
const clamp=(n,lo,hi)=>Math.min(hi,Math.max(lo,n));
const round=n=>Number(n.toFixed(3));
export const MAX_CABLES=128;
function point(p){
  if(!p||Object.keys(p).sort().join(",")!=="x,y"||
     !finite(p.x)||!finite(p.y))deny();
  return Object.freeze({x:p.x,y:p.y});
}
/** Never accepts untrusted CRDT root as its source. */
export function authoritativeCables(readGraph) {
  if(typeof readGraph!=="function")deny();
  const input=readGraph();
  if(!Array.isArray(input)||input.length>MAX_CABLES)deny();
  const seen=new Set();
  return Object.freeze(input.map(edge=>{
    if(!edge||Object.keys(edge).sort().join(",")!=="id,source,target"||
       typeof edge.id!=="string"||!ID.test(edge.id)||seen.has(edge.id))deny();
    seen.add(edge.id);
    return Object.freeze({id:edge.id,source:point(edge.source),target:point(edge.target)});
  }));
}
export function bezierPath(source,target,{sag=0}={}){
  source=point(source);target=point(target);
  if(!finite(sag,-200,200))deny();
  const dx=target.x-source.x,dy=target.y-source.y;
  const c=Math.min(150,Math.max(20,Math.abs(dx)*0.4));
  const sign=dx>=0?1:-1;
  return `M ${round(source.x)} ${round(source.y)} C ${round(source.x+sign*c)} ${round(source.y+sag)} ${round(target.x-sign*c)} ${round(target.y+sag)} ${round(target.x)} ${round(target.y)}`;
}
/** Deterministic, stable, bounded spring relaxation for 10 rope samples. */
export function createCablePhysics(edge,{samples=10}={}){
  if(!Number.isInteger(samples)||samples<4||samples>16)deny();
  const {id,source,target}=authoritativeCables(()=>[edge])[0];
  const points=Array.from({length:samples},(_,i)=>{
    const t=i/(samples-1),x=source.x+(target.x-source.x)*t,y=source.y+(target.y-source.y)*t;
    return {x,y,vx:0,vy:0};
  });
  return {id,source,target,points};
}
export function stepCable(state,edge,dt=1/60){
  if(!state||!Array.isArray(state.points)||state.points.length<4||
     !finite(dt,0,1))deny();
  const next=authoritativeCables(()=>[edge])[0];
  const s=state.points,steps=clamp(dt,0,1/30);
  const stiffness=120,damping=Math.exp(-14*steps);
  let unsettled=false;
  for(let i=0;i<s.length;i++){
    const t=i/(s.length-1);
    const desiredX=next.source.x+(next.target.x-next.source.x)*t;
    const desiredY=next.source.y+(next.target.y-next.source.y)*t+
      Math.sin(t*Math.PI)*Math.min(32,Math.hypot(next.target.x-next.source.x,
      next.target.y-next.source.y)*0.08);
    const p=s[i];
    if(i===0||i===s.length-1){
      p.x=desiredX;p.y=desiredY;p.vx=0;p.vy=0;continue;
    }
    p.vx=(p.vx+(desiredX-p.x)*stiffness*steps)*damping;
    p.vy=(p.vy+(desiredY-p.y)*stiffness*steps)*damping;
    p.x=clamp(p.x+p.vx*steps,desiredX-80,desiredX+80);
    p.y=clamp(p.y+p.vy*steps,desiredY-80,desiredY+80);
    if(Math.abs(p.x-desiredX)+Math.abs(p.y-desiredY)+
       Math.abs(p.vx)*0.01+Math.abs(p.vy)*0.01>0.08)unsettled=true;
  }
  state.source=next.source;state.target=next.target;
  return unsettled;
}
export function ropePath(state){
  const points=state?.points;
  if(!Array.isArray(points)||points.length<4||points.length>16)deny();
  let out=`M ${round(points[0].x)} ${round(points[0].y)}`;
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i];
    if(!finite(a.x)||!finite(a.y)||!finite(b.x)||!finite(b.y))deny();
    out+=` Q ${round(a.x)} ${round(a.y)} ${round((a.x+b.x)/2)} ${round((a.y+b.y)/2)}`;
  }
  return out+` L ${round(points.at(-1).x)} ${round(points.at(-1).y)}`;
}
/** SVG only. Does not create DOM outside the explicitly supplied <svg> element.
 * The graph reader must be host-authorized and never derived from the CRDT.
 */
export function mountCableLayer({svg,readGraph,requestFrame,cancelFrame,reducedMotion=false}={}){
  if(!svg||svg.namespaceURI!=="http://www.w3.org/2000/svg"||
     typeof svg.ownerDocument?.createElementNS!=="function"||
     typeof requestFrame!=="function"||typeof cancelFrame!=="function"||
     typeof readGraph!=="function"||typeof reducedMotion!=="boolean")deny();
  let closed=false,frame=null,last=0;
  const nodes=new Map(),physics=new Map();
  const cleanup=()=>{
    for(const item of nodes.values())item.remove();
    nodes.clear();physics.clear();
  };
  function draw(time=0){
    if(closed)return;
    frame=null;
    const edges=authoritativeCables(readGraph),active=new Set();
    let moving=false;
    for(const edge of edges){
      active.add(edge.id);
      let path=nodes.get(edge.id);
      if(!path){
        path=svg.ownerDocument.createElementNS("http://www.w3.org/2000/svg","path");
        path.setAttribute("fill","none");
        path.setAttribute("pointer-events","none");
        path.setAttribute("aria-hidden","true");
        svg.appendChild(path);nodes.set(edge.id,path);
      }
      if(reducedMotion){
        path.setAttribute("d",bezierPath(edge.source,edge.target));
      }else{
        let state=physics.get(edge.id);
        if(!state){state=createCablePhysics(edge);physics.set(edge.id,state);}
        moving=stepCable(state,edge,last?clamp((time-last)/1000,0,1/30):1/60)||moving;
        path.setAttribute("d",ropePath(state));
      }
    }
    last=time;
    for(const [id,elem] of nodes)if(!active.has(id)){
      elem.remove();nodes.delete(id);physics.delete(id);
    }
    if(!reducedMotion&&moving)frame=requestFrame(draw);
  }
  return Object.freeze({
    refresh(){
      if(closed)deny();
      if(frame!==null){cancelFrame(frame);frame=null;}
      draw();
    },
    dispose(){
      if(closed)return;
      closed=true;
      if(frame!==null)cancelFrame(frame);
      frame=null;cleanup();
    },
    count:()=>nodes.size
  });
}
