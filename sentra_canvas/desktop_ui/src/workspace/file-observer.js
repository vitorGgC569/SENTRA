// One bounded read per exact file scope and bridge, shared by visible editors.
// No filesystem writes, grant preparation or resource creation happen here.
const bridges=new WeakMap();
export function watchWorkspaceFile(bridge,scope,onValue,onError=()=>{}){
 let entries=bridges.get(bridge);if(!entries){entries=new Map();bridges.set(bridge,entries)}
 const key=JSON.stringify(Object.keys(scope).sort().map(k=>[k,scope[k]]));
 let entry=entries.get(key);
 if(!entry){
  entry={listeners:new Set(),running:false,stopped:false};
  entry.check=async()=>{if(entry.running||entry.stopped||globalThis.document?.hidden)return;entry.running=true;
   try{const value=await bridge({action:'workspace_file_get',...scope});if(!entry.stopped)for(const listener of entry.listeners)listener.onValue(value)}
   catch(error){if(!entry.stopped)for(const listener of entry.listeners)listener.onError(error)}
   finally{entry.running=false}
  };
  entry.timer=setInterval(()=>void entry.check(),3000);globalThis.window?.addEventListener('focus',entry.check);entries.set(key,entry);
 }
 const listener={onValue,onError};entry.listeners.add(listener);
 return()=>{entry.listeners.delete(listener);if(!entry.listeners.size){entry.stopped=true;clearInterval(entry.timer);globalThis.window?.removeEventListener('focus',entry.check);entries.delete(key)}};
}
