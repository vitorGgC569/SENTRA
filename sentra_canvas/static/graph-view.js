/* Pure viewport projection. Culling never owns or closes process sessions. */
(function(root){
 "use strict";
 function visibleIDs(nodes,{x,y,scale,width,height,padding=160}){
  if(!Array.isArray(nodes)||![x,y,scale,width,height,padding].every(Number.isFinite)||scale<=0||width<0||height<0||padding<0)
   throw Error("invalid graph viewport");
  const left=(-x-padding)/scale,top=(-y-padding)/scale;
  const right=(width-x+padding)/scale,bottom=(height-y+padding)/scale;
  return new Set(nodes.filter(n=>n.x+n.width>=left&&n.x<=right&&n.y+n.height>=top&&n.y<=bottom).map(n=>n.id));
 }
 function neighbors(nodes,links,id){
  const known=new Set(nodes.map(n=>n.id)),result=new Set();
  for(const link of links){
   if(link.source===id&&known.has(link.target))result.add(link.target);
   if(link.target===id&&known.has(link.source))result.add(link.source);
  }
  return [...result];
 }
 function bounds(nodes){
  if(!nodes.length)return null;
  return {left:Math.min(...nodes.map(n=>n.x)),top:Math.min(...nodes.map(n=>n.y)),
   right:Math.max(...nodes.map(n=>n.x+n.width)),bottom:Math.max(...nodes.map(n=>n.y+n.height))};
 }
 root.SentraGraphView=Object.freeze({visibleIDs,neighbors,bounds});
})(globalThis);
