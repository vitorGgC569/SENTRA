import React,{useEffect,useMemo,useState} from 'react';
import {WorkspaceRequestJournal,inspectionRequest} from './request-journal';
import {acknowledgeVerifiedPending} from '../shell-bridge';
const changed=()=>window.dispatchEvent(new Event('sentra:workspace-intents'));

export function useWorkspaceEffects(layoutScope,scope,bridge){
 const journal=useMemo(()=>layoutScope?new WorkspaceRequestJournal(layoutScope,{changed}):null,[layoutScope]);
 const [pending,setPending]=useState([]),[error,setError]=useState(''),[inspecting,setInspecting]=useState('');
 function read(){try{setPending(journal?.list()||[]);setError('')}catch(e){setError(e.message)}}
 useEffect(()=>{read();window.addEventListener('sentra:workspace-intents',read);window.addEventListener('storage',read);return()=>{window.removeEventListener('sentra:workspace-intents',read);window.removeEventListener('storage',read)}},[journal]);
 async function inspect(row){
  if(!journal)throw Error('Inventário não confirmado.');
  setInspecting(row.request_key);
  try{const value=await bridge(inspectionRequest(scope,row,journal.selector(row)));if(value.resolved){await journal.resolve(row,value);acknowledgeVerifiedPending([row.request_key])}return value}finally{setInspecting('');read()}
 }
 async function run(request,slot){
  if(!journal)throw Error('Inventário não confirmado.');
  const row=await journal.begin(request,slot);read();
  // Any transport/host/storage failure leaves the original selector durable.
  const value=await bridge(request);
  const observation=await inspect(row);
  return {value,observation};
 }
 return {pending,error,inspecting,run,inspect,ready:!!journal&&!error};
}

export function WorkspacePending({effects,onObserved}){
 const [message,setMessage]=useState('');
 return <>{effects.error&&<div className="sw-error" role="alert">{effects.error}</div>}{effects.pending.length>0&&<details className="sw-pending" open><summary>{effects.pending.length} pedido(s) aguardando confirmação</summary>{effects.pending.map(row=><div key={row.request_key}><span>{row.action}<small>{row.request_key}</small></span><button disabled={!!effects.inspecting} onClick={async()=>{try{const value=await effects.inspect(row);setMessage(value.resolved?'Pedido consultado e confirmado. Nenhuma ação foi reenviada.':'O resultado permanece incerto. Nenhuma ação foi reenviada.');onObserved?.(value)}catch(e){setMessage(e.message)}}}>Consultar sem reenviar</button></div>)}{message&&<p role="status">{message}</p>}</details>}</>;
}
