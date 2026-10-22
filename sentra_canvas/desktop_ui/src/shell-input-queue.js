// An admitted input always keeps its original scope and lease epoch. Neither a
// navigation nor a renewed lease can turn an old queued gesture into new input.
export class ScopedInputQueue {
  constructor(send, onError = () => {}) { this.send=send; this.onError=onError; this.pending=[]; this.serial=Promise.resolve(); this.generation=0; }
  enqueue(request) {
    if(this.pending.length>=32)return false;
    const item={request:structuredClone(request),generation:this.generation};
    this.pending.push(item);
    this.serial=this.serial.then(async()=>{
      const index=this.pending.indexOf(item); if(index<0)return;
      this.pending.splice(index,1);
      if(item.generation!==this.generation)return;
      try { const value=await this.send(item.request); if(value.state!=='SUCCEEDED')throw Error('Entrada da VM não confirmada; atualize a posse de controle.'); }
      catch(error) { this.clear(); this.onError(error); }
    });
    return true;
  }
  clear() { this.generation++; this.pending=[]; }
  release(requests) {
    this.clear();
    // Releases run after the one already in flight, with the old lease. They
    // cannot be retargeted to a different Dot, and are never retried.
    const frozen=structuredClone(requests);
    this.serial=this.serial.then(async()=>{for(const request of frozen){try{const value=await this.send(request);if(value.state!=='SUCCEEDED')throw Error('Liberação do controle não confirmada.');}catch(error){this.onError(error);}}});
    return this.serial;
  }
}
