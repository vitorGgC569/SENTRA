// Shared canonical intent representation for desktop, mobile and host receipts.
export function journalIntent(request){
 if(request.action==='dot_computer_action'){
  if(request.request?.action!=='machine_execute')throw Error('Ação sem contrato de recuperação.');
  const {action,...fields}=request.request;return [action,{space_id:request.space_id,...fields}];
 }
 const {action,project_id,request_key,...fields}=request;
 if((!action?.startsWith('dot_canvas_')||action==='dot_canvas_get')&&!['access_approve','access_reject','coordinator_approval_reply'].includes(action))throw Error('Ação sem contrato de recuperação.');
 return [action,fields];
}
export function canonicalIntent(value){
 function encode(v){
  if(v===null||typeof v==='boolean'||typeof v==='string')return JSON.stringify(v);
  if(typeof v==='number'&&Number.isFinite(v)){
   const wire=JSON.stringify(v);
   if(v!==0&&Math.abs(v)<1e-4)return v.toExponential().replace(/e([+-]?)(\d+)$/,(_,sign,n)=>'e'+(sign||'+')+n.padStart(2,'0'));
   return wire.replace(/e([+-]?)(\d+)$/,(_,sign,n)=>'e'+(sign||'+')+n.padStart(2,'0'));
  }
  if(Array.isArray(v))return '['+v.map(encode).join(',')+']';
  if(v&&Object.getPrototypeOf(v)===Object.prototype)return '{'+Object.keys(v).sort((a,b)=>{const x=Array.from(a),y=Array.from(b);for(let i=0;i<Math.min(x.length,y.length);i++){const d=x[i].codePointAt(0)-y[i].codePointAt(0);if(d)return d}return x.length-y.length}).map(k=>JSON.stringify(k)+':'+encode(v[k])).join(',')+'}';
  throw Error('Intenção contém valor não serializável.');
 }
 // Python's protected journal hashes JSON with ensure_ascii=True.
 return encode(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
}
