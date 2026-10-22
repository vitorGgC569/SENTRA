/** Protected storage adapter; a manifest switches only after every chunk is durable. */
export type DraftStorage={read:(key:string)=>Promise<string|null>;write:(key:string,value:string)=>Promise<void>;remove:(key:string)=>Promise<void>};
export class PersistentDrafts{
 private queues=new Map<string,Promise<void>>();
 private pending=new Map<string,string>();
 constructor(private storage:DraftStorage){}
 async read(key:string):Promise<string>{
  await this.queues.get(key)?.catch(()=>{});
  const raw=await this.storage.read(key);if(!raw)return '';
  const manifest=JSON.parse(raw);
  if(manifest.version!==1||!Number.isInteger(manifest.count)||manifest.count<0||manifest.count>48||typeof manifest.revision!=='string'||!/^[a-z0-9]+$/.test(manifest.revision))throw Error('Rascunho protegido inválido.');
  const chunks=await Promise.all(Array.from({length:manifest.count},(_,i)=>this.storage.read(key+'.'+manifest.revision+'.'+i)));
  if(chunks.some(value=>value===null))throw Error('Rascunho protegido incompleto.');
  return chunks.join('');
 }
 write(key:string,value:string):Promise<void>{
  if([...value].length>17280)return Promise.reject(Error('O rascunho excede 17.280 caracteres.'));
  this.pending.set(key,value);const running=this.queues.get(key);if(running)return running;
  const operation=Promise.resolve().then(async()=>{
   while(this.pending.has(key)){
   const value=this.pending.get(key)!;this.pending.delete(key);
   const oldRaw=await this.storage.read(key),old=oldRaw?JSON.parse(oldRaw):null;
   const revision=Date.now().toString(36)+Math.random().toString(36).slice(2),characters=[...value];
   const chunks=Array.from({length:Math.ceil(characters.length/360)},(_,i)=>characters.slice(i*360,(i+1)*360).join(''));
   // Each item stays under 2 KiB, including four-byte Unicode characters.
   try{
    for(let i=0;i<chunks.length;i++)await this.storage.write(key+'.'+revision+'.'+i,chunks[i]);
    await this.storage.write(key,JSON.stringify({version:1,revision,count:chunks.length}));
   }catch(error){
    // A failed acknowledgement may follow a committed manifest. Never delete
    // chunks whose commit is uncertain; the last manifest remains recoverable.
    this.pending.delete(key);throw error;
   }
   if(old?.version===1&&typeof old.revision==='string'&&/^[a-z0-9]+$/.test(old.revision)&&Number.isInteger(old.count)&&old.count<=48)
    await Promise.all(Array.from({length:old.count},(_,i)=>this.storage.remove(key+'.'+old.revision+'.'+i))).catch(()=>{});
   }
  });
  this.queues.set(key,operation);void operation.finally(()=>{if(this.queues.get(key)===operation)this.queues.delete(key)}).catch(()=>{});return operation;
 }
}
