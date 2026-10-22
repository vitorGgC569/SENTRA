import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import * as Tooltip from '@radix-ui/react-tooltip';
import {OpenDotsShell} from '../src/shell-app';
import {DesktopContext} from '../src/context';
import {TerminalPool} from '../src/terminal-pool';
import {initialLayout,saveLayout} from '../src/workspace/layout';
import {terminals} from './orca-preview-api';
import '@xyflow/react/dist/style.css';
import '@xterm/xterm/css/xterm.css';
import '../src/desktop.css';
import '../src/shell-polish.css';
// Render the existing shell. Only this isolated origin uses fixture data.
const scope={project_id:'project-preview',space_id:'space-preview',dot_id:'dot-preview'};
localStorage.setItem('sentra_shell_navigation',JSON.stringify({...scope,view:'canvas'}));
localStorage.setItem('sentra-orca-workspace-enabled','1');
if(!localStorage.getItem('sentra-workspace-v1:qa-orca-inner-v2')){
 const state=initialLayout();
 state.tree={type:'split',direction:'horizontal',ratio:.55,first:{type:'leaf',groupId:'main'},second:{type:'split',direction:'vertical',ratio:.64,first:{type:'leaf',groupId:'review'},second:{type:'leaf',groupId:'build'}}};
 state.panes={main:{tabs:[{id:'terminals:demo-main',kind:'terminals',resourceId:'demo-main'},{id:'map',kind:'map'}],active:'terminals:demo-main'},review:{tabs:[{id:'terminals:demo-review',kind:'terminals',resourceId:'demo-review'},{id:'files',kind:'files'}],active:'terminals:demo-review'},build:{tabs:[{id:'terminals:demo-build',kind:'terminals',resourceId:'demo-build'},{id:'activity',kind:'activity'}],active:'terminals:demo-build'}};
 saveLayout(localStorage,'qa-orca-inner-v2',state);
}
function Preview(){
 const [pool]=useState(()=>new TerminalPool(()=>{},()=>{}));
 const [notice,setNotice]=useState('');
 useEffect(()=>{pool.setOutputEnabled(true);pool.reconcile(scope.project_id,terminals);return()=>pool.destroy()},[pool]);
 return <Tooltip.Provider><DesktopContext.Provider value={{pool}}>
  <OpenDotsShell projectId={scope.project_id} workspaces={[{id:scope.project_id,name:'Oxta'}]} models={[]} onProject={()=>{}} onWorkspaceCreate={()=>setNotice('Criação de projetos indisponível na prévia.')} onCanvasActive={value=>pool.setOutputEnabled(value)} onTools={()=>setNotice('Configurações reais preservadas. Esta é uma prévia visual.')} nativeControls={<span style={{fontSize:10,opacity:.6}}>Prévia isolada</span>}/>
  {notice&&<div role="status" style={{position:'fixed',bottom:16,left:'50%',background:'#242424',color:'#fafafa',padding:12,borderRadius:8,zIndex:100}} onClick={()=>setNotice('')}>{notice}</div>}
 </DesktopContext.Provider></Tooltip.Provider>;
}
const root=createRoot(document.getElementById('desktop-root'));
root.render(<Preview/>);
if(import.meta.hot)import.meta.hot.dispose(()=>root.unmount());
