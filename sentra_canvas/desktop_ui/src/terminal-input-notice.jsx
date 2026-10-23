import React,{useEffect,useRef,useState,useSyncExternalStore} from 'react';

/** Inline recovery inside a terminal view; never sends the old input again. */
export function TerminalInputNotice({pool,ws,id}){
 useSyncExternalStore(pool.subscribe,pool.snapshot,pool.snapshot);
 const [busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 const request=useRef(0);
 useEffect(()=>{request.current++;setBusy(false);setNotice('');return()=>{request.current++}},[pool,ws,id]);
 const state=pool.state(ws,id);
 const pending=state?.inputPendings?.length?state.inputPendings:state?.inputPending?[state.inputPending]:[];
 const unsupported=state?.inputProtocol===false&&state.status==='running';
 if(!state?.inputBlocked&&!notice&&!unsupported)return null;
 async function inspect(rows){
  const generation=++request.current;setBusy(true);let confirmed=0,uncertain=0;const errors=[];
  for(const row of rows){
   if(request.current!==generation)return;
   try{const result=await pool.inspectInput(ws,id,row.request_key);if(result?.resolved)confirmed++;else uncertain++}
   catch(error){errors.push(error.message)}
  }
  if(request.current===generation){
   setNotice(errors.length?errors.join(' · '):uncertain?`${confirmed?confirmed+' pedido(s) conferido(s). ':''}${uncertain} entrega(s) ainda sem confirmação. Nenhuma entrada foi repetida.`:'Pedidos conferidos. Revise a saída antes de continuar digitando.');
   setBusy(false);
  }
 }
 return <div className="terminal-input-notice nodrag nopan nowheel" role="status">
  <span>{state?.inputJournalError||notice||(unsupported?'Este host não oferece entrada com confirmação recuperável. Atualize a instância experimental.':'Entrada interrompida. Confira a sessão antes de continuar.')}</span>
  {pending.length?<><button disabled={busy||state.inputBusy} onClick={()=>inspect(pending)}>{pending.length>1?`Conferir ${pending.length} entradas`:'Consultar confirmação'}</button>
   {pending.length>1&&<details className="terminal-input-pending-list"><summary>Ver entradas pendentes</summary><ul>{pending.map((row,index)=><li key={row.request_key}>
    <span>Entrada {index+1}{row.input_target!==state.inputTarget?' · outra conexão':''}</span>
    <button disabled={busy||state.inputBusy} onClick={()=>inspect([row])}>Conferir entrada {index+1}</button>
   </li>)}</ul></details>}
   {state.inputPendingOverflow&&<small>Há mais confirmações no host. As próximas aparecem após conferir estas entradas.</small>}</>:
   state?.inputBlocked&&<button disabled={busy||state.inputBusy} onClick={async()=>{if(await pool.resumeInput(ws,id))setNotice('');else setNotice('Aguarde a sessão ficar disponível e confira a confirmação.')}}>Continuar digitando</button>}
 </div>;
}
