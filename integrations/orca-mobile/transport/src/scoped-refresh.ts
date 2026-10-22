/** One read in flight; stopping fences delivery, errors and future scheduling. */
export class ScopedRefresh<T>{
 private stopped=true;private generation=0;private failures=0;private timer:ReturnType<typeof setTimeout>|undefined;
 constructor(private read:()=>Promise<T>,private deliver:(value:T)=>void,private error:(error:Error)=>void,private interval=2500){}
 start(){if(!this.stopped)return;this.stopped=false;void this.tick(++this.generation);}
 stop(){this.stopped=true;this.generation++;clearTimeout(this.timer);}
 private async tick(generation:number){const current=()=>!this.stopped&&this.generation===generation;if(!current())return;try{const value=await this.read();if(current()){this.failures=0;this.deliver(value)}}catch(error){if(current()){this.failures=Math.min(this.failures+1,4);this.error(error instanceof Error?error:Error(String(error)))}}
  if(current())this.timer=setTimeout(()=>void this.tick(generation),Math.min(30000,Math.max(1000,this.interval)*2**this.failures));
 }
}
