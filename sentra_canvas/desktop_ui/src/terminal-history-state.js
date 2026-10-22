export function terminalHistoryLabel(value,fallback=''){
 if(value?.status==='history_restored')return value.tailUncertain?'Histórico recuperado · final não confirmado':'Histórico recuperado';
 if(value?.persistenceState==='pending')return 'Gravando histórico…';
 if(value?.persistenceState==='gap'||value?.persistenceGap)return 'Histórico parcial';
 if(value?.persistenceState==='failed'||value?.persisted===false)return 'Histórico não salvo';
 return fallback;
}
export function resetForOutput(value,previousCursor){
 return value.truncated===true||(Number.isFinite(value.cursor)&&value.cursor<previousCursor);
}
