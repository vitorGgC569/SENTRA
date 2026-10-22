// Platform injection follows ORCA paired-e2ee-primitives; no Node imports here.
import nacl from 'tweetnacl';
import {derivePairedE2EEV2KeySchedule} from './vendor/paired-e2ee-v2-key-schedule';
import type {PairedE2EEPrimitives} from './vendor/paired-e2ee-primitives';
export const encode=(bytes:Uint8Array)=>{let value='';for(const b of bytes)value+=String.fromCharCode(b);return btoa(value);};
export const decode=(value:string)=>{if(value.length>6000000)throw Error('Frame too large');const raw=atob(value);return Uint8Array.from(raw,c=>c.charCodeAt(0));};
export function primitives(randomBytes:(n:number)=>Uint8Array):PairedE2EEPrimitives{
 nacl.setPRNG((out,n)=>out.set(randomBytes(n)));
 const publicKey=(value:string)=>{const bytes=decode(value);if(bytes.length!==32)throw Error('Invalid key');return bytes;};
 const unsupported=():never=>{throw Error('Legacy encryption is disabled');};
 return {generateKeyPair:()=>nacl.box.keyPair(),deriveSharedKey:(secret,peer)=>nacl.box.before(peer,secret),randomBytes,encodeBase64:encode,decodeBase64:decode,publicKeyFromBase64:publicKey,publicKeyToBase64:encode,sealLegacyText:unsupported,openLegacyText:unsupported,sealLegacyBinary:unsupported,openLegacyBinary:unsupported,deriveV2KeySchedule:derivePairedE2EEV2KeySchedule};
}
