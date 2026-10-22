import {test} from 'node:test';
import assert from 'node:assert/strict';
import {encode,decode} from 'dns-packet';
import {advertisementRecords,DISCOVERY_TYPE,advertiseLan} from '../src/lan-advertisement';
import {pairedDiscoveryCandidates} from '../src/lan-discovery';
import type {Device} from '../src/client';
const publicKey=Buffer.alloc(32,1).toString('base64');
const device:Device={device_id:'phone',credential:'not-advertised',endpoint:'ws://192.168.1.1:5197/sentra/mobile/v1',public_key:publicKey,keys:{publicKey:'client',secretKey:'never-advertised'},scope:{project_id:'p',space_id:'s',dot_id:'d',actions:['workspace_inventory']}};

test('DNS-SD wire records advertise only the bound private listener and public host key',()=>{
 const records=advertisementRecords('192.168.1.8',5197,publicKey),packet=decode(encode({type:'response',answers:records}));
 assert.equal(packet.answers?.length,4);assert.equal(records[0].name,DISCOVERY_TYPE);
 assert.deepEqual(records.flatMap(record=>record.type==='A'&&'data' in record?[record.data]:[]),['192.168.1.8']);
 const wire=JSON.stringify(packet);assert.ok(!wire.includes(device.credential)&&!wire.includes(device.keys.secretKey));
 assert.ok(!wire.includes('project_id')&&!wire.includes('space_id'));
 for(const invalid of ['0.0.0.0','127.0.0.1','8.8.8.8'])assert.throws(()=>advertisementRecords(invalid,5197,publicKey));
 assert.equal(advertiseLan('127.0.0.1',5197,publicKey).status(),'not_lan');
});
test('discovery is an untrusted address hint: unknown hosts, public/foreign addresses and altered scope are never adopted',()=>{
 const service={port:5197,addresses:['192.168.1.8'],txt:{protocol:'1',public_key:publicKey,address:'192.168.1.8',path:'/sentra/mobile/v1'}};
 const candidates=pairedDiscoveryCandidates([device],service);assert.equal(candidates.length,1);
 assert.deepEqual({...candidates[0],endpoint:device.endpoint},device);
 assert.equal(candidates[0].endpoint,'ws://192.168.1.8:5197/sentra/mobile/v1');
 for(const invalid of [{...service,txt:{...service.txt,public_key:'unknown'}},
  {...service,txt:{...service.txt,address:'8.8.8.8'},addresses:['8.8.8.8']},
  {...service,port:65536},{...service,txt:{...service.txt,path:'/other'}},
  {...service,addresses:Array(17).fill('192.168.1.8')},
  {...service,txt:{...service.txt,address:'192.168.1.9'}}])assert.deepEqual(pairedDiscoveryCandidates([device],invalid),[]);
 assert.deepEqual(pairedDiscoveryCandidates([],service),[]);
});
