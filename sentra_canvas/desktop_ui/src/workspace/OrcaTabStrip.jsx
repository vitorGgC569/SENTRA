/* Adapted from ORCA SortableTab.tsx, tab-bar-surface.tsx and tab-width-rules.ts
 * at 70b2197c97b164b16c618736a107967295e5af92. Copyright (c) 2026 Lovecast Inc.
 * MIT: vendor/orca/LICENSE. Tailwind/store/DnD dependencies replaced by scoped
 * CSS and SENTRA presentation callbacks; no provider execution is imported. */
import React from 'react';
import {Plus,X,Columns2,Rows2,Maximize2,Minimize2} from 'lucide-react';

export function OrcaTabStrip({id,group,labels,icons,title,onActivate,onClose,onSplit,onMaximize,maximized,onCloseGroup,canClose,onDragStart,onDragEnd,onDrop,onKeys,onAdd}){
 return <header className="sw-tabs" onDragOver={e=>e.preventDefault()} onDrop={e=>onDrop(e,id)}>
  <div role="tablist" aria-label="Abas do painel" onKeyDown={e=>onKeys(e,id)}>
   {group.tabs.map(tab=>{const Icon=icons[tab.kind];const selected=group.active===tab.id;const name=title(tab);return <div className="sw-orca-tab" key={tab.id} data-active={selected} draggable onDragStart={e=>onDragStart(e,id,tab.id)} onDragEnd={onDragEnd} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.stopPropagation();onDrop(e,id,tab.id)}} onAuxClick={e=>{if(e.button===1){e.preventDefault();onClose(id,tab.id)}}}>
    <button role="tab" tabIndex={selected?0:-1} id={id+'-tab-'+tab.id} aria-controls={id+'-surface-'+tab.id} aria-selected={selected} title={name} onClick={()=>onActivate(id,tab.id)}><Icon size={13}/><span>{name}</span></button>
    <button className="sw-close-tab" aria-label={'Fechar aba '+name} onClick={()=>onClose(id,tab.id)}><X size={12}/></button>
   </div>})}
   <button className="sw-add-tab" aria-label="Adicionar aba" onClick={()=>onAdd(id)}><Plus size={14}/></button>
  </div>
  <div className="sw-pane-actions"><button aria-label="Dividir lado a lado" onClick={()=>onSplit(id,'horizontal')}><Columns2 size={14}/></button><button aria-label="Dividir acima e abaixo" onClick={()=>onSplit(id,'vertical')}><Rows2 size={14}/></button><button aria-label={maximized?'Restaurar painel':'Maximizar painel'} onClick={onMaximize}>{maximized?<Minimize2 size={13}/>:<Maximize2 size={13}/>}</button>{canClose&&<button aria-label="Fechar painel sem encerrar sessões" onClick={()=>onCloseGroup(id)}><X size={13}/></button>}</div>
 </header>;
}
