export const draftFor=file=>({base_sha256:file.sha256,base_content:file.content,content:file.content,anchor:0,head:0});
export const fileScope=(scope,id)=>({...scope,execution_workspace_id:id});
export const editorConflict=(file,draft)=>!!draft&&(!!file.file_error||file.sha256!==draft.base_sha256);
export async function textDigest(text,crypto=globalThis.crypto){const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));return Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('')}
export async function savedDraftMatches(operation,file,draft){
 const evidence=operation?.evidence?.payload||operation?.evidence||{};
 return operation?.state==='SUCCEEDED'&&!file.file_error&&!!draft&&evidence.sha256===file.sha256&&evidence.sha256===await textDigest(draft.content);
}
export function fileSaveRequest(scope,file,draft,path,key){
 if(!scope.project_id||!scope.space_id||!scope.dot_id||!scope.conversation_id||!file.execution_workspace_id||!file.editor?.machine_id||!file.editor?.work_item_id||!draft.base_sha256)throw Error('Identidade completa do trabalho necessária.');
 return {action:'dot_computer_action',project_id:scope.project_id,space_id:scope.space_id,dot_id:scope.dot_id,conversation_id:scope.conversation_id,request_key:key,
  request:{action:'machine_execute',machine_id:file.editor.machine_id,work_item_id:file.editor.work_item_id,capability_id:'workspace:file.write',
   arguments:{action:'edit',path,content:draft.content,expected_sha256:draft.base_sha256,execution_workspace_id:file.execution_workspace_id}}};
}

/** Serialized protected-draft CAS, with no storage of content in the renderer. */
export class FileDraftWriter{
 constructor(save,revision,onState=()=>{}){this.save=save;this.revision=revision;this.onState=onState;this.pending=undefined;this.running=null;this.timer=null;this.closed=false;this.error=null}
 schedule(value){if(this.closed||this.error)return;this.pending=JSON.stringify(value);clearTimeout(this.timer);this.onState('pending');this.timer=setTimeout(()=>void this.flush().catch(()=>{}),600)}
 async flush(){
  clearTimeout(this.timer);
  if(this.running)await this.running;
  if(this.error)throw this.error;
  if(this.pending===undefined)return;
  const wire=this.pending;this.pending=undefined;
  this.running=(async()=>{try{const value=await this.save(JSON.parse(wire),this.revision);if(value.saved!==true)throw Error('O rascunho mudou em outra janela. Compare a versão guardada antes de continuar.');this.revision=value.revision;this.onState('saved')}
   catch(error){this.error=error;this.onState('error',error);throw error}finally{this.running=null}})();
  await this.running;
  if(this.pending!==undefined)await this.flush();
 }
 async commit(value){if(this.closed)throw Error('Editor fechado.');this.pending=JSON.stringify(value);await this.flush()}
 close(){this.closed=true;clearTimeout(this.timer);void this.flush().catch(()=>{})}
}
