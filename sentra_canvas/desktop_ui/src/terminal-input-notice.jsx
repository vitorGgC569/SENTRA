import React,{useState,useSyncExternalStore} from 'react';

/** Inline recovery inside a terminal view; never sends the old input again. */
export function TerminalInputNotice({pool,ws,id}){
 useSyncExternalStore(pool.subscribe,pool.snapshot,pool.snapshot);
 const [busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 const state=pool.state(ws,id);
 const unsupported=state?.inputProtocol===false&&state.status==='running';
 if(!state?.inputBlocked&&!notice&&!unsupported)return null;
 async function inspect(){setBusy(true);try{const result=await pool.inspectInput(ws,id);setNotice(result?.resolved?'Pedido conferido. Revise a saída antes de continuar digitando.':'A entrega permanece incerta. A entrada não foi repetida.')}catch(error){setNotice(error.message)}finally{setBusy(false)}}
 return <div className="terminal-input-notice nodrag nopan nowheel" role="status">
  <span>{state?.inputJournalError||notice||(unsupported?'Este host não oferece entrada com confirmação recuperável. Atualize a instância experimental.':'Entrada interrompida. Confira a sessão antes de continuar.')}</span>
  {state?.inputPending?<button disabled={busy||state.inputBusy} onClick={inspect}>Consultar confirmação</button>:
   state?.inputBlocked&&<button disabled={busy||state.inputBusy} onClick={async()=>{if(await pool.resumeInput(ws,id))setNotice('');else setNotice('Aguarde a sessão ficar disponível e confira a confirmação.')}}>Continuar digitando</button>}
 </div>;
}
