/** In-process Hocuspocus admission and bounded per-socket message budget.
 * No global distributed quota claims. No sensitive data in inspect().
 */
const deny=()=>{throw Error("collaboration-denied");};
const integer=(v,lo,hi)=>Number.isInteger(v)&&v>=lo&&v<=hi;
const safeId=s=>typeof s==="string"&&/^[A-Za-z0-9_-]{1,80}$/.test(s);
export class LocalAdmission {
  #sessions=new Map();
  #accepted=0;#rejected=0;#framesRejected=0;
  #times=[];#closed=false;#clock;
  constructor({maxPerPrincipal=4,maxPerWorkspace=24,maxTotal=128,
    maxFramesPerWindow=120,windowMs=1000,maxFrameBytes=81920,
    clock=()=>Date.now()}={}){
    if(!integer(maxPerPrincipal,1,128)||!integer(maxPerWorkspace,1,128)||
       !integer(maxTotal,1,128)||!integer(maxFramesPerWindow,1,1000)||
       !integer(windowMs,50,60000)||!integer(maxFrameBytes,128,81920)||
       typeof clock!=="function")deny();
    this.limits=Object.freeze({maxPerPrincipal,maxPerWorkspace,maxTotal,
      maxFramesPerWindow,windowMs,maxFrameBytes});
    this.#clock=clock;
  }
  #ensure(){if(this.#closed)deny();}
  admit(key,context,latencyMs=0){
    this.#ensure();
    if(typeof key!=="string"||!key||
       !safeId(context?.workspaceId)||!safeId(context?.principalId)||
       this.#sessions.has(key))deny();
    const sessions=[...this.#sessions.values()];
    const principal=sessions.filter(s=>s.principalId===context.principalId).length;
    const workspace=sessions.filter(s=>s.workspaceId===context.workspaceId).length;
    if(sessions.length>=this.limits.maxTotal||
       principal>=this.limits.maxPerPrincipal||
       workspace>=this.limits.maxPerWorkspace){
      this.reject();deny();
    }
    this.#sessions.set(key,{principalId:context.principalId,
      workspaceId:context.workspaceId,count:0,start:this.#clock()});
    this.#accepted++;
    this.recordLatency(latencyMs);
  }
  reject(){this.#rejected++;}
  recordLatency(ms){
    if(typeof ms!=="number"||!Number.isFinite(ms)||ms<0)deny();
    this.#times.push(Math.min(60000,ms));
    if(this.#times.length>256)this.#times.shift();
  }
  frame(key,length){
    this.#ensure();
    const session=this.#sessions.get(key);
    if(!session||!integer(length,0,this.limits.maxFrameBytes)){
      this.#framesRejected++;deny();
    }
    const now=this.#clock();
    if(now<session.start||now-session.start>=this.limits.windowMs){
      session.start=now;session.count=0;
    }
    session.count++;
    if(session.count>this.limits.maxFramesPerWindow){
      this.#framesRejected++;deny();
    }
  }
  release(key){this.#sessions.delete(key);}
  inspect(){
    const numbers=[...this.#times].sort((a,b)=>a-b);
    const p95=numbers.length?numbers[Math.ceil(numbers.length*0.95)-1]:0;
    return Object.freeze({activeSessions:this.#sessions.size,
      activeWorkspaces:new Set([...this.#sessions.values()].map(s=>s.workspaceId)).size,
      accepted:this.#accepted,rejected:this.#rejected,
      framesRejected:this.#framesRejected,
      admissionLatencyP95Ms:Math.round(p95*100)/100,
      closed:this.#closed});
  }
  close(){if(this.#closed)return;this.#closed=true;this.#sessions.clear();this.#times=[];}
}
