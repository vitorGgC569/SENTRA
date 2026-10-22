import React, { useEffect, useMemo, useRef } from 'react';
import { mascotMotionState } from './dot-motion';
import { DOT_COMPANIONS, companionIdFor, createCompanion } from './dot-companion-engine';
import './dot-companion.css';

// Old saved IDs (blue/mint/orange/purple) remain valid and now display animated characters.
export const DOT_MASCOTS=DOT_COMPANIONS.map(item=>({id:item.id,label:item.label}));
export const mascotFor=companionIdFor;

export function companionMood(status, execution) {
  const phase=mascotMotionState(status, execution);
  if(phase==='working')return 'work';
  if(phase==='needs-input')return 'wait';
  if(phase==='paused')return 'sleep';
  // A success animation requires explicit completion evidence from the host.
  if(phase==='complete')return execution?.verified===true?'done':'idle';
  const value=String(status||'').toLowerCase();
  if(['thinking','reasoning'].includes(value))return 'think';
  if(['listening'].includes(value))return 'listen';
  if(['responding','speaking'].includes(value))return 'speak';
  if(['failed','error','expired'].includes(value))return 'error';
  return 'idle';
}
export function DotMascot({ identity, mascot, name='Dot', status, execution, size='small', decorative=false }) {
  const canvas=useRef(null);
  const instance=useRef(null);
  const id=useMemo(()=>DOT_MASCOTS.some(x=>x.id===mascot)?mascot:mascotFor(identity),[mascot,identity]);
  const mood=companionMood(status,execution);
  useEffect(()=>{
    if(!canvas.current)return;
    const current=createCompanion(canvas.current,id,mood);
    instance.current=current;
    return ()=>{current.destroy();if(instance.current===current)instance.current=null;};
  },[id]);
  useEffect(()=>instance.current?.update(mood),[mood,id]);
  return <span className={'shell-mascot '+size+' dot-companion'} data-companion={id} data-state={mood}
    role={decorative?undefined:'img'} aria-hidden={decorative||undefined}
    aria-label={decorative?undefined:name+(status?' · '+status:'')}>
    <canvas ref={canvas} aria-hidden="true" />
  </span>;
}
