import mdns from 'multicast-dns';
import type {Answer} from 'dns-packet';
import {createHash} from 'node:crypto';
import {isLocalIPv4} from './lan-address';

export const DISCOVERY_TYPE='_sentra._tcp.local';
export function advertisementRecords(bind:string,port:number,publicKey:string,ttl=120):Answer[]{
 if(!isLocalIPv4(bind,false)||!Number.isInteger(port)||port<1||port>65535||Buffer.from(publicKey,'base64').length!==32)throw Error('Private listener and pinned host key required');
 const id=createHash('sha256').update(publicKey).digest('hex').slice(0,20),name='SENTRA-'+id+'.'+DISCOVERY_TYPE,host='sentra-'+id+'.local';
 return [{name:DISCOVERY_TYPE,type:'PTR',ttl,data:name},
  {name,type:'SRV',ttl,flush:true,data:{port,target:host,priority:0,weight:0}},
  {name,type:'TXT',ttl,flush:true,data:[`protocol=1`,`public_key=${publicKey}`,`address=${bind}`,`path=/sentra/mobile/v1`].map(value=>Buffer.from(value))},
  {name:host,type:'A',ttl,flush:true,data:bind}];
}
export type Advertisement={close:()=>void;status:()=>string};
export function advertiseLan(bind:string,port:number,publicKey:string):Advertisement{
 if(!isLocalIPv4(bind,false))return {close:()=>{},status:()=>'not_lan'};
 let state='starting',closed=false,socket:mdns.MulticastDNS|undefined,refresh:ReturnType<typeof setInterval>|undefined;
 try{
  const records=advertisementRecords(bind,port,publicKey),names=new Set(records.map(record=>record.name.toLowerCase()));
  socket=mdns({interface:bind,loopback:true,ttl:255});
  const send=()=>{if(!closed)socket!.respond({answers:records},error=>{if(!closed)state=error?'unavailable':'advertising'})};
  socket.on('error',()=>{state='unavailable';clearInterval(refresh);try{socket?.destroy()}catch{}});
  socket.on('ready',()=>{send();refresh=setInterval(send,30000);refresh.unref();});
  let window=Date.now(),count=0;
  socket.on('query',(packet:mdns.QueryPacket,remote:{address:string})=>{
   if(closed||!isLocalIPv4(remote.address))return;
   if(Date.now()-window>=1000){window=Date.now();count=0;}
   if(++count<=4&&packet.questions?.some(question=>names.has(question.name.toLowerCase().replace(/\.$/,''))))send();
  });
 }catch{state='unavailable';try{socket?.destroy()}catch{}}
 return {status:()=>state,close:()=>{if(closed)return;closed=true;state='stopped';clearInterval(refresh);if(!socket)return;
  const fallback=setTimeout(()=>{try{socket?.destroy()}catch{}},500);fallback.unref();
  try{socket.respond({answers:advertisementRecords(bind,port,publicKey,0)},()=>{clearTimeout(fallback);socket?.destroy()})}catch{clearTimeout(fallback);try{socket.destroy()}catch{}}
 }};
}
