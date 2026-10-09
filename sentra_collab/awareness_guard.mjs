/**
 * Hocuspocus v4 pre-decode guard for raw awareness frames.
 * The upstream scratch Awareness.getStates() omits null tombstones, so the
 * higher-level beforeHandleAwareness hook cannot authenticate removals.
 * Validate raw clientId/clock/null BEFORE the receiver processes the message.
 */
import * as decoding from "lib0/decoding";
const deny=()=>{throw Error("collaboration-denied");};
export function readAwarenessFrame(bytes,documentName) {
  if(!(bytes instanceof Uint8Array)||bytes.byteLength>81920)deny();
  try{
    const decoder=decoding.createDecoder(bytes);
    const rawAddress=decoding.readVarString(decoder);
    const address=rawAddress.split("\0",1)[0];
    if(address!==documentName)deny();
    const type=decoding.readVarUint(decoder);
    if(type!==1)return null; // only awareness needs special tombstone handling
    const payload=decoding.readVarUint8Array(decoder);
    if(decoding.hasContent(decoder))deny();
    const input=decoding.createDecoder(payload);
    const count=decoding.readVarUint(input);
    // One awareness identity per connection/frame (including tombstones).
    if(count!==1)deny();
    const clientId=decoding.readVarUint(input);
    const clock=decoding.readVarUint(input);
    const state=JSON.parse(decoding.readVarString(input));
    if(decoding.hasContent(input)||!Number.isSafeInteger(clientId)||
       clientId<0||!Number.isSafeInteger(clock)||clock<0||
       (state!==null&&(typeof state!=="object"||Array.isArray(state))))deny();
    return {clientId,clock,state,payload};
  }catch{deny();}
}
