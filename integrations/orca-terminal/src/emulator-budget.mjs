/** Presentation allocations only. This never owns a PTY or an input operation.
 * Reserve both screen buffers, bounded scrollback and per-renderer overhead.
 * The byte count is a conservative allocation model, not a JS heap measurement.
 */
export class EmulatorBudget {
 constructor({maxBytes=64*1024*1024,maxRenderers=8,bytesPerCell=32,overheadBytes=1024*1024}={}){
  if(![maxBytes,maxRenderers,bytesPerCell,overheadBytes].every(Number.isSafeInteger)||maxBytes<1||maxRenderers<1||bytesPerCell<12||overheadBytes<0)throw Error('Invalid emulator budget');
  Object.assign(this,{maxBytes,maxRenderers,bytesPerCell,overheadBytes});this.allocations=new Map();
 }
 cost(cols,rows,scrollback){
  if(!Number.isInteger(cols)||cols<20||cols>500||!Number.isInteger(rows)||rows<5||rows>200||!Number.isInteger(scrollback)||scrollback<0||scrollback>6000)throw Error('Invalid emulator geometry');
  return this.overheadBytes+cols*(rows*2+scrollback)*this.bytesPerCell;
 }
 reserve(key,cols,rows,scrollback){
  if(typeof key!=='string'||!key||key.length>512)throw Error('Invalid emulator identity');
  const bytes=this.cost(cols,rows,scrollback),previous=this.allocations.get(key)||0;
  if(this.allocations.size+(previous?0:1)>this.maxRenderers||this.usedBytes-previous+bytes>this.maxBytes)return false;
  this.allocations.set(key,bytes);return true;
 }
 release(key){this.allocations.delete(key)}
 get usedBytes(){return [...this.allocations.values()].reduce((total,bytes)=>total+bytes,0)}
 status(){return {renderers:this.allocations.size,reservedBytes:this.usedBytes,maxRenderers:this.maxRenderers,maxBytes:this.maxBytes,measurement:'buffer-allocation-model'}}
}
