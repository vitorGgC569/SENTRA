/** Read-only, versioned and host-bound display snapshot interchange.
 * SHA256 integrity is NOT authentication: trustedSha256 MUST arrive through a
 * separately authenticated SENTRA host. Never imports into ControlStore/Yjs.
 */
import {createHash,timingSafeEqual} from "node:crypto";
import * as Y from "yjs";
import {validateYDocument,workspaceFromDocument,MAX_SNAPSHOT_BYTES} from "./policy.mjs";
const deny=()=>{throw Error("collaboration-denied");};
export const DISPLAY_ENVELOPE_VERSION=1;
export const MAX_ENVELOPE_BYTES=1400000;
const sha=bytes=>createHash("sha256").update(bytes).digest("hex");
const revision=n=>Number.isSafeInteger(n)&&n>=0;
const validWS=ws=>workspaceFromDocument("sentra-collab:v1:"+ws);
function encodedDoc(binary) {
  if(!(binary instanceof Uint8Array)||binary.byteLength>MAX_SNAPSHOT_BYTES)deny();
  const doc=new Y.Doc();
  try {
    for(const key of ["layout","nodes","notes"])doc.getMap(key);
    Y.applyUpdate(doc,binary);
    validateYDocument(doc,Y);
    return Object.freeze({
      layout:Object.freeze(structuredClone(doc.getMap("layout").toJSON())),
      nodes:Object.freeze(Object.fromEntries(Object.entries(doc.getMap("nodes").toJSON())
        .map(([k,v])=>[k,Object.freeze(structuredClone(v))]))),
      notes:Object.freeze(structuredClone(doc.getMap("notes").toJSON()))
    });
  }catch{deny();}finally{doc.destroy();}
}
function encodedSnapshot({workspaceId,revision:rev,snapshot}) {
  validWS(workspaceId);
  if(!revision(rev)||!(snapshot instanceof Uint8Array))deny();
  encodedDoc(snapshot);
  const binary=Buffer.from(snapshot);
  const object={format:"SENTRA_DISPLAY_ONLY",version:DISPLAY_ENVELOPE_VERSION,
    workspaceId,revision:rev,payloadSha256:sha(binary),payloadBase64:binary.toString("base64")};
  const bytes=Buffer.from(JSON.stringify(object),"utf8");
  if(bytes.byteLength>MAX_ENVELOPE_BYTES)deny();
  return {bytes:new Uint8Array(bytes),sha256:sha(bytes)};
}
export async function exportVerifiedSnapshot({workspaceId,authorizeRead,loadSnapshot}={}){
  validWS(workspaceId);
  if(typeof authorizeRead!=="function"||typeof loadSnapshot!=="function")deny();
  try {
    if(await authorizeRead({workspaceId})!==true)deny();
    const loaded=await loadSnapshot({workspaceId});
    if(!loaded||!revision(loaded.revision))deny();
    // A zero-revision workspace may have no binary; export an empty Y.Doc.
    let snapshot=loaded.snapshot;
    if(snapshot===null&&loaded.revision===0){
      const empty=new Y.Doc();
      try{
        for(const k of ["layout","nodes","notes"])empty.getMap(k);
        snapshot=Y.encodeStateAsUpdate(empty);
      }finally{empty.destroy();}
    }
    return encodedSnapshot({workspaceId,revision:loaded.revision,snapshot});
  }catch{deny();}
}
export function inspectVerifiedSnapshot({bytes,workspaceId,minRevision=0,trustedSha256}={}){
  validWS(workspaceId);
  if(!(bytes instanceof Uint8Array)||bytes.byteLength>MAX_ENVELOPE_BYTES||
     !revision(minRevision)||typeof trustedSha256!=="string"||
     !/^[a-f0-9]{64}$/.test(trustedSha256))deny();
  const fingerprint=Buffer.from(sha(bytes),"hex");
  if(!timingSafeEqual(fingerprint,Buffer.from(trustedSha256,"hex")))deny();
  try {
    const raw=Buffer.from(bytes).toString("utf8");
    const v=JSON.parse(raw);
    if(!v||Array.isArray(v)||typeof v!=="object"||
       Object.keys(v).join(",")!=="format,version,workspaceId,revision,payloadSha256,payloadBase64"||
       v.format!=="SENTRA_DISPLAY_ONLY"||v.version!==DISPLAY_ENVELOPE_VERSION||
       v.workspaceId!==workspaceId||!revision(v.revision)||
       v.revision<minRevision||
       typeof v.payloadSha256!=="string"||!/^[a-f0-9]{64}$/.test(v.payloadSha256)||
       typeof v.payloadBase64!=="string"||
       v.payloadBase64.length>Math.ceil(MAX_SNAPSHOT_BYTES/3)*4+4||
       !/^[A-Za-z0-9+/]*={0,2}$/.test(v.payloadBase64)||
       JSON.stringify(v)!==raw)deny();
    const snapshot=Buffer.from(v.payloadBase64,"base64");
    if(snapshot.toString("base64")!==v.payloadBase64||snapshot.byteLength>MAX_SNAPSHOT_BYTES||
       !timingSafeEqual(Buffer.from(sha(snapshot),"hex"),Buffer.from(v.payloadSha256,"hex")))deny();
    return Object.freeze({workspaceId:v.workspaceId,revision:v.revision,
      verified:true,display:encodedDoc(snapshot),restoreAllowed:false});
  }catch{deny();}
}
