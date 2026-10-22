/** Presentation only: never create a session or infer authority from its name. */
export function conversationResources(inventory,dot){
 const machines=(inventory?.machines||[]).filter(m=>m.agent_id===dot.agent_id);
 return {
  terminals:(inventory?.terminals||[]).filter(t=>t.dot_id===dot.dot_id),
  browser:machines.some(m=>m.kind==='browser'),
 };
}
export function newlyObservedTerminal(previous,current){
 return previous===null?null:current.find(t=>!previous.has(t.id)&&!['exited','closed','failed'].includes(String(t.status).toLowerCase()))||null;
}
