/** Read-only projection transport. It never submits work or grants authority. */
export type PresentationScope={project_id:string;space_id:string;conversation_id:string};
export type PresentationPreview=Record<string,unknown>&{sequence:number;content?:string;
 authoritative:false;partial:true;automatic_retry:false;closes_trio:false};
export type PresentationFrame={event:string;id?:string;data:Record<string,unknown>};
export type PresentationObserver={onPreview:(preview:PresentationPreview)=>void;onState?:(state:string)=>void};
export function sseFrames(body:ReadableStream<Uint8Array>,onBytes?:()=>void):AsyncGenerator<PresentationFrame>;
export function reduceProjection(previous:PresentationPreview|null|undefined,event:any):PresentationPreview;
export function reconnectDelay(attempt:number,random?:()=>number):number;
export class ProjectFeed {
 constructor(options:{open:(after:number|undefined,signal:AbortSignal,epoch?:string)=>Promise<{body:ReadableStream<Uint8Array>}|{frames:AsyncIterable<PresentationFrame>}>;
  readHead:(scope:PresentationScope,options:{signal:AbortSignal})=>Promise<any>;random?:()=>number;
  batchMs?:number;headTimeoutMs?:number;silenceMs?:number});
 readonly cursor:number|undefined;
 readonly state:string;
 readonly task:Promise<void>|undefined;
 subscribe(scope:PresentationScope,observer:PresentationObserver):()=>void;
 receive(frame:PresentationFrame):void;
 resume():void;
 close():void;
}
