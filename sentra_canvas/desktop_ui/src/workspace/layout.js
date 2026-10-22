// Tree representation adapted from ORCA src/shared/tab-types.ts at 70b2197c.
// Copyright (c) 2026 Lovecast Inc. MIT; see vendor/orca/LICENSE.
export const KINDS = ['map','terminals','files','review','browser','computer','activity'];
export const leaf = id => ({type:'leaf',groupId:id});
export function groups(node){return node.type==='leaf'?[node.groupId]:[...groups(node.first),...groups(node.second)];}
export function updateTree(node,id,replace){return node.type==='leaf'?(node.groupId===id?replace(node):node):{...node,first:updateTree(node.first,id,replace),second:updateTree(node.second,id,replace)};}
export function removeGroup(node,id){if(node.type==='leaf')return node.groupId===id?null:node;const first=removeGroup(node.first,id),second=removeGroup(node.second,id);return !first?second:!second?first:{...node,first,second};}
export function setRatio(node,path,ratio){if(!path.length)return {...node,ratio:Math.max(.15,Math.min(.85,ratio))};const [side,...tail]=path;return {...node,[side]:setRatio(node[side],tail,ratio)};}
export function initialLayout(){return {version:1,tree:leaf('main'),panes:{main:{tabs:KINDS.map(kind=>({id:kind,kind})),active:'terminals'}},focused:'main'};}
export function validateLayout(value){
 if(!value||value.version!==1||!value.tree||!value.panes)return false;
 let count=0;const ids=new Set();function check(n,depth=0){if(!n||++count>31||depth>8)return false;if(n.type==='leaf'){if(typeof n.groupId!=='string'||n.groupId.length>80||ids.has(n.groupId))return false;ids.add(n.groupId);const pane=value.panes[n.groupId];return !!pane&&Array.isArray(pane.tabs)&&pane.tabs.length<=30&&pane.tabs.every(t=>t&&typeof t.id==='string'&&t.id.length<256&&KINDS.includes(t.kind)&&(!t.resourceId||typeof t.resourceId==='string'&&t.resourceId.length<=128)&&(!t.dotId||typeof t.dotId==='string'&&t.dotId.length<=128)&&['conversationId','executionWorkspaceId'].every(k=>!(k in t)||typeof t[k]==='string'&&t[k].length>0&&t[k].length<=128))&&new Set(pane.tabs.map(t=>t.id)).size===pane.tabs.length&&(!pane.active||pane.tabs.some(t=>t.id===pane.active));}return n.type==='split'&&['horizontal','vertical'].includes(n.direction)&&Number.isFinite(n.ratio)&&n.ratio>=.15&&n.ratio<=.85&&check(n.first,depth+1)&&check(n.second,depth+1);}
 return check(value.tree)&&ids.has(value.focused)&&Object.keys(value.panes).length===ids.size;
}
export function restoreLayout(storage,key,fallback=initialLayout){try{const raw=storage?.getItem('sentra-workspace-v1:'+key);if(raw&&raw.length<64000){const value=JSON.parse(raw);if(validateLayout(value))return value;}}catch{}return fallback();}
export function saveLayout(storage,key,value){if(!validateLayout(value))throw Error('Invalid workspace layout');try{storage?.setItem('sentra-workspace-v1:'+key,JSON.stringify(value));}catch{/* Quota/private mode affects layout only. */}}
export function moveTab(state,from,to,id,before){
 const source=state.panes[from],target=state.panes[to];if(!source||!target)return state;
 const tab=source.tabs.find(t=>t.id===id);if(!tab||from!==to&&target.tabs.length>=30)return state;
 const panes={...state.panes,[from]:{...source,tabs:source.tabs.filter(t=>t.id!==id)}};
 const dest=from===to?panes[from]:target;const tabs=dest.tabs.filter(t=>t.id!==id);let at=tabs.findIndex(t=>t.id===before);if(at<0)at=tabs.length;tabs.splice(at,0,tab);
 panes[to]={...dest,tabs,active:id};if(from!==to&&source.active===id)panes[from].active=panes[from].tabs.at(-1)?.id||null;
 return {...state,panes,focused:to};
}

// Edge drops are a single presentation transaction. They never create sessions.
export function dropTabAtEdge(state,from,to,id,edge,newId){
 if(!['left','right','top','bottom'].includes(edge)||!state.panes[to]||!state.panes[from]?.tabs.some(t=>t.id===id)||groups(state.tree).length>=8||state.panes[newId])return state;
 const before=['left','top'].includes(edge),next=leaf(newId);
 const split=old=>({type:'split',direction:['left','right'].includes(edge)?'horizontal':'vertical',ratio:.5,first:before?next:old,second:before?old:next});
 const prepared={...state,tree:updateTree(state.tree,to,split),panes:{...state.panes,[newId]:{tabs:[],active:null}}};
 return moveTab(prepared,from,newId,id);
}
export function dropEdge(rect,x,y){
 const dx=Math.min(48,rect.width*.2),dy=Math.min(48,rect.height*.2);
 const choices=[['left',(x-rect.left)/dx],['right',(rect.right-x)/dx],['top',(y-rect.top)/dy],['bottom',(rect.bottom-y)/dy]].filter(([,distance])=>distance>=0&&distance<=1).sort((a,b)=>a[1]-b[1]);
 return choices[0]?.[0]||null;
}
