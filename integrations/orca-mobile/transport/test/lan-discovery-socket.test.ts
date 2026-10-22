import {test} from 'node:test';
import assert from 'node:assert/strict';
import {networkInterfaces} from 'node:os';
import {randomBytes} from 'node:crypto';
import mdns from 'multicast-dns';
import {advertiseLan,DISCOVERY_TYPE} from '../src/lan-advertisement';
import {lanAddresses} from '../src/lan-address';

test('actual local multicast carries the exact public advertisement without any application request',
 {skip:process.env.SENTRA_MDNS_ACCEPTANCE!=='1',timeout:15000},async t=>{
 const bind=lanAddresses(networkInterfaces(),'auto').find(row=>!row.virtual)?.address;
 if(!bind){t.skip('No physical private IPv4 interface is available');return;}
 const publicKey=randomBytes(32).toString('base64'),observer=mdns({interface:bind,loopback:true});
 t.after(()=>observer.destroy());
 await new Promise<void>((resolve,reject)=>{observer.once('ready',resolve);observer.once('error',reject)});
 const received=new Promise<mdns.ResponsePacket>((resolve,reject)=>{
  const timeout=setTimeout(()=>reject(Error('Local multicast advertisement was not observed')),10000);
  observer.on('response',(packet:mdns.ResponsePacket)=>{
   const txt=packet.answers?.find(answer=>answer.type==='TXT'&&'data' in answer&&Array.isArray(answer.data)&&answer.data.some(value=>Buffer.from(value).toString()==='public_key='+publicKey));
   if(txt){clearTimeout(timeout);resolve(packet)}
  });
 });
 const advertisement=advertiseLan(bind,5197,publicKey);t.after(()=>advertisement.close());
 observer.query(DISCOVERY_TYPE,'PTR');const packet=await received;
 assert.deepEqual(packet.answers.filter(answer=>answer.type==='A'&&'data' in answer).map(answer=>'data' in answer?answer.data:null),[bind]);
 assert.ok(packet.answers.some(answer=>answer.type==='SRV'&&'data' in answer&&typeof answer.data==='object'&&answer.data!==null&&'port' in answer.data&&answer.data.port===5197));
 assert.equal(advertisement.status(),'advertising');
});
