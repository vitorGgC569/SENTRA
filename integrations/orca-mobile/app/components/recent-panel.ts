/** A recent desktop panel is a navigation hint, never authority or a replay. */
export function recentMobilePanel(profile:any,inventory:any,dotId:string){
 const terminals=inventory?.resources?.terminals||[];
 for(const tab of profile?.recent||[]){
  if(!tab||tab.dotId&&tab.dotId!==dotId)continue;
  if(tab.kind==='terminals'&&tab.resourceId&&!terminals.some((t:any)=>t.id===tab.resourceId&&(!t.dot_id||t.dot_id===dotId)))continue;
  const screen=({terminals:'terminal',files:'files',browser:'browser',computer:'computer',map:'workspace',review:'workspace',activity:'workspace'} as Record<string,string>)[tab.kind];
  if(screen)return {screen,conversationId:tab.conversationId||null,label:profile?.sessionNames?.[tab.resourceId]||({terminals:'sessões',files:'arquivos',browser:'navegador',computer:'computador',map:'workspace',review:'revisão',activity:'atividade'} as Record<string,string>)[tab.kind]};
 }
 return null;
}
