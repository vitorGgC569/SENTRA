/** Real encrypted acceptance client, isolated from installed accounts. */
import {createInterface} from 'node:readline';
import {randomBytes} from 'node:crypto';
import WebSocket from 'ws';
import {MobileClient} from '../src/client';
import {primitives} from '../src/primitives';
const lines=createInterface({input:process.stdin})[Symbol.asyncIterator]();
const config=JSON.parse((await lines.next()).value!);const wire:string[]=[],seen:string[]=[];
const client=new MobileClient(primitives(n=>new Uint8Array(randomBytes(n))),url=>{
 const socket=new WebSocket(url);socket.on('message',data=>wire.push(String(data)));return socket as any;
});
let detach:(()=>void)|undefined,readyAnnounced=false;
try{
 const pending=await client.pair(config.offer,'Presentation acceptance');
 console.log(JSON.stringify({phase:'pending',device_id:pending.device_id}));
 if((await lines.next()).value!=='approved')throw Error('Approval gate missing');
 const device=await client.claim(pending);if(!device)throw Error('Approval missing');
 detach=client.observeConversation(config.conversation_id,{
  onPreview:preview=>{
   if(!preview.content||seen.at(-1)===preview.content)return;
   if(preview.authoritative||preview.automatic_retry)throw Error('Preview conferred authority');
   seen.push(String(preview.content));console.log(JSON.stringify({phase:'preview',content:preview.content}));
  },
  onState:state=>{if(state==='connected'&&!readyAnnounced){readyAnnounced=true;console.log(JSON.stringify({phase:'ready'}));}if(state==='reauth_required')console.log(JSON.stringify({phase:'revoked',paired:client.isPairedTo(device)}));},
 });
 if((await lines.next()).value!=='finish')throw Error('Finish gate missing');
 if(seen.some(text=>text.includes('FOREIGN-PRIVATE')))throw Error('Foreign Dot leaked');
 if(wire.some(text=>text.includes('OWN-PRIVATE')))throw Error('Presentation was not encrypted');
 console.log(JSON.stringify({phase:'finished',seen:seen.length,encrypted:true}));
}catch(error){console.error(error);process.exitCode=1;}
finally{detach?.();client.disconnect();process.stdin.destroy();}
