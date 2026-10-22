// Simulated host fixture only. Production drafts use DPAPI/keyring on the host.
import React from 'react';
import {createRoot} from 'react-dom/client';
import {WorkspaceFile} from '../src/workspace/WorkspaceExplorer';
import {textDigest} from '../src/workspace/file-editor-state';
import '../src/desktop.css';
import '../src/shell-polish.css';
import '../src/workspace/workspace.css';
const scope={project_id:'editor-project',space_id:'editor-space',dot_id:'editor-dot',conversation_id:'editor-conversation',execution_workspace_id:'project'};
const read=(key,fallback)=>JSON.parse(localStorage.getItem('fixture-host-'+key)||JSON.stringify(fallback));
const write=(key,value)=>localStorage.setItem('fixture-host-'+key,JSON.stringify(value));
const hostFile=()=>read('file','original\n');
const draft=()=>read('draft',{revision:0,draft:null});
window.fixture={setFile:value=>write('file',value),effects:()=>read('effects',0),hostDraft:draft};
async function bridge(p){
 if(p.action==='workspace_file_get')return {path:'sample.txt',content:hostFile(),sha256:await textDigest(hostFile()),editable:true,
  scope:'editor-file-scope',layout_scope:'editor-layout',execution_workspace_id:'project',editor:{machine_id:'editor-machine',work_item_id:'editor-work'},...draft()};
 if(p.action==='project_file_preview')return {content:hostFile(),sha256:await textDigest(hostFile()),editable:true,execution_workspace_id:'project'};
 if(p.action==='workspace_file_draft_save'){
  const old=draft();
  if(JSON.stringify(old.draft)===JSON.stringify(p.draft))return {saved:true,revision:old.revision};
  if(old.revision!==p.expected_revision)return {saved:false,conflict:true,revision:old.revision};
  const next={draft:p.draft,revision:old.revision+1};write('draft',next);return {saved:true,revision:next.revision};
 }
 if(p.action==='dot_computer_action'){
  const args=p.request.arguments;
  if(args.expected_sha256!==await textDigest(hostFile()))throw Error('fixture revision conflict');
  write('file',args.content);write('effects',read('effects',0)+1);
  const value={state:'SUCCEEDED',evidence:{sha256:await textDigest(args.content)}};write('result',value);
  write('request',p.request_key);
  if(read('effects',0)===1)throw Error('fixture lost acknowledgement');
  return value;
 }
 if(p.action==='workspace_request_status')return {request_key:p.selector.request_key,resolved:true,automatic_retry:false,operation:read('result',null)};
 throw Error('Unsupported editor fixture action '+p.action);
}
createRoot(document.getElementById('root')).render(<div className="opendots-shell sentra-workspace" style={{height:'100%'}}>
 <WorkspaceFile projectId={scope.project_id} fileScope={scope} path="sample.txt" bridge={bridge}/>
</div>);
