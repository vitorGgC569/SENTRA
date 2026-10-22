export function stageConversationDraft(storage,conversation,text){
 if(typeof text!=='string'||!text.trim()||text.length>100000)return false;
 const key='sentra_shell_draft:'+conversation.project_id+':'+conversation.conversation_id;
 try{const old=JSON.parse(storage.getItem(key)||'null')||{};if(old.content?.trim()||old.pending||old.pendingAttachment)return false;storage.setItem(key,JSON.stringify({...old,content:text,pending:null}));return true}catch{return false}
}
