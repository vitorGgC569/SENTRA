/** Bounded volatile input only. Cancellation never repeats an in-flight effect. */
export class TerminalInputQueue {
 constructor({totalBytes=262144,sessionBytes=65536,packetBytes=16384,maxEntries=512,sessionEntries=128}={}){
  if(![totalBytes,sessionBytes,packetBytes,maxEntries,sessionEntries].every(n=>Number.isSafeInteger(n)&&n>0)||packetBytes>sessionBytes||sessionBytes>totalBytes)throw Error('Invalid terminal input bounds');
  Object.assign(this,{totalBytes,sessionBytes,packetBytes,maxEntries,sessionEntries});
  this.bytes=0;this.count=0;this.sessions=new Map();
 }
 enqueue(key,data,run){
  if(typeof key!=='string'||!key||key.length>512||typeof run!=='function'||typeof data!=='string'||!data||data.length>this.packetBytes)throw Error('terminal_input_queue_limit');
  for(const char of data){const cp=char.codePointAt(0);if(cp>=0xd800&&cp<=0xdfff)throw Error('terminal_input_invalid_unicode')}
  const bytes=new TextEncoder().encode(data).length+256;
  const session=this.sessions.get(key)||{bytes:0,count:0,queue:[],active:null};
  if(bytes-256>this.packetBytes||this.bytes+bytes>this.totalBytes||session.bytes+bytes>this.sessionBytes||this.count>=this.maxEntries||session.count>=this.sessionEntries)throw Error('terminal_input_queue_limit');
  this.sessions.set(key,session);this.bytes+=bytes;this.count++;session.bytes+=bytes;session.count++;
  return new Promise((resolve,reject)=>{session.queue.push({data,bytes,run,resolve,reject});this.pump(key,session)});
 }
 pump(key,session){
  if(session.active||!session.queue.length)return;
  const row=session.queue.shift();session.active=row;
  Promise.resolve().then(()=>row.run(row.data)).then(row.resolve,error=>{this.cancel(key);row.reject(error)}).finally(()=>{
   session.active=null;this.release(key,session,row);this.pump(key,session);
  });
 }
 release(key,session,row){
  this.bytes-=row.bytes;this.count--;session.bytes-=row.bytes;session.count--;
  row.data=null;row.run=null;
  if(!session.count&&this.sessions.get(key)===session)this.sessions.delete(key);
 }
 cancel(key){
  const session=this.sessions.get(key);if(!session)return 0;
  const rows=session.queue.splice(0);
  for(const row of rows){this.release(key,session,row);row.resolve({cancelled:true})}
  return rows.length;
 }
 status(key){const s=this.sessions.get(key);return {bytes:this.bytes,count:this.count,sessionBytes:s?.bytes||0,sessionCount:s?.count||0,active:!!s?.active}}
}
