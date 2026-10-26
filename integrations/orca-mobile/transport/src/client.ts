import {ProjectFeed,type PresentationObserver,type PresentationScope} from './presentation-stream.js';
import {PresentationQueue} from './presentation-queue';
import {PairedE2EEV2ClientSession} from './vendor/paired-e2ee-v2-client-session';
import type {PairedE2EEPrimitives,PairedE2EEKeyPair} from './vendor/paired-e2ee-primitives';
import type {PairedScope} from './contracts';
import {directEndpoint} from './pairing-state';
export {canonicalIntent,journalIntent} from './intent-fingerprint.js';
export {EffectJournal,type PendingEffect} from './effect-journal';
export {upsertDevice,deviceAtAddress,deviceAtOffer,directEndpoint} from './pairing-state';
export {ReconnectLoop} from './reconnect';
export {canActivateSession} from './activation';
export {TerminalFeed,type TerminalDelivery} from './terminal-feed';
export type {TerminalOutputFrame} from './contracts';
export {bindRequestContext,requireRequestContext} from './request-context';
export {ScopedRefresh} from './scoped-refresh';
export {ProjectFeed,sseFrames,reduceProjection} from './presentation-stream.js';
export {NATIVE_MOBILE_ORIGIN} from './native-origin';
export type {PresentationScope,PresentationPreview,PresentationFrame,PresentationObserver} from './presentation-stream.js';
export {pairedDiscoveryCandidates} from './lan-discovery';
export type PairingOffer={endpoint:string;public_key:string;invite_id:string;invite:string;protocol_version:1};
export type Device={device_id:string;credential:string;rotation_key?:string;scope:PairedScope;endpoint:string;public_key:string;keys:{publicKey:string;secretKey:string}};
type SocketLike={send:(value:string)=>void;close:()=>void;onopen:((e:any)=>void)|null;onmessage:((e:any)=>void)|null;onclose:((e:any)=>void)|null;onerror:((e:any)=>void)|null};
export function parseOffer(uri:string):PairingOffer{if(!uri.startsWith('sentra://pair#')||uri.length>6000)throw Error('Link de pareamento inválido');const encoded=uri.slice('sentra://pair#'.length).replace(/-/g,'+').replace(/_/g,'/');const data=JSON.parse(atob(encoded));const url=new URL(data.endpoint);if(!['ws:','wss:'].includes(url.protocol)||url.username||url.password||url.search||url.hash||url.pathname!=='/sentra/mobile/v1'||data.protocol_version!==1)throw Error('Oferta incompatível');directEndpoint(data.endpoint);return data;}
export class MobileClient {
 private socket:SocketLike|null=null;private session:PairedE2EEV2ClientSession|null=null;
 private pending=new Map<string,{resolve:(v:any)=>void;reject:(e:Error)=>void;timer:ReturnType<typeof setTimeout>;authDevice:Device|null}>();
 private presentations=new Map<string,{queue:PresentationQueue;authDevice:Device}>();
 private device:Device|null=null;private readyReject:((e:Error)=>void)|null=null;
 private connectionIdentity:{endpoint:string;hostKey:string;clientKey:string}|null=null;
 get hasPairedSession(){return this.device!==null&&this.session?.isReady===true;}
 /** A live socket must belong to the same pinned host, credential and scope
  * shown by the caller. This fences input while a different host is resumed. */
 isPairedTo(expected:Device|null){
  const actual=this.device;
  return this.hasPairedSession&&!!actual&&!!expected&&actual.device_id===expected.device_id&&
   actual.public_key===expected.public_key&&actual.credential===expected.credential&&
   actual.scope.project_id===expected.scope.project_id&&actual.scope.space_id===expected.scope.space_id&&
   actual.scope.dot_id===expected.scope.dot_id&&actual.scope.actions.length===expected.scope.actions.length&&
   actual.scope.actions.every((action,index)=>action===expected.scope.actions[index]);
 }
 constructor(private p:PairedE2EEPrimitives,private createSocket:(url:string)=>SocketLike,private onStatus:(status:string)=>void=()=>{}){}
 async connect(endpoint:string,publicKey:string,keys?:PairedE2EEKeyPair){this.disconnect();const session=PairedE2EEV2ClientSession.create({primitives:this.p,desktopPublicKeyB64:publicKey,transport:'direct',clientKeyPair:keys});this.session=session;const socket=this.createSocket(endpoint);this.socket=socket;this.connectionIdentity={endpoint,hostKey:publicKey,clientKey:session.hello.clientPublicKeyB64};const current=()=>this.socket===socket&&this.session===session;this.onStatus('connecting');await new Promise<void>((resolve,reject)=>{this.readyReject=reject;const timer=setTimeout(()=>{if(!current())return;this.disconnect();reject(Error('Conexão não confirmada.'))},10000);socket.onopen=()=>{if(current())socket.send(JSON.stringify(session.hello))};socket.onmessage=e=>{if(!current())return;try{if(!session.isReady){if(!session.acceptReady(JSON.parse(String(e.data))))throw Error('Identidade do host não corresponde ao pareamento');clearTimeout(timer);this.readyReject=null;this.onStatus('connected');resolve();return;}const plain=session.openText(String(e.data));if(plain===null)throw Error('Frame inválido ou repetido');const response=JSON.parse(plain);if(response.type==='presentation'){const observer=this.presentations.get(response.subscription_id);if(observer){observer.queue.push(response.frame);if(response.frame?.event==='end'&&response.frame?.data?.status===403&&response.frame?.data?.code==='MOBILE_DEVICE_AUTH_INVALID'&&this.device===observer.authDevice)this.disconnect('reauth_required');}return;}const item=this.pending.get(response.id);if(item){clearTimeout(item.timer);this.pending.delete(response.id);if(response.ok)item.resolve(response.value);else{const invalid=response.status===403&&response.code==='MOBILE_DEVICE_AUTH_INVALID'&&item.authDevice!==null&&this.device===item.authDevice;item.reject(Object.assign(Error(response.error||'Pedido recusado'),{status:response.status,code:response.code}));if(invalid)this.disconnect('reauth_required');}}}catch(error){clearTimeout(timer);reject(error);this.disconnect();}};socket.onclose=event=>{clearTimeout(timer);if(current()){if(!session.isReady&&event?.code===1008){const rejectReady=this.readyReject;this.readyReject=null;rejectReady?.(Error('Conexão recusada. O SENTRA no computador pode estar desatualizado; atualize o aplicativo e confirme a mesma rede.'));}this.socket=null;this.session=null;this.device=null;this.connectionIdentity=null;this.closed();}};socket.onerror=()=>{if(!current())return;clearTimeout(timer);reject(Error('Host indisponível'));this.disconnect();};});}
 private closed(status='disconnected'){for(const observer of this.presentations.values())observer.queue.fail(status==='reauth_required'?Object.assign(Error('Device access is no longer valid'),{status:403,code:'MOBILE_DEVICE_AUTH_INVALID'}):Error('Presentation connection interrupted'));this.presentations.clear();this.onStatus(status);this.readyReject?.(Error('Conexão interrompida'));this.readyReject=null;for(const item of this.pending.values()){clearTimeout(item.timer);item.reject(Error('Resultado não confirmado. Consulte antes de repetir.'));}this.pending.clear();}
 disconnect(status='disconnected'){const socket=this.socket;this.socket=null;this.session=null;this.device=null;this.connectionIdentity=null;if(socket){socket.onclose=null;socket.close();}this.closed(status);}
 async rpc(body:Record<string,unknown>){const session=this.session,socket=this.socket;if(!session?.isReady||!socket)throw Error('Conecte-se ao host');const id=this.p.encodeBase64(this.p.randomBytes(18));const authDevice=this.device&&body.device_id===this.device.device_id&&body.credential===this.device.credential?this.device:null;return new Promise<any>((resolve,reject)=>{const timer=setTimeout(()=>{if(!this.pending.delete(id))return;reject(Error('Resultado não confirmado. Nenhum reenvio automático.'));if(this.socket===socket&&this.session===session)this.disconnect();},15000);this.pending.set(id,{resolve,reject,timer,authDevice});try{socket.send(session.sealText(JSON.stringify({id,...body})))}catch{clearTimeout(timer);this.pending.delete(id);reject(Error('Envio não confirmado'));if(this.socket===socket&&this.session===session)this.disconnect();}});}
 /** Observe an existing conversation; disconnect only detaches the viewer. */
 observeConversation(conversation_id:string,observer:PresentationObserver){
  const device=this.device;if(!device)throw Error('Dispositivo não pareado');
  const scope:PresentationScope={project_id:device.scope.project_id,space_id:device.scope.space_id,conversation_id};
  const request={...scope,dot_id:device.scope.dot_id};
  const feed=new ProjectFeed({
   readHead:async()=>{
    if(this.device!==device)throw Object.assign(Error('Presentation device changed'),{status:403});
    return this.rpc({method:'presentation_head',device_id:device.device_id,credential:device.credential,request});
   },
   open:async(after,signal,epoch)=>{
    if(this.device!==device||!this.hasPairedSession)throw Object.assign(Error('Presentation device changed'),{status:403});
    const id=this.p.encodeBase64(this.p.randomBytes(18)),frames=new PresentationQueue();
    this.presentations.set(id,{queue:frames,authDevice:device});
    const stop=()=>{
     frames.close();this.presentations.delete(id);
     if(this.device===device&&this.hasPairedSession)void this.rpc({method:'unsubscribe_presentation',subscription_id:id}).catch(()=>{});
    };
    signal.addEventListener('abort',stop,{once:true});
    try{
     const accepted=await this.rpc({method:'subscribe_presentation',subscription_id:id,device_id:device.device_id,
      credential:device.credential,request,after,epoch});
     if(accepted?.protocol_version!==1||accepted.subscription_id!==id)
      throw Object.assign(Error('Presentation protocol unavailable'),{status:501});
     if(signal.aborted)throw Error('Presentation observation interrupted');
     return {frames};
    }catch(error){signal.removeEventListener('abort',stop);stop();throw error;}
   },
  });
  const detach=feed.subscribe(scope,observer);
  return ()=>{detach();feed.close();};
 }
 async pair(offer:PairingOffer,name:string){const keys=this.p.generateKeyPair();await this.connect(offer.endpoint,offer.public_key,keys);const value=await this.rpc({method:'pair',invite_id:offer.invite_id,invite:offer.invite,name});return {device_id:value.device_id,fingerprint:value.fingerprint,keys,offer};}
 async claim(pending:{device_id:string;keys:PairedE2EEKeyPair;offer:PairingOffer}){
  // Reconnect the original pinned host and key before a user-requested claim.
  // No pair request or uncertain claim is automatically replayed.
  const matches=()=>this.session?.isReady===true&&this.connectionIdentity?.endpoint===pending.offer.endpoint&&
   this.connectionIdentity.hostKey===pending.offer.public_key&&this.connectionIdentity.clientKey===this.p.encodeBase64(pending.keys.publicKey);
  if(!matches())await this.connect(pending.offer.endpoint,pending.offer.public_key,pending.keys);
  if(!matches())throw Error('A conexão mudou. A confirmação não foi enviada.');
  const value=await this.rpc({method:'claim',device_id:pending.device_id});if(value.state==='pending')return null;const device:Device={...value,endpoint:pending.offer.endpoint,public_key:pending.offer.public_key,keys:{publicKey:this.p.encodeBase64(pending.keys.publicKey),secretKey:this.p.encodeBase64(pending.keys.secretKey)}};this.device=device;return device;}
 async rotateCredential(persist:(device:Device)=>Promise<void>){
  const original=this.device;if(!original)throw Error('Dispositivo não pareado');
  const prepared={...original,rotation_key:original.rotation_key||this.p.encodeBase64(this.p.randomBytes(24))};
  await persist(prepared);if(this.device!==original)throw Error('A conexão mudou. A rotação não foi enviada.');this.device=prepared;
  const result=await this.rpc({method:'rotate',device_id:prepared.device_id,credential:prepared.credential,request_key:prepared.rotation_key});
  if(this.device!==prepared)throw Error('A conexão mudou. Retome a rotação salva.');
  const {rotation_key,...next}={...prepared,credential:result.credential};await persist(next);
  if(this.device!==prepared)throw Error('A conexão mudou. A credencial foi salva.');this.device=next;return next;
 }
 async resume(device:Device,persist?:(device:Device)=>Promise<void>){try{await this.connect(device.endpoint,device.public_key,{publicKey:this.p.decodeBase64(device.keys.publicKey),secretKey:this.p.decodeBase64(device.keys.secretKey)});this.device=device;
  if(device.rotation_key){if(!persist)throw Error('Retome a rotação protegida neste aparelho.');device=await this.rotateCredential(persist)}
  await this.request({action:'workspace_inventory'});return device;}catch(error){this.disconnect();throw error;}}
 async request(request:Record<string,unknown>){if(!this.device)throw Error('Dispositivo não pareado');return this.rpc({method:'request',device_id:this.device.device_id,credential:this.device.credential,request:{...request,project_id:this.device.scope.project_id,space_id:this.device.scope.space_id,dot_id:this.device.scope.dot_id}});}
}
