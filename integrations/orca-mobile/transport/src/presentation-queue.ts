import type {PresentationFrame} from './presentation-stream.js';

/** Bounded observer queue for Hermes; no browser stream/decoder polyfill. */
export class PresentationQueue implements AsyncIterable<PresentationFrame> {
 private items:{frame:PresentationFrame;bytes:number}[]=[];private bytes=0;
 private failure:Error|null=null;private stopped=false;private wake:(()=>void)|null=null;
 push(frame:PresentationFrame){
  if(this.stopped)return;
  // Three bytes per UTF-16 code unit is a conservative UTF-8 bound, including
  // surrogate pairs. Reject before retaining another serialized frame.
  const bytes=JSON.stringify(frame).length*3;
  if(bytes>2_000_000||this.bytes+bytes>4_000_000||this.items.length>=128){
   this.fail(Error('Presentation observer queue exceeded its budget'));return;
  }
  this.items.push({frame,bytes});this.bytes+=bytes;this.wake?.();this.wake=null;
 }
 fail(error:Error){this.failure=error;this.close();}
 close(){this.stopped=true;this.items=[];this.bytes=0;this.wake?.();this.wake=null;}
 async *[Symbol.asyncIterator](){
  try{for(;;){
   if(this.failure)throw this.failure;
   const item=this.items.shift();if(item){this.bytes-=item.bytes;yield item.frame;continue;}
   if(this.stopped)return;
   await new Promise<void>(resolve=>{this.wake=resolve;});
  }}finally{this.close();}
 }
}
