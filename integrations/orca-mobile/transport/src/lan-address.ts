import {isIP} from 'node:net';
import type {NetworkInterfaceInfo} from 'node:os';

export function isLocalIPv4(value: string, loopback = true): boolean {
 return isIP(value)===4 && (/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(value) || loopback && value.startsWith('127.'));
}

/** Only addresses the actual listener serves; virtual adapters remain manual choices. */
export function lanAddresses(interfaces:Record<string,NetworkInterfaceInfo[]|undefined>,bind:string){
 const rows=Object.entries(interfaces).flatMap(([name,values])=>(values||[])
  .filter(v=>v.family==='IPv4'&&!v.internal&&isLocalIPv4(v.address,false))
  .map(v=>({name,address:v.address,virtual:/docker|wsl|vethernet|virtualbox|vmware|hyper-v|loopback/i.test(name)})));
 const unique=[...new Map(rows.map(v=>[v.address,v])).values()];
 const served=bind==='auto'?unique:unique.filter(v=>v.address===bind);
 if(bind.startsWith('127.')&&isLocalIPv4(bind))served.push({name:'Este computador',address:bind,virtual:false});
 return served.sort((a,b)=>Number(a.virtual)-Number(b.virtual)||a.name.localeCompare(b.name)||a.address.localeCompare(b.address));
}
