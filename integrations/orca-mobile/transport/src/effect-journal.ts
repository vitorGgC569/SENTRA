/** Persist identity before transmission; uncertainty never becomes a new send. */
export type PendingEffect={key:string;slot:string;action:string;device_id:string;conversation_id?:string;fingerprint?:string;created_at:number};
type Storage={read:()=>Promise<string|null>;write:(value:string)=>Promise<void>};
export class EffectJournal {
 private queue:Promise<unknown>=Promise.resolve();
 constructor(private storage:Storage){}
 private serial<T>(fn:()=>Promise<T>):Promise<T>{const next=this.queue.then(fn,fn);this.queue=next.catch(()=>{});return next;}
 private async read(){const raw=await this.storage.read();if(!raw)return [] as PendingEffect[];const rows=JSON.parse(raw);if(!Array.isArray(rows)||rows.length>32||rows.some(r=>!r||typeof r.key!=='string'||typeof r.slot!=='string'||typeof r.action!=='string'||typeof r.device_id!=='string'))throw Error('Registro de envios inválido; consulte o desktop antes de enviar.');return rows as PendingEffect[];}
 list(){return this.serial(()=>this.read());}
 begin(record:PendingEffect){return this.serial(async()=>{const rows=await this.read();if(rows.some(r=>r.slot===record.slot))throw Error('Há um envio sem confirmação neste recurso. Consulte o recibo antes de repetir.');if(rows.length>=32)throw Error('Consulte os envios sem confirmação no desktop.');await this.storage.write(JSON.stringify([...rows,record]));return record;});}
 finish(key:string){return this.serial(async()=>{const rows=await this.read();await this.storage.write(JSON.stringify(rows.filter(r=>r.key!==key)));});}
}
