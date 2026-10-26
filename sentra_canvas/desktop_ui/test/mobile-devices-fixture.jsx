// Isolated browser fixture: the browser test intercepts every control request.
import React from 'react';
import {createRoot} from 'react-dom/client';
import '../src/desktop.css';
import '../src/shell-polish.css';
import '../src/workspace/workspace.css';
import '../src/shell-coucou-macos.css';

sessionStorage.setItem('sentra_native_token','fixture-token');
const {MobileDevices}=await import('../src/workspace/MobileDevices');
const dot={name:'Dot de teste',project_id:'fixture-project',space_id:'fixture-space',dot_id:'fixture-dot'};
const root=createRoot(document.getElementById('root'));
root.render(<React.StrictMode><MobileDevices dot={dot} onClose={()=>root.unmount()}/></React.StrictMode>);
