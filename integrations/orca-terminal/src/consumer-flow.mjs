/** Pull transport budget: count reads through renderer ACK, not only HTTP return.
 * Inspired by ORCA's per-client/in-flight accounting at the pinned MIT source.
 * No process control, input authority or producer pause is owned by this class.
 */
export class TerminalReadBudget {
 constructor({slots=8,maxWaiting=128}={}){
  if(!Number.isInteger(slots)||slots<1||slots>32||!Number.isInteger(maxWaiting)||maxWaiting<1||maxWaiting>512)throw Error('Invalid terminal read budget');
  this.slots=slots;this.maxWaiting=maxWaiting;this.active=new Map();this.waiting=new Map();
 }
 acquire(key,signal){
  if(typeof key!=='string'||!key||key.length>512)return Promise.reject(Error('Invalid terminal consumer identity'));
  if(signal?.aborted)return Promise.reject(Error('Terminal consumer detached'));
  if(this.active.has(key)||this.waiting.has(key))return Promise.reject(Error('Terminal consumer already has a read'));
  if(this.waiting.size>=this.maxWaiting)return Promise.reject(Error('Terminal consumer budget exhausted'));
  return new Promise((resolve,reject)=>{
   const row={key,signal,resolve,reject};
   row.abort=()=>{if(this.waiting.get(key)!==row)return;this.waiting.delete(key);reject(Error('Terminal consumer detached'))};
   signal?.addEventListener('abort',row.abort,{once:true});this.waiting.set(key,row);this.pump();
  });
 }
 pump(){
  while(this.active.size<this.slots&&this.waiting.size){
   const row=this.waiting.values().next().value;this.waiting.delete(row.key);
   row.signal?.removeEventListener('abort',row.abort);
   if(row.signal?.aborted){row.reject(Error('Terminal consumer detached'));continue}
   this.active.set(row.key,row);let released=false;
   row.resolve(()=>{if(released)return;released=true;if(this.active.get(row.key)===row)this.active.delete(row.key);this.pump()});
  }
 }
 status(){return {active:this.active.size,waiting:this.waiting.size,slots:this.slots,maxWaiting:this.maxWaiting}}
}
