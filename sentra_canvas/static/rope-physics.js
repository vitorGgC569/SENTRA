"use strict";
/* SENTRA cable dynamics: SVG + Verlet constraints, no UI framework/dependencies.
 * The graph remains authoritative; animation never changes or dispatches edges.
 */
(function (root) {
  const NS = "http://www.w3.org/2000/svg";
  const SEGMENTS = 12, MAX_TICKS = 180;
  const cables = new Map();
  let layer = null, pending = false, ticks = 0;
  const reduceMotion = () => !!root.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const valid = x => Number.isFinite(x) ? x : 0;
  const anchors = (a, b) => [
    {x: valid(a.x + a.width), y: valid(a.y + a.height / 2)},
    {x: valid(b.x), y: valid(b.y + b.height / 2)}
  ];
  function straight(a, b) {
    const len = Math.hypot(b.x-a.x, b.y-a.y);
    const sag = Math.min(66, Math.max(10, len * .15));
    const points = [];
    for (let i = 0; i <= SEGMENTS; i++) {
      const t = i / SEGMENTS;
      const x = a.x + (b.x-a.x)*t;
      const y = a.y + (b.y-a.y)*t + Math.sin(Math.PI*t)*sag;
      points.push({x,y,px:x,py:y});
    }
    return points;
  }
  function path(points) {
    if (!points.length) return "";
    let d = "M " + points[0].x.toFixed(2) + " " + points[0].y.toFixed(2);
    for (let i=1; i<points.length-1; i++) {
      const p=points[i],q=points[i+1];
      d += " Q "+p.x.toFixed(2)+" "+p.y.toFixed(2)+" "+
           ((p.x+q.x)/2).toFixed(2)+" "+((p.y+q.y)/2).toFixed(2);
    }
    const p=points[points.length-1];
    return d+" L "+p.x.toFixed(2)+" "+p.y.toFixed(2);
  }
  function pin(c) {
    const last=c.points.length-1;
    for(const [i,p] of [[0,c.start],[last,c.end]]){
      const q=c.points[i];q.x=q.px=p.x;q.y=q.py=p.y;
    }
  }
  function step(c) {
    const p=c.points,last=p.length-1;
    const span=Math.hypot(c.end.x-c.start.x,c.end.y-c.start.y);
    const rest=Math.max(3,span/last*1.13);
    for(let i=1;i<last;i++){
      const q=p[i],vx=(q.x-q.px)*.91,vy=(q.y-q.py)*.91;
      q.px=q.x;q.py=q.y;q.x+=vx;q.y+=vy+.5;
    }
    for(let iter=0;iter<8;iter++){
      pin(c);
      for(let i=0;i<last;i++){
        const a=p[i],b=p[i+1],dx=b.x-a.x,dy=b.y-a.y;
        const distance=Math.max(.001,Math.hypot(dx,dy));
        const adjust=(distance-rest)/distance;
        if(i===0){b.x-=dx*adjust;b.y-=dy*adjust;}
        else if(i+1===last){a.x+=dx*adjust;a.y+=dy*adjust;}
        else{a.x+=dx*adjust*.5;a.y+=dy*adjust*.5;b.x-=dx*adjust*.5;b.y-=dy*adjust*.5;}
      }
    }
    pin(c);
    if(p.some(q=>!Number.isFinite(q.x)||!Number.isFinite(q.y)||
          Math.abs(q.x)>1e6||Math.abs(q.y)>1e6))c.points=straight(c.start,c.end);
  }
  function frame() {
    pending=false;
    if(!layer || !layer.isConnected || root.document?.hidden)return;
    const animate=!reduceMotion();
    for(const c of cables.values()){
      if(animate)step(c);
      c.path.setAttribute("d",path(c.points));
    }
    if(animate && ++ticks < MAX_TICKS && cables.size)schedule();
  }
  function schedule() {
    if(!pending){pending=true;root.requestAnimationFrame(frame);}
  }
  function sync(target, links, nodes) {
    if(!target)return;
    layer=target;
    const table=new Map(nodes.map(n=>[String(n.id),n]));
    const active=new Set();
    let moved=false;
    for(const link of links){
      const a=table.get(String(link.source)),b=table.get(String(link.target));
      if(!a||!b)continue;
      const id=String(link.id),[start,end]=anchors(a,b);
      active.add(id);
      let c=cables.get(id);
      if(!c){
        const stroke=root.document.createElementNS(NS,"path");
        stroke.setAttribute("class","edge-line cable-line");
        stroke.dataset.edge=id;
        stroke.setAttribute("tabindex","0");
        stroke.setAttribute("role","button");
        stroke.setAttribute("aria-label","Conexão entre "+String(a.title||"nó")+" e "+String(b.title||"nó")+". Enter para remover.");
        target.appendChild(stroke);
        c={path:stroke,points:straight(start,end),start,end};
        cables.set(id,c);moved=true;
      }else if(c.start.x!==start.x||c.start.y!==start.y||
               c.end.x!==end.x||c.end.y!==end.y){
        c.start=start;c.end=end;moved=true;
      }
      c.path.classList.toggle("backward",end.x<start.x);
      if(reduceMotion()) {
        c.points=straight(start,end);
        c.path.setAttribute("d",path(c.points));
      }
    }
    for(const [id,c] of cables){
      if(!active.has(id)){c.path.remove();cables.delete(id);}
    }
    if(moved || (ticks===0 && cables.size)){ticks=0;schedule();}
  }
  function clear() {
    for(const c of cables.values())c.path.remove();
    cables.clear();layer=null;ticks=0;
  }
  root.SentraCablePhysics=Object.freeze({sync,clear});
})(window);
