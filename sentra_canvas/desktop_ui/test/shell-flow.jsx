// Whole-shell fixture: production components, explicit local API substitution.
import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import * as Tooltip from '@radix-ui/react-tooltip';
import {OpenDotsShell} from '../src/shell-app';
import {DesktopContext} from '../src/context';
import {TerminalPool} from '../src/terminal-pool';
import '@xyflow/react/dist/style.css';
import '@xterm/xterm/css/xterm.css';
import '../src/desktop.css';
import '../src/shell-polish.css';
const scope={project_id:'project-preview',space_id:'space-preview',dot_id:'dot-preview',conversation_id:'conversation-dot-preview'};
localStorage.setItem('sentra_shell_navigation',JSON.stringify({...scope,view:'chat'}));localStorage.setItem('sentra-orca-workspace-enabled','1');
function Fixture(){const [pool]=useState(()=>new TerminalPool(()=>{},()=>{}));return <Tooltip.Provider><DesktopContext.Provider value={{pool}}><OpenDotsShell projectId={scope.project_id} workspaces={[{id:scope.project_id,name:'Fixture'}]} models={[]} onProject={()=>{}} onWorkspaceCreate={()=>{}} onCanvasActive={value=>pool.setOutputEnabled(value)} onTools={()=>{}}/></DesktopContext.Provider></Tooltip.Provider>}
createRoot(document.getElementById('root')).render(<Fixture/>);
