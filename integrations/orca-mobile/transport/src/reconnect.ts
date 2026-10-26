/** Reopen a transport only; never queue or replay a business request. */
export class ReconnectLoop {
 private current: {controller:AbortController;timer:ReturnType<typeof setTimeout>|null}|null=null;
 constructor(private options:{
  eligible:()=>boolean;
  attempt:(signal:AbortSignal)=>Promise<void>;
  stopOn:(error:unknown)=>boolean;
  onExhausted:(error:unknown)=>void;
  maxAttempts?:number;
  baseDelayMs?:number;
 }){}
 trigger(){
  if(this.current||!this.options.eligible())return;
  const entry={controller:new AbortController(),timer:null as ReturnType<typeof setTimeout>|null};
  this.current=entry;
  const isCurrent=()=>this.current===entry&&!entry.controller.signal.aborted;
  const finish=()=>{if(isCurrent())this.current=null;};
  const run=async(attempt:number)=>{
   if(!isCurrent())return;
   if(!this.options.eligible()){this.cancel();return;}
   try{
    await this.options.attempt(entry.controller.signal);
    if(isCurrent())finish();
   }catch(error){
    if(!isCurrent())return;
    if(!this.options.eligible()){this.cancel();return;}
    if(this.options.stopOn(error)||attempt>=(this.options.maxAttempts??5)){
     finish();this.options.onExhausted(error);return;
    }
    const delay=Math.min(30000,(this.options.baseDelayMs??1000)*2**(attempt-1));
    entry.timer=setTimeout(()=>{entry.timer=null;void run(attempt+1);},delay);
   }
  };
  void run(1);
 }
 cancel(){
  const entry=this.current;if(!entry)return;
  this.current=null;if(entry.timer)clearTimeout(entry.timer);entry.controller.abort();
 }
 get active(){return this.current!==null;}
}
