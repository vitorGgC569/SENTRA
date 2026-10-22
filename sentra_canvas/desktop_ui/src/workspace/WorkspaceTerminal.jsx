import React,{useLayoutEffect,useSyncExternalStore} from 'react';
import {useDesktop} from '../context';
import {PtySlot} from '../nodes';
import {terminalHistoryLabel} from '../terminal-history-state';

// Presentation only: the existing pool owns the view and the SENTRA daemon
// owns the process. Leaving this workspace restores the previous view theme.
export function WorkspaceTerminal({projectId,terminal}){
 const {pool}=useDesktop();
 useSyncExternalStore(pool.subscribe,pool.snapshot,pool.snapshot);
 const state=pool.state(projectId,terminal.id);
 const label=state?.transportUnavailable?'Conexão indisponível':state?.checkpointUnavailable?'Imagem parcial · checkpoint indisponível':state?.status==='history_restored'
  ?terminalHistoryLabel(state)+' · somente leitura'
  :state?.persistenceState&&state.persistenceState!=='saved'?terminalHistoryLabel(state)
  :state?.status==='running'?'Processo em execução':state?.status==='exited'?'Processo encerrado':'Consultando sessão…';
 useLayoutEffect(()=>{const entry=pool.ensure(projectId,terminal),previous=entry.term.options.theme;
  entry.term.options.theme={...previous,background:'#0a0a0a',foreground:'#d4d4d8',brightBlack:'#929292'};
  return()=>{entry.term.options.theme=previous};
 },[pool,projectId,terminal.id]);
 return <div className="sw-terminal-view"><PtySlot ws={projectId} resource={terminal} priority={30}/><footer role="status">{label}{state?.scrollbackOmitted?' · histórico anterior limitado no checkpoint':''}</footer></div>;
}
