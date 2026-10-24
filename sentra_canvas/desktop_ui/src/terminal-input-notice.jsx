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
 const control=state?.inputControl;
 const owned=control?.available&&control.live&&control.client_id===control.viewer_client_id;
 async function changeControl(action){
  setBusy(true);try{
   await pool.controlInput(ws,id,action);
   setNotice(action==='release'?'Controle liberado. A entrada desta janela está pausada.':'Controle conferido. Revise a saída antes de continuar.');
  }catch(error){setNotice(error.message)}finally{setBusy(false)}
 }
 if(!state?.inputBlocked&&!notice&&!unsupported){
  if(!owned)return null;
  return <div className="terminal-control-status nodrag nopan nowheel"><span>Entrada nesta janela</span><button disabled={busy||state.inputBusy} onClick={()=>changeControl('release')}>Liberar controle</button></div>;
 }
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
  <span>{state?.inputJournalError||notice||(control?.available&&control.can_write===false?
   (control.client_id?.startsWith('mobile:')?'O celular está usando este terminal.':control.client_id?.startsWith('agent:')?'Um Dot está usando este terminal.':'Outra janela está usando este terminal.'):
   unsupported?'Este host não oferece entrada com confirmação recuperável. Atualize a instância experimental.':'Entrada interrompida. Confira a sessão antes de continuar.')}</span>
  {control?.available&&control.pending_confirmation&&!pending.length&&<button disabled={busy||state.inputBusy} onClick={()=>changeControl('observe')}>Consultar confirmação</button>}
  {control?.available&&control.can_write===false&&!control.pending_confirmation&&<button disabled={busy||state.inputBusy} onClick={()=>changeControl('takeover')}>Assumir controle nesta janela</button>}
  {owned&&<button disabled={busy||state.inputBusy} onClick={()=>changeControl('release')}>Liberar controle</button>}
  {pending.length?<><button disabled={busy||state.inputBusy} onClick={()=>inspect(pending)}>{pending.length>1?`Conferir ${pending.length} entradas`:'Consultar confirmação'}</button>
   {pending.length>1&&<details className="terminal-input-pending-list"><summary>Ver entradas pendentes</summary><ul>{pending.map((row,index)=><li key={row.request_key}>
    <span>Entrada {index+1}{row.input_target!==state.inputTarget?' · outra conexão':''}</span>
    <button disabled={busy||state.inputBusy} onClick={()=>inspect([row])}>Conferir entrada {index+1}</button>
   </li>)}</ul></details>}
   {state.inputPendingOverflow&&<small>Há mais confirmações no host. As próximas aparecem após conferir estas entradas.</small>}</>:
   state?.inputBlocked&&<button disabled={busy||state.inputBusy} onClick={async()=>{if(await pool.resumeInput(ws,id))setNotice('');else setNotice('Aguarde a sessão ficar disponível e confira a confirmação.')}}>Continuar digitando</button>}
 </div>;
}
