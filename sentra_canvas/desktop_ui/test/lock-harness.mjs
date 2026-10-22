// Explicit Web Locks model for deterministic contract tests, not a browser proof.
export function testLocks(){
 const keys=new Map();
 return {request(key,options,callback){
  const run=typeof options==='function'?options:callback;
  let state=keys.get(key);
  if(options?.ifAvailable&&state?.count)return Promise.resolve().then(()=>run(null));
  if(!state){state={count:0,tail:Promise.resolve()};keys.set(key,state)}
  state.count++;
  const task=state.tail.then(()=>run({name:key}));state.tail=task.catch(()=>{});
  return task.finally(()=>{state.count--;if(!state.count&&keys.get(key)===state)keys.delete(key)});
 }};
}
