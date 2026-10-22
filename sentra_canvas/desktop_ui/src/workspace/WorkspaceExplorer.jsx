// File explorer presentation follows ORCA FileExplorerRow at the pinned MIT
// source. Reads remain scoped to the existing SENTRA project_file_* bridge.
import React,{useEffect,useRef,useState} from 'react';
import {Files,GitBranch,Activity,ChevronRight,Folder,FileText,RefreshCw} from 'lucide-react';

export function WorkspaceExplorer({bridge,projectId,onOpen,onReview,onActivity,fileScope={}}){
 const [rows,setRows]=useState([]),[children,setChildren]=useState({}),[expanded,setExpanded]=useState(new Set()),[error,setError]=useState(''),[selected,setSelected]=useState('');
 const [identity,setIdentity]=useState({}),[loadedScope,setLoadedScope]=useState(null);
 const revision=useRef(0),scopeKey=JSON.stringify(fileScope);
 async function load(){const ticket=++revision.current;setLoadedScope(null);try{const value=await bridge({action:'project_file_list',project_id:projectId,...fileScope,path:''});if(ticket===revision.current){setRows(value.items||[]);setIdentity({execution_workspace_id:value.execution_workspace_id||'project'});setLoadedScope(scopeKey);setChildren({});setExpanded(new Set());setError('')}}catch(e){if(ticket===revision.current)setError(e.message)}}
 useEffect(()=>{void load();return()=>{revision.current++}},[projectId,bridge,scopeKey]);
 async function toggle(row){if(loadedScope!==scopeKey)return;if(!row.directory){setSelected(row.path);onOpen(row.path,identity);return}if(expanded.has(row.path)){setExpanded(s=>{const n=new Set(s);n.delete(row.path);return n});return}const ticket=revision.current;try{const value=await bridge({action:'project_file_list',project_id:projectId,...fileScope,...identity,path:row.path});if(ticket!==revision.current)return;setChildren(s=>({...s,[row.path]:value.items||[]}));setExpanded(s=>new Set([...s,row.path]));setError('')}catch(e){if(ticket===revision.current)setError(e.message)}}
 function tree(items,depth=0){return items.map(row=><React.Fragment key={row.path}><button className="sw-file-row" role="treeitem" aria-level={depth+1} aria-expanded={row.directory?expanded.has(row.path):undefined} aria-selected={selected===row.path} style={{paddingLeft:10+depth*13}} onClick={()=>void toggle(row)}><ChevronRight size={11} style={{opacity:row.directory?1:0,transform:expanded.has(row.path)?'rotate(90deg)':undefined}}/>{row.directory?<Folder size={13}/>:<FileText size={13}/>}<span>{row.name}</span></button>{expanded.has(row.path)&&tree(children[row.path]||[],depth+1)}</React.Fragment>)}
 return <aside className="sw-explorer" aria-label="Explorador do Canvas"><nav><button aria-label="Explorador de arquivos" aria-current="page"><Files size={15}/></button><button aria-label="Revisão Git" onClick={onReview}><GitBranch size={15}/></button><button aria-label="Atividade do Dot" onClick={onActivity}><Activity size={15}/></button></nav><header><strong>Arquivos do projeto</strong><button aria-label="Atualizar explorador" onClick={load}><RefreshCw size={12}/></button></header>{error?<p role="alert">{error}</p>:loadedScope!==scopeKey?<p role="status">Consultando arquivos deste trabalho…</p>:<div role="tree" aria-label="Arquivos">{tree(rows)}{!rows.length&&<p>Nenhum arquivo neste projeto.</p>}</div>}<footer>Projeto autorizado pelo SENTRA</footer></aside>;
}

export function WorkspaceFile({bridge,projectId,path,fileScope={}}){
 const [file,setFile]=useState(null),[error,setError]=useState('');const scopeKey=JSON.stringify(fileScope);
 useEffect(()=>{let alive=true;setFile(null);setError('');bridge({action:'project_file_preview',project_id:projectId,...fileScope,path}).then(v=>{if(alive)setFile(v)}).catch(e=>{if(alive)setError(e.message)});return()=>{alive=false}},[projectId,path,bridge,scopeKey]);
 return <section className="sw-file-preview"><header><FileText size={13}/><span>{path}</span><small>{file?.branch||'Leitura'}</small></header>{error?<p role="alert">{error}</p>:file?<div className="sw-code-lines">{String(file.content??file.text??'').split('\n').map((line,i)=><div key={i}><span aria-hidden>{i+1}</span><code>{line||' '}</code></div>)}</div>:<p role="status">Abrindo arquivo…</p>}</section>;
}
