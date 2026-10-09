/** Explicitly mounted, read-only native SVG accessibility projection.
 * Input MUST be provided by the authoritative SENTRA host graph, never Yjs.
 * Selection is only a UI indication, never link creation or Run/Grant/Lease.
 */
const denied=()=>{throw Error("collaboration-denied");};
const id=/^[A-Za-z0-9_-]{1,80}$/;
const finite=n=>typeof n==="number"&&Number.isFinite(n);
const within=(n,lo,hi)=>finite(n)&&n>=lo&&n<=hi;
export const MAX_A11Y_NODES=256;
export function projectAccessibleGraph(readGraph){
  if(typeof readGraph!=="function")denied();
  const graph=readGraph();
  if(!Array.isArray(graph)||graph.length>MAX_A11Y_NODES)denied();
  const seen=new Set();
  return Object.freeze(graph.map(n=>{
    if(!n||Object.keys(n).sort().join(",")!=="height,id,label,width,x,y"||
      typeof n.id!=="string"||!id.test(n.id)||seen.has(n.id)||
      typeof n.label!=="string"||n.label.length<1||n.label.length>120||
      !within(n.x,-1e6,1e6)||!within(n.y,-1e6,1e6)||
      !within(n.width,60,2000)||!within(n.height,40,1600))denied();
    seen.add(n.id);
    return Object.freeze({id:n.id,label:n.label,x:n.x,y:n.y,
      width:n.width,height:n.height});
  }));
}
export function mountGraphAccessibility({svg,readGraph,readViewport,
  onSelect=()=>{},onZoom=()=>{},reducedMotion=false}={}){
  if(svg?.namespaceURI!=="http://www.w3.org/2000/svg"||
    typeof svg?.ownerDocument?.createElementNS!=="function"||
    typeof readGraph!=="function"||typeof readViewport!=="function"||
    typeof onSelect!=="function"||typeof onZoom!=="function"||
    typeof reducedMotion!=="boolean")denied();
  const ns="http://www.w3.org/2000/svg";
  const elements=new Map();let active=null,closed=false;
  const view=()=>{
    const v=readViewport();
    if(!v||Object.keys(v).sort().join(",")!=="x,y,zoom"||
       !within(v.x,-1e6,1e6)||!within(v.y,-1e6,1e6)||
       !within(v.zoom,0.1,5))denied();
    return Object.freeze({...v});
  };
  let projection=Object.freeze([]);
  function refresh(){
    if(closed)denied();
    projection=projectAccessibleGraph(readGraph);
    const live=new Set(projection.map(n=>n.id));
    for(const [key,elem] of elements)if(!live.has(key)){
      elem.node.remove();elements.delete(key);
    }
    if(!live.has(active))active=null;
    for(const n of projection){
      let el=elements.get(n.id);
      if(!el){
        const node=svg.ownerDocument.createElementNS(ns,"g");
        const shape=svg.ownerDocument.createElementNS(ns,"rect");
        node.appendChild(shape);svg.appendChild(node);
        const onKey=e=>{
          if(closed)return;
          if(e.key==="Enter"||e.key===" "){
            e.preventDefault();active=n.id;sync();
            onSelect(Object.freeze({id:n.id,visualOnly:true}));return;
          }
          const at=projection.findIndex(x=>x.id===n.id);
          const moves={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1};
          let target=null;
          if(Object.hasOwn(moves,e.key))
            target=projection[(at+moves[e.key]+projection.length)%projection.length];
          else if(e.key==="Home")target=projection[0];
          else if(e.key==="End")target=projection.at(-1);
          if(target){
            e.preventDefault();elements.get(target.id)?.node.focus();
            active=target.id;sync();return;
          }
          if(e.key==="+"||e.key==="="||e.key==="-"){
            e.preventDefault();
            const v=view();const step=e.key==="-"?1/1.2:1.2;
            const zoom=Math.min(5,Math.max(0.1,Math.round(v.zoom*step*1e4)/1e4));
            // Host decides whether/how to apply a viewport change.
            onZoom(Object.freeze({...v,zoom,visualOnly:true}));
          }
        };
        const onFocus=()=>{if(!closed){active=n.id;sync();}};
        node.addEventListener("keydown",onKey);
        node.addEventListener("focus",onFocus);
        el={node,shape,onKey,onFocus};
        elements.set(n.id,el);
      }
      el.node.setAttribute("tabindex","0");
      el.node.setAttribute("role","button");
      el.node.setAttribute("aria-label",n.label);
      el.node.setAttribute("data-visual-only","true");
      el.node.setAttribute("style",reducedMotion?"transition:none":"transition:transform 80ms ease-out");
      el.shape.setAttribute("x",String(n.x));
      el.shape.setAttribute("y",String(n.y));
      el.shape.setAttribute("width",String(n.width));
      el.shape.setAttribute("height",String(n.height));
      el.shape.setAttribute("fill","transparent");
    }
    sync();view();
  }
  function sync(){
    for(const [id,el] of elements)
      el.node.setAttribute("aria-pressed",String(id===active));
  }
  function dispose(){
    if(closed)return;closed=true;
    for(const {node,onKey,onFocus} of elements.values()){
      node.removeEventListener("keydown",onKey);
      node.removeEventListener("focus",onFocus);node.remove();
    }
    elements.clear();projection=Object.freeze([]);active=null;
  }
  return Object.freeze({refresh,dispose,selected:()=>active,count:()=>elements.size});
}
