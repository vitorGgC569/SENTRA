// Presentation fixture only. Actual host/ConPTY and pool behavior have separate tests.
import React from 'react';
import {createRoot} from 'react-dom/client';
import {TerminalInputNotice} from '../src/terminal-input-notice';
import '../src/desktop.css';
import '../src/shell-polish.css';
import '../src/workspace/workspace.css';

const rows=Array.from({length:3},(_,i)=>({request_key:'fixture-pending-'+i,fingerprint:'a'.repeat(64),input_target:(i===0?'d':'e').repeat(32),created_at:i+1}));
const state={status:'running',inputProtocol:true,inputBlocked:'confirmation_pending',inputTarget:'e'.repeat(32),inputPendings:rows};
let revision=0;const listeners=new Set();let lastConfirmed=false;
const fixture=window.fixture={queries:[],physicalWrites:0,confirmLast:()=>{lastConfirmed=true}};
const pool={subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)},snapshot:()=>revision,state:()=>state,
 async inspectInput(ws,id,key){
  if(ws!=='fixture-project'||id!=='fixture-terminal')throw Error('Fixture scope mismatch');
  fixture.queries.push(key);const resolved=key!=='fixture-pending-2'||lastConfirmed;
  if(resolved){state.inputPendings=state.inputPendings.filter(row=>row.request_key!==key);state.inputBlocked=state.inputPendings.length?'confirmation_pending':'review_required';revision++;for(const fn of listeners)fn()}
  return {resolved,automatic_retry:false};
 },
 async resumeInput(){if(state.inputPendings.length)return false;state.inputBlocked=null;revision++;for(const fn of listeners)fn();return true}
};
createRoot(document.getElementById('root')).render(<div className="opendots-shell" style={{width:'100%',height:'100vh'}}><div className="sentra-workspace" style={{width:'100%',maxWidth:740,margin:'40px auto',height:'fit-content'}}><TerminalInputNotice pool={pool} ws="fixture-project" id="fixture-terminal"/></div></div>);
