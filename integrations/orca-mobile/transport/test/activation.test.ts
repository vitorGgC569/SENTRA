import {test} from 'node:test';
import assert from 'node:assert/strict';
import {canActivateSession} from '../src/activation';
import type {Device} from '../src/client';

const device:Device={device_id:'phone',credential:'credential',public_key:'host',endpoint:'ws://192.168.1.2:8080/sentra/mobile/v1',
 keys:{publicKey:'client',secretKey:'secret'},scope:{project_id:'p',space_id:'s',dot_id:'d',actions:['workspace_inventory']}};

test('activation after an asynchronous save rejects a closed or changed session',async()=>{
 let paired:Device|null=device,current:unknown;
 const transport={isPairedTo:(expected:Device)=>paired===expected};current=transport;
 let finish!:()=>void;const saving=new Promise<void>(resolve=>finish=resolve);
 const completion=saving.then(()=>canActivateSession(transport,current,device,true,7,7));
 paired=null;finish();assert.equal(await completion,false);
 paired=device;current={};assert.equal(canActivateSession(transport,current,device,true,7,7),false);
 assert.equal(canActivateSession(transport,transport,device,true,7,7),true);
});

test('background then foreground during an asynchronous step cannot reactivate an old generation',async()=>{
 const transport={isPairedTo:(expected:Device)=>expected===device};let epoch=3,foreground=true,finish!:()=>void;
 const saving=new Promise<void>(resolve=>finish=resolve);
 const completion=saving.then(()=>canActivateSession(transport,transport,device,foreground,3,epoch));
 foreground=false;epoch++;foreground=true;epoch++;finish();
 assert.equal(await completion,false);
 assert.equal(canActivateSession(transport,transport,device,false,epoch,epoch),false);
});
