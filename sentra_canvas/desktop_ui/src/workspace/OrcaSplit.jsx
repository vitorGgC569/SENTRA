// Resize gesture adapted from ORCA TabGroupSplitNodeTree.tsx, commit 70b2197c.
// Copyright (c) 2026 Lovecast Inc. MIT; see vendor/orca/LICENSE.
// SENTRA changes: injected pane renderer, no global store, keyboard support.
import React,{useRef,useEffect} from 'react';
function ResizeHandle({direction,ratio,onChange}){
 const cleanup=useRef(null);useEffect(()=>()=>cleanup.current?.(),[]);
 function start(e){if(e.button!==0||cleanup.current)return;e.preventDefault();const handle=e.currentTarget,container=handle.parentElement,first=handle.previousElementSibling,second=handle.nextElementSibling;if(!container||!first||!second)return;handle.setPointerCapture(e.pointerId);let rect=container.getBoundingClientRect(),next=ratio;
 const observer=new ResizeObserver(()=>rect=container.getBoundingClientRect());observer.observe(container);
 const move=event=>{if(event.pointerId!==e.pointerId)return;next=Math.max(.15,Math.min(.85,direction==='horizontal'?(event.clientX-rect.left)/rect.width:(event.clientY-rect.top)/rect.height));first.style.flex=`${next} 1 0%`;second.style.flex=`${1-next} 1 0%`;};
 const finish=()=>{observer.disconnect();handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',finish);handle.removeEventListener('pointercancel',finish);handle.removeEventListener('lostpointercapture',finish);cleanup.current=null;onChange(next);};cleanup.current=finish;handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',finish);handle.addEventListener('lostpointercapture',finish);
 }
 return <div className={'sw-divider '+direction} role="separator" aria-label="Redimensionar painéis" aria-orientation={direction==='horizontal'?'vertical':'horizontal'} aria-valuemin={15} aria-valuemax={85} aria-valuenow={Math.round(ratio*100)} tabIndex={0} onPointerDown={start} onKeyDown={e=>{if(['ArrowLeft','ArrowUp','ArrowRight','ArrowDown'].includes(e.key)){e.preventDefault();onChange(Math.max(.15,Math.min(.85,ratio+(['ArrowRight','ArrowDown'].includes(e.key)?.05:-.05))));}}}/>;
}
export function OrcaSplit({node,path=[],onRatio,render}){if(node.type==='leaf')return render(node.groupId);return <div className={'sw-split '+node.direction}><div style={{flex:`${node.ratio} 1 0%`}}><OrcaSplit node={node.first} path={[...path,'first']} onRatio={onRatio} render={render}/></div><ResizeHandle direction={node.direction} ratio={node.ratio} onChange={r=>onRatio(path,r)}/><div style={{flex:`${1-node.ratio} 1 0%`}}><OrcaSplit node={node.second} path={[...path,'second']} onRatio={onRatio} render={render}/></div></div>;}
