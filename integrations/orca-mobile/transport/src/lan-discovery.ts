import type {Device} from './client';
import {deviceAtAddress} from './pairing-state';
export type DiscoveredService={port?:unknown;addresses?:unknown;txt?:unknown};
/** Unauthenticated DNS-SD data is only a bounded hint for an already pinned host. */
export function pairedDiscoveryCandidates(devices:Device[],service:DiscoveredService):Device[]{
 const txt=service.txt as Record<string,unknown>|undefined;
 if(!txt||txt.protocol!=='1'||txt.path!=='/sentra/mobile/v1'||typeof txt.public_key!=='string'||
  typeof service.port!=='number'||!Number.isInteger(service.port)||service.port<1||service.port>65535||
  !Array.isArray(service.addresses)||service.addresses.length>16)return [];
 const approved=devices.filter(device=>device.public_key===txt.public_key);
 if(!approved.length)return [];
 const candidates:Device[]=[];
 for(const address of service.addresses){
  if(typeof address!=='string'||address.startsWith('127.')||address!==txt.address)continue;
  for(const device of approved){try{candidates.push(deviceAtAddress(device,address+':'+service.port))}catch{/* Public, malformed and IPv6 advertisements are ignored. */}}
 }
 return [...new Map(candidates.map(device=>[device.device_id+':'+device.endpoint,device])).values()].slice(0,8);
}
