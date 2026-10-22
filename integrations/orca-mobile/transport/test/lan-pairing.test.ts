import {test} from 'node:test';
import assert from 'node:assert/strict';
import type {NetworkInterfaceInfo} from 'node:os';
import {isLocalIPv4,lanAddresses} from '../src/lan-address';
import {deviceAtAddress,upsertDevice,directEndpoint} from '../src/pairing-state';
import type {Device} from '../src/client';

const nic=(address:string,family='IPv4'):NetworkInterfaceInfo=>({address,netmask:'255.255.255.0',
 family,mac:'00:00:00:00:00:00',internal:false,cidr:address+'/24'}) as NetworkInterfaceInfo;
test('LAN selection advertises only a family and address the listener serves',()=>{
 const interfaces={WiFi:[nic('192.168.1.8'),nic('fe80::1','IPv6')],
  'vEthernet (WSL)':[nic('172.28.0.1')],Ethernet:[nic('10.1.0.2')],public:[nic('203.0.113.2')]};
 assert.equal(isLocalIPv4('0.0.0.0'),false);assert.equal(isLocalIPv4('::1'),false);
 assert.deepEqual(lanAddresses(interfaces,'192.168.1.8').map(v=>v.address),['192.168.1.8']);
 assert.equal(lanAddresses(interfaces,'auto')[0].virtual,false);
 assert.deepEqual(lanAddresses(interfaces,'192.168.1.99'),[]);
 assert.equal(lanAddresses(interfaces,'127.0.0.1')[0].address,'127.0.0.1');
});
test('changing an IP preserves the pinned identity, credential, key and Dot scope',()=>{
 const device:Device={device_id:'phone',credential:'credential',public_key:'pinned-key',endpoint:'ws://192.168.1.3:5197/sentra/mobile/v1',
  keys:{publicKey:'client-key',secretKey:'client-secret'},scope:{project_id:'p',space_id:'s',dot_id:'d',actions:['workspace_inventory']}};
 const changed=deviceAtAddress(device,'192.168.1.9:5197');
 assert.equal(changed.endpoint,'ws://192.168.1.9:5197/sentra/mobile/v1');
 assert.deepEqual({...changed,endpoint:device.endpoint},device);
 const other={...device,device_id:'other',public_key:'another-host'};
 const otherDot={...device,device_id:'other-dot',scope:{...device.scope,dot_id:'second'}};
 assert.deepEqual(upsertDevice([device,other,otherDot],changed),[other,otherDot,changed]);
 for(const invalid of ['http://192.168.1.9:5197','ws://user:pass@192.168.1.9','ws://192.168.1.9/other','ws://192.168.1.9/?token=secret'])
  assert.throws(()=>directEndpoint(invalid));
});


test('private overlay VPN addresses remain direct, pinned and manually selected',()=>{
 for(const ip of ['100.64.0.1','100.100.5.9','100.127.255.254'])assert.equal(isLocalIPv4(ip,false),true);
 for(const ip of ['100.63.255.255','100.128.0.1','8.8.8.8'])assert.equal(isLocalIPv4(ip,false),false);
 const interfaces={WiFi:[nic('192.168.1.8')],Tailscale:[nic('100.100.5.9')]};
 assert.equal(lanAddresses(interfaces,'auto')[0].address,'192.168.1.8');
 assert.equal(lanAddresses(interfaces,'100.100.5.9')[0].virtual,true);
 assert.equal(directEndpoint('100.100.5.9:5197'),'ws://100.100.5.9:5197/sentra/mobile/v1');
});
