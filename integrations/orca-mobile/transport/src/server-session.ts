import type {PairedE2EEPrimitives,PairedE2EEV2KeySchedule} from './vendor/paired-e2ee-primitives';
import {validateMobileE2EEV2Handshake,encodeMobileE2EEV2Transcript,type MobileE2EEV2Hello,type MobileE2EEV2Ready} from './vendor/mobile-e2ee-v2-contract';
import {sealMobileE2EEV2Frame,openMobileE2EEV2Frame} from './vendor/mobile-e2ee-v2-framing';
export class ServerSession {
 readonly ready:MobileE2EEV2Ready;readonly peer:string;
 private schedule:PairedE2EEV2KeySchedule;private inbound=0n;private outbound=0n;
 constructor(hello:MobileE2EEV2Hello,secret:Uint8Array,publicKey:Uint8Array,private p:PairedE2EEPrimitives){
  if(hello?.context?.transport!=='direct')throw Error('Direct transport required');
  this.ready={type:'e2ee_ready',v:2,desktopPublicKeyB64:p.encodeBase64(publicKey),clientNonceB64:hello.clientNonceB64,desktopNonceB64:p.encodeBase64(p.randomBytes(32)),selection:{framing:2,payloadKinds:['text','binary']},context:hello.context};
  const handshake=validateMobileE2EEV2Handshake(hello,this.ready);if(!handshake)throw Error('Invalid E2EE handshake');this.peer=hello.clientPublicKeyB64;
  this.schedule=p.deriveV2KeySchedule({sharedSecret:p.deriveSharedKey(secret,handshake.clientPublicKey),transcript:encodeMobileE2EEV2Transcript(handshake),clientNonce:handshake.clientNonce,desktopNonce:handshake.desktopNonce});
 }
 open(frame:string){const bytes=this.p.decodeBase64(frame);if(this.p.encodeBase64(bytes)!==frame)return null;const value=openMobileE2EEV2Frame({frame:bytes,key:this.schedule.mobileToDesktopKey,sessionId:this.schedule.sessionId,direction:'mobile-to-desktop',payloadKind:'text',expectedCounter:this.inbound});if(!value)return null;this.inbound++;return new TextDecoder().decode(value);}
 seal(value:string){const bytes=sealMobileE2EEV2Frame({payload:new TextEncoder().encode(value),key:this.schedule.desktopToMobileKey,sessionId:this.schedule.sessionId,direction:'desktop-to-mobile',payloadKind:'text',counter:this.outbound++});return this.p.encodeBase64(bytes);}
}
