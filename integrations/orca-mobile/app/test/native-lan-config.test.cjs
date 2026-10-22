'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process'),path=require('node:path');
test('Expo native mods carry Android LAN transport and iOS local-network intent',()=>{
 const root=path.resolve(__dirname,'..');
 const output=spawnSync(process.execPath,[path.join(root,'node_modules/expo/bin/cli'),'config','--type','introspect','--json'],
  {cwd:root,encoding:'utf8',timeout:30000,maxBuffer:2*1024*1024,windowsHide:true,
   env:{...process.env,CI:'1',EXPO_NO_DOTENV:'1'}});
 assert.equal(output.status,0,output.stderr.slice(-1000));
 const config=JSON.parse(output.stdout),mods=config._internal.modResults;
 assert.equal(mods.android.manifest.manifest.application[0].$['android:usesCleartextTraffic'],'true');
 assert.equal(mods.ios.infoPlist.NSAppTransportSecurity.NSAllowsLocalNetworking,true);
 assert.ok(mods.ios.infoPlist.NSLocalNetworkUsageDescription.length>10);
 assert.notEqual(mods.ios.infoPlist.NSAppTransportSecurity.NSAllowsArbitraryLoads,true);
 assert.equal(config.scheme,'sentra');
 assert.ok(mods.ios.infoPlist.NSBonjourServices.includes('_sentra._tcp'));
 const permissions=mods.android.manifest.manifest['uses-permission'].map(row=>row.$['android:name']);
 for(const permission of ['ACCESS_NETWORK_STATE','ACCESS_WIFI_STATE','CHANGE_WIFI_MULTICAST_STATE'])assert.ok(permissions.includes('android.permission.'+permission));
});
